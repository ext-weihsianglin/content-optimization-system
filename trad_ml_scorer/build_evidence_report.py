"""V5 bounded experiment report, including rejected families and embedding handoff."""
import json
from pathlib import Path
import re
import joblib
import numpy as np
from markdown_it import MarkdownIt
from trad_ml_scorer.train_lr import plt, save_plot, plot_response_curves
from trad_ml_scorer.build_retention_report import glossary


def main():
    root=Path('trad_ml_scorer/v5'); cache=Path('data/trad_ml_scorer/v5')
    read=lambda n:json.loads((root/f'{n}.json').read_text())
    search,selection,audit,stress,raw=map(read,('search','selection','audit','stress','raw_stress'))
    selected=selection['selected']; variant=selected['variant']
    permutation=next(r for r in audit['audits'] if r['variant']==variant)
    bundle=joblib.load(cache/'model.joblib'); model=bundle['pipeline']; names=bundle['feature_names']
    manifest=json.loads((cache/'manifest.json').read_text())
    coefficients=[{'feature':str(n),'coefficient':float(c)} for n,c in zip(model[0].get_feature_names_out(names),model[-1].coef_[0])]
    coefficients.sort(key=lambda r:abs(r['coefficient']),reverse=True)
    (root/'coefficients.json').write_text(json.dumps(coefficients,indent=2)+'\n')
    plots=[]
    fig,ax=plt.subplots(figsize=(9,5))
    finalists=search['finalists']; x=np.arange(len(finalists))
    ax.bar(x-.18,[r['cv_auc'] for r in finalists],.36,label='Four-fold training host CV')
    ax.bar(x+.18,[r['validation']['roc_auc'] for r in finalists],.36,label='Validation')
    ax.set(xticks=x,xticklabels=[r['variant'] for r in finalists],ylim=(.64,.69),ylabel='ROC-AUC',title='V5 sparse-feature search: development only')
    ax.legend();fig.tight_layout();save_plot(fig,root,'frontier');plots.append('frontier')
    for name,rows,field,title in [('coefficients',coefficients[::-1],'coefficient','All final standardized coefficients'),
            ('permutation',sorted(permutation['permutation'],key=lambda r:r['auc_drop'])[-20:],'auc_drop','Top 20 validation ROC-AUC permutation effects'),
            ('families',sorted(permutation['family_permutation'],key=lambda r:r['auc_drop']),'auc_drop','Joint family permutation effects')]:
        fig,ax=plt.subplots(figsize=(11,max(5,len(rows)*.23)))
        ax.barh([r.get('feature',r.get('family')) for r in rows],[r[field] for r in rows],color='#267f8f')
        ax.set(title=title,xlabel='Log odds per training SD' if field=='coefficient' else 'Validation ROC-AUC decrease')
        fig.tight_layout();save_plot(fig,root,name);plots.append(name)
    data=dict(np.load(cache/'features.npz')); cols=[manifest['feature_names'].index(n) for n in names]
    ranked=sorted(permutation['permutation'],key=lambda r:r['auc_drop'],reverse=True)
    curves=plot_response_curves(model,data['X'][data['splits']=='train'][:,cols],data['X'][data['splits']=='validation'][:,cols],names,ranked,root)
    (root/'sensitivity.json').write_text(json.dumps(curves,indent=2)+'\n');plots.append('sensitivity_curves')
    fig,ax=plt.subplots(figsize=(10,5)); attacks=list(raw['variants']['selected']); x=np.arange(len(attacks))
    for offset,label in [(-.18,'v4'),(.18,'selected')]:
        ax.bar(x+offset,[raw['variants'][label][a]['p95_increase'] for a in attacks],.36,label=label)
    ax.set(xticks=x,xticklabels=attacks,ylabel='p95 probability increase',title=f'Raw input diagnostics on {raw["rows"]} validation HTML snapshots');ax.legend()
    fig.tight_layout();save_plot(fig,root,'raw_stress');plots.append('raw_stress')
    lines=['# V5: sparse answer and evidence features','',f"Decision: **{variant}**, C={selected['C']}, {len(names)} features. New candidate promoted by development rule: **{selection['new_candidate_promoted']}**.",'',
      '## Development comparison','', '| Variant | Grouped training CV AUC | Validation AUC | Gates |','|---|---:|---:|---|']
    for r in finalists:
        gates=next(d['gates'] for d in selection['decisions'] if d['variant']==r['variant'])
        failed=[k for k,v in gates.items() if not v]
        lines.append(f"| {r['variant']} | {r['cv_auc']:.5f} | {r['validation']['roc_auc']:.5f} | {', '.join(failed) if failed else 'pass'} |")
    lines += ['', 'Five variants × five C values; fixed four-fold training-host CV chooses C, then validation AUC selects among candidates passing predeclared CV-nonregression and concentration/manipulation rules. Train-only median imputation, missing indicators and scaling. The same reused validation set has guided previous iterations; tiny gains are not independent evidence.', '', '![Development search](frontier.svg)', '']
    if (root/'test_metrics.json').exists():
        test=read('test_metrics'); a,b=test['v4_same_rows'],test['selected']; delta=test['paired_auc_delta']
        lines += ['## Frozen reused-benchmark evaluation','','| Metric | V4 | V5 |','|---|---:|---:|']
        for k in ('roc_auc','log_loss','brier_score','accuracy_at_0_5','mean_within_host_auc'):
            lines.append(f'| {k} | {a[k]:.5f} | {b[k]:.5f} |')
        lines += ['',f"947 rows / 97 hosts, same fixed test population. Paired AUC difference {delta['estimate']:+.5f}, 95% host-bootstrap interval [{delta['low']:+.5f}, {delta['high']:+.5f}]. Selection froze before evaluation; no tuning followed test inspection. This is a reused historical benchmark, not independent confirmation.",'']
    else:
        lines += ['## Test status','','No new test evaluation. Retain the existing frozen v4 benchmark; no development winner should be justified using test results.','']
    lines += ['## Importance and sensitivity','',f"Top coefficient share {selected['top1_share']:.1%}; top-five share {selected['top5_share']:.1%}; top positive permutation share {permutation['positive_permutation_top1_share']:.1%}. Gates: 20%, 60%, 45%. Correlated features can dilute individual importance; examine joint family effects too. Balanced importance does not prove no leakage.",'',
              '![Permutation](permutation.svg)','','![Family effects](families.svg)','','![All coefficients](coefficients.svg)','','![Response curves](sensitivity_curves.svg)','',
              'Response curves vary one input at a time and can create implausible combinations. They describe model sensitivity, not causal citation uplift.','',
              '## Manipulation checks','', 'The original three post-parser checks use 120 hash-selected validation documents and retain mean-increase ≤.03 / p95 ≤.08 gates. The raw-input extension is a diagnostic on 20 hash-selected validation HTML snapshots: duplicate query headings, a synthetic numeric assertion, title replacement, and query-shaped URL path. It is not exhaustive and did not choose the winner.','',
              '| Raw edit | V4 mean increase | V5 mean increase | V5 p95 increase |','|---|---:|---:|---:|']
    for a,r in raw['variants']['selected'].items():
        lines.append(f"| {a} | {raw['variants']['v4'][a]['mean_delta']:+.4f} | {r['mean_delta']:+.4f} | {r['p95_increase']:+.4f} |")
    lines += ['', 'The original gates passed, but this broader diagnostic exposes substantial title/URL sensitivity and score inflation from unverified assertions. Title replacement raises scores by roughly 23 percentage points in both models. The candidate remains experimental and must not serve as an unchecked editing reward.', '', '![Raw stress](raw_stress.svg)','', '## New feature glossary (including rejected families)','',
              'Query matching uses the existing fixed English stopword list. Sentence candidates contain 6–80 tokens; exact duplicates count once. These cues do not establish factual accuracy. English definition/unit expressions and simple sentence splitting have multilingual and punctuation limitations. Table rows stay separate from headers; ordered-step text follows parser parent links.','',
              '| Feature | Family | ELI5 |','|---|---|---|']
    newfamilies={k:v for k,v in manifest['families'].items() if k in ('answer','evidence','structured')}
    for family,members in newfamilies.items():
        for n in members:
            lines.append(f"| {n} | {family} | {manifest['descriptions'][n]} |")
    descriptions={**glossary(),**manifest['descriptions']}
    lines += ['', '### Retained baseline features', '', 'These 86 features use the unchanged v4 scoring view. Unsupported or repeated headings do not receive heading credit; source metadata and URL inputs stay original.', '', '| Feature | ELI5 |', '|---|---|']
    for name in manifest['base_names']:
        lines.append(f'| {name} | {descriptions[name]} |')
    lines += ['', 'The full coefficient chart includes all baseline and selected new features.','',
              '## Provenance and reproduction','', 'Source parsing and population filtering were not rerun. Snapshot archive hashes, original feature hashes and extractor versions are recorded; v4 columns, IDs, labels, splits and quality membership are unchanged. Full train-only refit parity and zero hostname overlap passed at selection. The raw stress run verified raw/cached feature parity on all 20 original pages. Models and matrices remain ignored caches.', '',
              'See [plan.md](plan.md) for the predeclared search and embedding integration contract. This round implements no embeddings or projection methods.','',
              '## Next round and embedding handoff','',
              '- Join page-field vectors by exact snapshot ID and field/extraction version; query vectors need prompt hash or record ID. Never join only by URL.',
              '- Obtain model/revision, dimensions, pooling, truncation, missing-field indicators and benchmark populations. Fit learned projections/normalization inside each training fold, then on training only.',
              '- Combine per-field semantic similarity with answer-sentence coverage and factual/table evidence cues. Keep field-level ablations and concentration checks.',
              '- Treat numerical assertions and links as unverified cues. Validate source-supported evidence and broaden metadata/raw-HTML stress tests before using scores as an optimization reward.',
              '- Collect fresh hosts for independent confirmation; do not optimize the next round from this reused test reading.','']
    md='\n'.join(lines);(root/'report.md').write_text(md)
    rendered=MarkdownIt().enable('table').render(md)
    for name in plots:
        svg=(root/f'{name}.svg').read_text();svg=svg[svg.index('<svg'):]
        rendered=re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,rendered)
    (root/'report.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>V5 sparse evidence experiment</title><style>body{font:16px system-ui;max-width:1180px;margin:40px auto;padding:24px;color:#243343}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}svg{max-width:100%;height:auto}h2{margin-top:44px}</style></head><body>'+rendered+'</body></html>')

if __name__=='__main__':
    main()
