"""Final portable report: ROC-AUC, concentration, stress, and ELI5 feature glossary."""
import json
from pathlib import Path
import joblib
import numpy as np
from markdown_it import MarkdownIt
from trad_ml_scorer.train_lr import plt, save_plot, plot_response_curves
from trad_ml_scorer.build_retention_report import glossary


def main():
    root, cache = Path('trad_ml_scorer/v4'), Path('data/trad_ml_scorer/v4')
    read = lambda name: json.loads((root/f'{name}.json').read_text())
    selection, metrics, audit, stress = map(read,('selection','test_metrics','audit','stress'))
    chosen = selection['selected']; variant = chosen['variant']
    checked = next(r for r in audit['audits'] if r['variant']==variant)
    bundle = joblib.load(cache/'model.joblib'); model = bundle['pipeline']
    names = bundle['feature_names']; transformed = model[0].get_feature_names_out(names)
    coefficients = [{'feature':str(n),'coefficient':float(c)} for n,c in zip(transformed,model[-1].coef_[0])]
    coefficients.sort(key=lambda r:abs(r['coefficient']),reverse=True)
    (root/'coefficients.json').write_text(json.dumps(coefficients,indent=2)+'\n')
    rows = coefficients[::-1]
    fig, ax = plt.subplots(figsize=(11,max(8,len(rows)*.23)))
    ax.barh([r['feature'] for r in rows],[r['coefficient'] for r in rows],color=['#167968' if r['coefficient']>0 else '#b94854' for r in rows])
    ax.set(title='Final LR: every standardized coefficient',xlabel='Log-odds change per training standard deviation')
    fig.tight_layout();save_plot(fig,root,'coefficients')
    permutation = sorted(checked['permutation'],key=lambda r:r['auc_drop'],reverse=True)
    fig, ax = plt.subplots(figsize=(11,7))
    rows = permutation[:20][::-1]
    ax.barh([r['feature'] for r in rows],[r['auc_drop'] for r in rows],xerr=[r['std'] for r in rows],color='#317dab')
    ax.set(title='Validation sensitivity: top 20 features',xlabel='ROC-AUC drop after permutation (mean ± shuffle SD)')
    fig.tight_layout();save_plot(fig,root,'permutation')
    fig, ax = plt.subplots(figsize=(10,5))
    rows = sorted(checked['family_permutation'],key=lambda r:r['auc_drop'])
    ax.barh([r['family'] for r in rows],[r['auc_drop'] for r in rows],xerr=[r['std'] for r in rows],color='#7861ab')
    ax.set(title='Joint feature-family sensitivity',xlabel='Validation ROC-AUC drop (20 joint permutations)')
    fig.tight_layout();save_plot(fig,root,'families')
    data = dict(np.load(cache/'features.npz'))
    manifest = json.loads((cache/'manifest.json').read_text())
    columns = [manifest['feature_names'].index(n) for n in names]
    curves = plot_response_curves(model,data['X'][data['splits']=='train'][:,columns],data['X'][data['splits']=='validation'][:,columns],names,permutation,root)
    (root/'sensitivity.json').write_text(json.dumps(curves,indent=2)+'\n')
    before = json.loads(Path('trad_ml_scorer/v3/stress.json').read_text())['variants']['all']
    after = stress['variants'][variant]
    fig, ax = plt.subplots(figsize=(10,4))
    attacks = list(after); x = np.arange(len(attacks))
    ax.bar(x-.18,[before[a]['p95_increase'] for a in attacks],.36,label='V3 full features')
    ax.bar(x+.18,[after[a]['p95_increase'] for a in attacks],.36,label='V4 selected')
    ax.axhline(.08,color='red',ls='--',label='Predeclared p95 gate')
    ax.set(xticks=x,xticklabels=attacks,ylabel='95th-percentile probability increase',title='Post-parser manipulation checks: 120 validation documents');ax.legend()
    fig.tight_layout();save_plot(fig,root,'stress')
    final, base = metrics['selected'],metrics['v2_same_rows']; delta = metrics['paired_auc_delta']
    lines = ['# LR ROC-AUC frontier: v4', '',
             f"Selected **{variant}**, {len(names)} raw features, C={chosen['C']}; exact v2 population and hostname assignments.", '',
             '## Results', '', '| Metric | Frozen v2 | V4 |','|---|---:|---:|']
    for key in ('roc_auc','log_loss','brier_score','accuracy_at_0_5','mean_within_host_auc'):
        lines.append(f'| {key} | {base[key]:.5f} | {final[key]:.5f} |')
    ci = metrics['host_bootstrap_95_percent']['roc_auc']
    lines += ['',f"Reused benchmark: {final['rows']} rows / {final['hosts']} hosts. V4 ROC-AUC 95% host-bootstrap interval [{ci['low']:.4f}, {ci['high']:.4f}]. Paired AUC difference {delta['estimate']:+.5f}, 95% interval [{delta['low']:+.5f}, {delta['high']:+.5f}] (1,000 host bootstrap replicates).",
              '', 'Test is a reused historical benchmark. The interval quantifies host sampling uncertainty, not repeated-development selection bias. Do not claim independent confirmation or causal citation uplift.', '',
              '## Selection and provenance', '',
              f"Two bounded rounds evaluated 50 configurations total. Four training-host-grouped folds chose C per variant; validation ROC-AUC selected among guardrail-passing finalists. Selected grouped CV AUC: {chosen['cv_auc']:.5f}; validation AUC: {chosen['validation']['roc_auc']:.5f}. Training-only medians, missing indicators, scaling and LR; no train-plus-validation refit. Model selection was frozen before this test evaluation.", '',
              'Raw snapshots were not re-prepared. V4 derives a scoring view from cached retention documents: repeated headings and headings without at least five following content words before the next heading receive no heading credit. This can suppress legitimate parent headings; heading-only documents retain body text. Original parser documents remain intact.', '',
              'Verification reproduced the full training fit, checked hashes and exact row/split identity, and matched raw-input inference on six train/validation snapshots. Cached-feature parity passed for 120 validation documents. No hostname identity, label, source-row position, or split enters a feature.', '',
              '## Importance and sensitivity guardrails', '',
              f"Absolute standardized coefficient shares: top one **{chosen['top1_share']:.1%}**, top five **{chosen['top5_share']:.1%}** (gates 20%/60%). Top positive validation permutation share: **{checked['positive_permutation_top1_share']:.1%}** (gate 45%). Correlation can spread importance among related features: family permutation is shown too. A balanced plot does not prove absence of leakage. URL path matching is the largest individual permutation signal; lexical matching is the largest joint family. Homepage sensitivity is large for the rare binary switch, so these scores must not be used as an unchecked content-editing reward.", '',
              '![Permutation importance](permutation.svg)', '', '![Family importance](families.svg)', '',
              'All transformed coefficients, including missing-value indicators:', '', '![All coefficients](coefficients.svg)', '',
              'Response curves vary one feature while holding others fixed; implausible combinations and correlated features limit interpretation. These are not editing recommendations.', '',
              '![Feature response curves](sensitivity_curves.svg)', '',
              '## Manipulation checks', '',
              'The three predeclared checks append repeated query text, twenty duplicate query headings, or unrelated padding to 120 hash-selected validation documents. Each must have mean probability increase ≤0.03 and p95 ≤0.08. These are post-parser checks, not comprehensive raw-HTML adversarial robustness.', '',
              '| Edit | Mean increase | p95 increase | Maximum increase |','|---|---:|---:|---:|']
    for a,r in after.items():
        lines.append(f"| {a} | {r['mean_delta']:+.4f} | {r['p95_increase']:+.4f} | {r['max_increase']:+.4f} |")
    lines += ['', '![Stress comparison](stress.svg)', '', '## ELI5 feature descriptions', '',
              'All body, heading, section, and composition features now use the v4 scoring view described above. URL and source metadata use original page inputs. Log1p squeezes large counts. Missing measurements are imputed from training data.', '',
              '| Feature | Plain-language description |','|---|---|']
    descriptions = {**glossary(),**manifest['descriptions']}
    descriptions['retained_text_fraction'] = 'How much source text remains in the scoring view after unsupported or repeated headings lose credit? This can still move when source padding changes.'
    for name in names:
        lines.append(f'| {name} | {descriptions[name]} |')
    lines += ['', '## Promising next features and experiments', '',
              '- Answer-bearing sentence coverage and evidence density: reward concise relevant explanations, not repeated headings.',
              '- Table question-to-column and row alignment: distinguish useful comparisons from the mere presence of tables.',
              '- Distinct supported facts, units, and procedure completeness; validate extracted values against source blocks.',
              '- Training-fold-only lexical weighting and multilingual matching, with explicit vocabulary provenance.',
              '- Broader raw-HTML manipulation tests and new independent hosts before another benchmark claim.', '',
              'Avoid rewarding unverifiable authority badges, self-declared freshness, or keyword stuffing. Keep future feature decisions away from the now-inspected test results.', '',
              '## Reproduction', '',
              'See `trad_ml_scorer/README.md`. Frozen data/models are ignored under `data/trad_ml_scorer/v4/`; metrics, audit, verification and this report are inspectable artifacts. The existing v2 inference default is preserved; pass the v4 model explicitly.', '']
    markdown = '\n'.join(lines)
    (root/'report.md').write_text(markdown)
    rendered = MarkdownIt().enable("table").render(markdown)
    for name in ('permutation','families','coefficients','sensitivity_curves','stress'):
        svg = (root/f'{name}.svg').read_text()
        svg = svg[svg.index('<svg'):]
        import re
        rendered = re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,rendered)
    (root/'report.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>LR ROC-AUC frontier v4</title><style>body{font:16px system-ui;max-width:1150px;margin:40px auto;padding:24px;color:#243343}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}svg{max-width:100%;height:auto}h2{margin-top:48px}code{font-size:13px}</style></head><body>'+rendered+'</body></html>')

if __name__ == '__main__':
    main()
