"""Report the frozen v8 calibration experiment with reliability and support plots."""
import json
import re
from pathlib import Path
import numpy as np
from markdown_it import MarkdownIt
from scipy.special import expit,logit
from trad_ml_scorer.train_lr import plt,save_plot
from trad_ml_scorer.calibration_experiment import ROOT


def main():
    r=json.loads((ROOT/'results.json').read_text());params=r['parameters'];evaluation=r['validation']
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    colors={'v7.1':'#247e8b','v8':'#db9534'}
    for name,values in evaluation.items():
        occupied=[b for b in values['bins'] if b['count']]
        axes[0].plot([b['mean_probability'] for b in occupied],[b['observed_positive_fraction'] for b in occupied],marker='o',color=colors[name],label=name)
        offset=-.018 if name=='v7.1' else .018
        axes[1].bar(np.arange(.05,1,.1)+offset,[b['count'] for b in values['bins']],width=.034,color=colors[name],label=name)
    axes[0].plot([0,1],[0,1],ls='--',color='#777',label='Perfect calibration')
    axes[0].set(xlabel='Average predicted high-class probability',ylabel='Observed high-class fraction',xlim=(0,1),ylim=(0,1),title='Reliability: closer to the diagonal is better')
    axes[1].set(xlabel='Predicted probability bin',ylabel='Validation records',title='Support: how many records sit in each bin?',xlim=(0,1))
    for ax in axes:ax.legend(fontsize=9)
    fig.tight_layout();save_plot(fig,ROOT,'reliability')
    p=np.linspace(.001,.999,300);z=logit(p)
    fig,ax=plt.subplots(figsize=(7,5));ax.plot(p,expit(params['slope']*z+params['intercept']),color='#db9534',label='V8 calibrated');ax.plot([0,1],[0,1],ls='--',color='#777',label='Unchanged')
    ax.set(xlabel='V7.1 uncalibrated probability',ylabel='V8 calibrated probability',title='The calibration changes confidence, not ranking')
    ax.legend();fig.tight_layout();save_plot(fig,ROOT,'mapping')
    lines=['# V8: Platt calibration on v7.1','',
        '**Question:** When the scorer says “70% high-class probability,” do roughly 70% of comparable sampled records have the high label? V7.1 supplies probabilities, but its sigmoid alone does not guarantee this. V8 adds a small probability correction without changing the base ranking model.','',
        '**Decision: '+r['decision']+'** Point estimates improve, but the uncertainty around the change is too wide to pass the predeclared promotion rule. V8 is saved for inspection; nothing was deployed or silently enabled.','',
        '## What we fitted','',
        f"`v8 probability = sigmoid({params['slope']:.6f} × v7.1 logit + {params['intercept']:.6f})`",'',
        'The input is the LR decision-function score before its sigmoid, not the existing probability. We fit two numbers: a slope and an offset. Here the slope is above one, so the correction generally moves probabilities farther from the middle. It leaves the page ranking unchanged.','',
        '![Probability mapping](mapping.svg)','',
        '| V7.1 score | V8 score |','|---:|---:|']
    for p in (.1,.3,.5,.7,.9):lines.append(f"| {p:.0%} | {expit(params['slope']*logit(p)+params['intercept']):.2%} |")
    lines+=['', '## Fitting without using validation labels','',
        'We split the 7,540 training records (771 hosts) into the existing four hostname-grouped folds. Each fold fits its own imputer, scaler and C=.001 LR on the other hosts. Every training record receives exactly one score from a model that did not train on its host. The two calibration parameters are then fitted on those out-of-fold scores and training labels only.','',
        'The fit uses Platt class-count target smoothing, uniform row weights and no regularization. Positive targets are `(Npos+1)/(Npos+2)` and negative targets `1/(Nneg+2)`; counts use only training data. We minimize mean cross-entropy using stable logaddexp/expit, an analytic gradient, and L-BFGS-B. The fit must converge with a positive slope. This is one recipe, with no calibration-method or parameter search.','',
        'The final base is the exact saved v7.1 model, unchanged. Its weights were fitted on all training hosts, whereas the calibration scores came from smaller fold fits. Validation measures how well the calibration transfers to that final model. Historical feature/C selection and validation exploration mean this is reused development evidence, not independent confirmation.','',
        '## Same validation records, before and after','',
        '| Metric | V7.1 | V8 |','|---|---:|---:|']
    for key,label in [('roc_auc','ROC-AUC ↑'),('mean_within_host_auc','Within-host ROC-AUC ↑'),('log_loss','Log loss ↓'),('brier_score','Brier score ↓'),('ece','ECE ↓'),('average_precision','Average precision ↑'),('accuracy_at_0_5','Accuracy at 0.5')]:
        lines.append(f"| {label} | {evaluation['v7.1'][key]:.6f} | {evaluation['v8'][key]:.6f} |")
    lines+=['', '945 validation records / 97 hosts, identical coverage before and after. No new exclusions. Positive slope preserves ordering; observed AUC and within-host AUC are identical. No new numerical ties, rank inversions or exact 0/1 saturation occurred. A fixed 0.5 threshold can still change classifications when the calibration offset moves the decision boundary.','',
        '### How certain is the change?','',
        'Differences below are V8 minus V7.1; negative is better. Each bootstrap draw resamples the same website clusters for both predictions (1,000 draws). These intervals do not include model-fitting or historical selection uncertainty.','',
        '| Metric difference | Estimate | Paired 95% interval |','|---|---:|---|']
    for name,d in r['paired_differences'].items():lines.append(f"| {name} | {d['delta']:+.6f} | [{d['low']:+.6f}, {d['high']:+.6f}] |")
    lines+=['', 'The predeclared rule requires positive slope, preserved ranking, no saturation/new ties, improvements in both log loss and Brier, and a log-loss interval entirely below zero. Only the last condition fails. We retain v7.1 as the default rather than treating a small favorable point estimate as a confirmed improvement.','',
        '## Reliability: what to look for','',
        'In the left chart, each point groups records with similar predicted probabilities. For example, predictions averaging 60% should have about 60% high labels. The dashed line marks perfect agreement. The right chart shows how much data supports those points. Sparse bins can move a lot with only a few records; empty bins have no reliability point. Connecting lines are visual guides, not fitted curves.','',
        '![Reliability and bin support](reliability.svg)','',
        'ECE is the count-weighted average absolute gap between predicted probability and observed positive fraction. We use ten fixed equal-width bins: [0,.1), [.1,.2), …, [.9,1]. ECE depends on binning, so it is descriptive and not the sole acceptance criterion. A lower ECE here does not prove the model is calibrated across all hosts or probabilities.','',
        '| Bin | V7.1 count | V7.1 predicted / observed | V8 count | V8 predicted / observed |','|---|---:|---|---:|---|']
    def cell(b):return '—' if not b['count'] else f"{b['mean_probability']:.3f} / {b['observed_positive_fraction']:.3f}"
    for a,b in zip(evaluation['v7.1']['bins'],evaluation['v8']['bins']):lines.append(f"| {a['lower']:.1f}–{a['upper']:.1f} | {a['count']} | {cell(a)} | {b['count']} | {cell(b)} |")
    lines+=['', '## API and artifacts','',
        f"Calibration artifact: `{r['calibration_path']}`",'',
        f"SHA256: `{r['calibration_sha256']}`",'',
        f"Bound base model: `{r['provenance']['base_model_path']}`",'',
        f"Base SHA256: `{r['provenance']['base_model_sha256']}`",'',
        '```python',
        'from trad_ml_scorer.predict_platt import load_calibrated_model, predict_calibrated_document',
        f'model = load_calibrated_model("{r["calibration_path"]}")',
        'result = predict_calibrated_document(model, prompt, document, semantic_scores)',
        '# result exposes raw_logit, uncalibrated_high_class_probability,',
        '# calibrated_high_class_probability, model_version and base_model_version.',
        '```','',
        'The loader checks the exact base checksum, feature order, version and implementation fingerprints. Saved/reloaded calibrated predictions match exactly. This is a separate opt-in adapter: existing v7.1 consumers do not change. Document/semantic-score freshness obligations from v7.1 still apply. Webapp integration was not performed.','',
        'OOF logits, labels, record IDs and fold assignments live alongside the calibration artifact in shared `trad_ml_scorer/v8/training_oof.npz`. Results record fit/scored hosts for every fold, input/model/code hashes and optimizer details. Raw data and fitted artifacts stay outside Git.','',
        '## Limits and reproduction','',
        'These probabilities concern `is_cited_high` under balanced host-relative top/bottom sampling, not whether an answer engine will cite a page at all. Calibration does not correct an unknown deployment class prior, establish causal edit uplift, or supply reliable per-host calibration from roughly ten sampled records. No test predictions or metrics were computed. Fresh-host confirmation needs a separately planned dataset and evaluation.','',
        '```sh',
        'uv run python -m trad_ml_scorer.calibration_experiment',
        'uv run python -m trad_ml_scorer.build_calibration_report',
        'uv run python -m pytest -q',
        '```','',
        'The experiment refuses to replace completed artifacts. Reuse the saved calibration and OOF cache; only rebuilding the report is needed for presentation changes. No data preparation, embeddings or changes to v7.1 weights are required.','']
    md='\n'.join(lines);(ROOT/'report.md').write_text(md)
    html=MarkdownIt().enable('table').render(md)
    for name in ('mapping','reliability'):
        svg=(ROOT/f'{name}.svg').read_text();svg=svg[svg.index('<svg'):]
        html=re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,html)
    (ROOT/'report.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V8 Platt calibration</title><style>body{font:16px/1.65 system-ui;max-width:1120px;margin:40px auto;padding:24px;color:#243343}h2{margin-top:44px}table{display:block;overflow:auto;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #ddd}svg{max-width:100%;height:auto}pre{background:#eef4f5;padding:16px;overflow:auto}code{overflow-wrap:anywhere}</style></head><body>'+html+'</body></html>')
    (ROOT/'STATUS.md').write_text('# V8 calibration status\n\n'+r['decision']+'\n\nSee report.html / report.md, results.json, plan.md and validation_predictions.json.\nBase model is corrected Markdownify v7.1; test remains closed.\n')

if __name__=='__main__':main()
