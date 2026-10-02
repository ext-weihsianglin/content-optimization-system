"""Report all three controlled ablations, including a no-promotion outcome."""
import json
from pathlib import Path
import re
import joblib
import numpy as np
from markdown_it import MarkdownIt
from trad_ml_scorer.train_lr import plt,save_plot,plot_response_curves
from trad_ml_scorer.build_retention_report import glossary


def main():
    root,cache=Path('trad_ml_scorer/v6'),Path('data/trad_ml_scorer/v6')
    read=lambda name:json.loads((root/f'{name}.json').read_text())
    search,selection,audit,raw,stress=map(read,('search','selection','audit','raw_stress','stress'))
    manifest=json.loads((cache/'manifest.json').read_text());finalists=search['finalists']
    baseline=selection['baseline'];chosen=selection['selected'];variant=chosen['variant']
    plots=[]
    fig,ax=plt.subplots(figsize=(10,5));x=np.arange(len(finalists))
    ax.bar(x-.18,[r['cv_auc'] for r in finalists],.36,label='Grouped training CV')
    ax.bar(x+.18,[r['validation']['roc_auc'] for r in finalists],.36,label='Validation')
    ax.set(xticks=x,xticklabels=[r['variant'] for r in finalists],ylim=(.65,.685),ylabel='ROC-AUC',title='V6: isolated ablations and combined variant');ax.legend()
    fig.tight_layout();save_plot(fig,root,'frontier');plots.append('frontier')
    fig,ax=plt.subplots(figsize=(10,5))
    for r in finalists:
        if r['variant']=='v5_baseline':continue
        ax.plot(range(1,5),np.array(r['fold_auc'])-baseline['fold_auc'],marker='o',label=r['variant'])
    ax.axhline(0,color='black',lw=.8);ax.set(xticks=range(1,5),xlabel='Fixed training-host fold',ylabel='ROC-AUC difference from v5',title='Paired fold differences: no separate resampling per candidate');ax.legend()
    fig.tight_layout();save_plot(fig,root,'paired_folds');plots.append('paired_folds')
    attacks=list(raw['variants']['v5_baseline'])
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    for ax,metric in zip(axes,('mean_delta','p95_increase')):
        for i,r in enumerate(finalists):
            ax.bar(np.arange(len(attacks))+(i-2)*.15,[raw['variants'][r['variant']][a][metric] for a in attacks],.15,label=r['variant'])
        ax.set(xticks=range(len(attacks)),xticklabels=['Headings','Assertion','Title','URL'],ylabel='Probability increase',title=metric)
    axes[1].legend(fontsize=8);fig.tight_layout();save_plot(fig,root,'raw_stress');plots.append('raw_stress')
    # Compare new-family permutation effects; baseline families remain in audit.json.
    fig,ax=plt.subplots(figsize=(11,5));rows=[]
    for entry in audit['audits']:
        for family in entry['family_permutation']:
            if family['family'] in ('corroboration','long_prose','normalization','combined_support'):
                rows.append((entry['variant']+': '+family['family'],family['auc_drop'],family['std']))
    ax.barh([r[0] for r in rows],[r[1] for r in rows],xerr=[r[2] for r in rows]);ax.set(xlabel='Validation ROC-AUC drop (mean ± shuffle SD)',title='Joint added/replacement-family sensitivity; correlation can mask importance')
    fig.tight_layout();save_plot(fig,root,'family_effects');plots.append('family_effects')
    bundle=joblib.load(cache/'model.joblib');names=bundle['feature_names'];model=bundle['pipeline']
    coeff=[{'feature':str(n),'coefficient':float(c)} for n,c in zip(model[0].get_feature_names_out(names),model[-1].coef_[0])]
    coeff.sort(key=lambda r:abs(r['coefficient']),reverse=True)
    (root/'coefficients.json').write_text(json.dumps(coeff,indent=2)+'\n')
    fig,ax=plt.subplots(figsize=(11,max(8,len(coeff)*.23)));ordered=coeff[::-1]
    ax.barh([r['feature'] for r in ordered],[r['coefficient'] for r in ordered]);ax.set(title='Retained model: all standardized coefficients',xlabel='Log odds per training standard deviation')
    fig.tight_layout();save_plot(fig,root,'coefficients');plots.append('coefficients')
    data=dict(np.load(cache/'features.npz'));cols=[manifest['feature_names'].index(n) for n in names]
    selected_audit=next(r for r in audit['audits'] if r['variant']==variant)
    ranked=sorted(selected_audit['permutation'],key=lambda r:r['auc_drop'],reverse=True)
    curves=plot_response_curves(model,data['X'][data['splits']=='train'][:,cols],data['X'][data['splits']=='validation'][:,cols],names,ranked,root)
    (root/'sensitivity.json').write_text(json.dumps(curves,indent=2)+'\n');plots.append('sensitivity_curves')
    lines=['# V6 controlled experiments','',f"Decision: **{variant}**. New candidate promoted: **{selection['new_candidate_promoted']}**.",'',
           '## Results','', '| Variant | CV AUC | CV delta | Validation AUC | Validation delta | Failed gates |','|---|---:|---:|---:|---:|---|']
    for r in finalists:
        gates=next(d['gates'] for d in selection['decisions'] if d['variant']==r['variant'])
        failed=', '.join(k for k,v in gates.items() if not v) or 'none'
        lines.append(f"| {r['variant']} | {r['cv_auc']:.5f} | {r['cv_auc']-baseline['cv_auc']:+.5f} | {r['validation']['roc_auc']:.5f} | {r['validation']['roc_auc']-baseline['validation']['roc_auc']:+.5f} | {failed} |")
    lines += ['', 'Five variants × five regularization values; identical four training-host folds (seed 137), training-only transforms and fitting. C is selected per variant using CV ROC-AUC. The strict CV non-regression gate was declared before outcomes. Small negative CV deltas do not establish statistical harm; they do mean these candidates did not meet this experiment’s promotion rule.', '',
              '![AUC comparison](frontier.svg)','','![Paired folds](paired_folds.svg)','',
              '## What each intervention changes','',
              '- **Corroboration:** replaces nine original title/URL match inputs with products using best answer-sentence coverage. Other source/path-type inputs remain. Body support is lexical, not factual verification.',
              '- **Long prose:** adds 10/25/50-token coverage windows for deduplicated prose segments longer than 80 tokens. Windows stay inside segments. The v5 sentence features are unchanged.',
              '- **Normalization:** adds separate normalized title/path/body/prose coverage, gain and numeric matching. Fixed English plurals, narrow hyphen aliases, number formatting and unit aliases; no learned vocabulary or unit-magnitude conversion. Normalized prose windows retain v5’s 6–80-token eligibility to isolate this change.',
              '- **Combined:** applies all changes; normalized title/path inputs are also multiplied by body support so they do not bypass corroboration.', '',
              '## Robustness and importance','',
              'Original gates: top-one absolute coefficient share ≤20%, top-five ≤60%, top positive feature-permutation share ≤45%; three post-parser edits on 120 validation documents require mean inflation ≤.03 and p95 ≤.08. New raw-edit gate: all four edits must have mean and p95 inflation no more than .01 above v5 on the same 20 validation HTML snapshots. The relative gate tolerates existing v5 weaknesses and is not an absolute safety guarantee.', '',
              '| Variant | Top coefficient share | Top-five share | Top positive permutation share | Title mean inflation | URL mean inflation |','|---|---:|---:|---:|---:|---:|']
    for r in finalists:
        a=next(a for a in audit['audits'] if a['variant']==r['variant'])
        rr=raw['variants'][r['variant']]
        lines.append(f"| {r['variant']} | {r['top1_share']:.1%} | {r['top5_share']:.1%} | {a['positive_permutation_top1_share']:.1%} | {rr['title_query']['mean_delta']:+.4f} | {rr['url_query']['mean_delta']:+.4f} |")
    lines += ['', '### Original post-parser stress results', '', '| Variant | Edit | Mean increase | p95 increase |', '|---|---|---:|---:|']
    for name,attacks in stress['variants'].items():
        for attack,r in attacks.items():
            lines.append(f"| {name} | {attack} | {r['mean_delta']:+.4f} | {r['p95_increase']:+.4f} |")
    lines += ['', 'Corroboration reduces direct title/URL editing sensitivity, but repeated query prose can fabricate its required support: p95 inflation is about .112, versus .066 for v5. Combined reaches .131. This is why metadata improvement alone does not justify promotion.', '']
    lines += ['', '![Raw edits](raw_stress.svg)','','![Family importance](family_effects.svg)','','![Coefficient breakdown](coefficients.svg)','','![Response curves](sensitivity_curves.svg)','',
              'Correlated inputs can spread apparent importance. Family permutations and single-feature response curves can create implausible combinations; neither establishes causal editing benefit. Lexical corroboration cannot prove truth or prevent synthetic supporting prose.', '',
              '## Test and deployment decision','']
    if (root/'test_metrics.json').exists():
        test=read('test_metrics');lines += [f"Frozen candidate reused-test AUC: {test['selected']['roc_auc']:.5f}; prior v5: {test['v5_same_rows']['roc_auc']:.5f}. This is not independent confirmation.",'']
    else:
        lines += ['**No new test evaluation.** All new candidates failed the predeclared development rule; retain v5. The historical v5 test AUC remains 0.68088 on 947 rows / 97 hosts and was not used to choose v6 features. No defaults or frozen v1–v5 artifacts changed.','']
    lines += ['## ELI5: tested feature definitions','', '| Feature | Family | Explanation |','|---|---|---|']
    for family in ('corroboration','long_prose','normalization','combined_support'):
        for n in manifest['families'][family]:lines.append(f"| {n} | {family} | {manifest['descriptions'][n]} |")
    descriptions={**glossary(),**manifest['descriptions']}
    lines += ['', '## Retained baseline feature glossary','', '| Feature | Explanation |','|---|---|']
    for n in manifest['base_names']:lines.append(f'| {n} | {descriptions[n]} |')
    lines += ['', '## Provenance and reproduction','',
              'All v5 record IDs, labels, hostname splits and the selected 96 feature columns are preserved. Cached document hashes and code fingerprints are verified. Raw audit checks feature parity on every original sampled page. Finalization verifies full training-only refit parity and zero hostname overlap. No corpus parsing or embedding generation was repeated.', '',
              'See [plan.md](plan.md) and the package README for predeclared rules and reproduction commands. Runtime models and matrices remain ignored and shared locally. Results from the earlier v5 round are preserved separately.', '',
              '## Follow-up','',
              '- Retain v5 while awaiting the other session’s per-field embedding results. Apply the snapshot/field/prompt identity and fold-local projection-fitting contract already documented in v5.',
              '- Consider corroboration as a robustness research direction only if it measurably reduces editing sensitivity; simple lexical support can itself be fabricated.',
              '- Expand normalization only with language-aware evidence and targeted failure examples. The current narrow English rules are heuristic, not a general morphological analyzer.',
              '- Use new independent hosts for confirmation. Do not relax these gates after seeing results or reopen the reused test to rescue a rejected variant.','']
    md='\n'.join(lines);(root/'report.md').write_text(md)
    rendered=MarkdownIt().enable('table').render(md)
    for name in plots:
        svg=(root/f'{name}.svg').read_text();svg=svg[svg.index('<svg'):]
        rendered=re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,rendered)
    (root/'report.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>V6 controlled experiments</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:24px;color:#243343}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}svg{max-width:100%;height:auto}h2{margin-top:44px}</style></head><body>'+rendered+'</body></html>')

if __name__=='__main__':main()
