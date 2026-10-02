"""Replot frozen-model importance for fixed-prompt HTML editing, with exact deltas."""
import json
from pathlib import Path
import re
import numpy as np
from markdown_it import MarkdownIt
from trad_ml_scorer.train_lr import plt,save_plot
from trad_ml_scorer.feature_dependencies import feature_group, feature_metadata, REGISTRY, GROUPS

LABELS={'title_from_existing_h1':'Use main heading as title','relevant_paragraph_first':'Move relevant paragraph earlier','split_long_paragraph':'Split a long paragraph'}
COLORS={'prompt':'#888888','doc':'#247e8b','promptXdoc':'#e39b32','mixed':'#6c7694'}


def main():
    source=Path('trad_ml_scorer/interpretation/fixed_prompt')
    root=Path('trad_ml_scorer/interpretation/dependency_audit')
    root.mkdir(parents=True,exist_ok=True)
    analysis=json.loads((source/'analysis.json').read_text())
    analysis['feature_groups']={n:feature_group(n) for n in analysis['feature_groups']}
    for edit in analysis['edits']:
        for term in edit['contributions']:
            term['group']=feature_group(term['feature'])
    coefficients=json.loads(Path('trad_ml_scorer/v5/coefficients.json').read_text())
    audit=json.loads(Path('trad_ml_scorer/v5/audit.json').read_text())
    permutation=next(r for r in audit['audits'] if r['variant']=='plus_answer')['permutation']
    editable={'doc','promptXdoc'}
    plots=[]
    actions=list(analysis['summary'])
    fig,ax=plt.subplots(figsize=(11,5))
    rng=np.random.default_rng(42)
    for i,a in enumerate(actions):
        rows=[r for r in analysis['edits'] if r['action']==a];summary=analysis['summary'][a]
        if not rows:continue
        ax.scatter([r['delta_probability']*100 for r in rows],i+rng.uniform(-.09,.09,len(rows)),alpha=.55,color='#267f8f',s=22)
        mean=summary['mean_delta']*100
        ax.scatter([mean],[i],marker='D',color='#b64b47',s=65,zorder=4)
        if 'mean_host_bootstrap_95' in summary:
            lo,hi=np.array(summary['mean_host_bootstrap_95'])*100
            ax.plot([lo,hi],[i,i],lw=3,color='#b64b47',zorder=3)
    ax.axvline(0,color='black',lw=.8)
    ax.set(yticks=range(len(actions)),yticklabels=[f"{LABELS[a]} (n={analysis['summary'][a]['rows']})" for a in actions],
           xlabel='Change in model score (percentage points; right = higher)',
           title='Same question, same page address: what changed after an edit?')
    ax.text(0,-.25,'Dot = one page. Diamond = average. Line = uncertainty around the average (95% website bootstrap).\nThese are model responses on a small sample, not measured increases in real citations.',transform=ax.transAxes,fontsize=9)
    fig.tight_layout();save_plot(fig,root,'edit_effects');plots.append('edit_effects')
    # Deterministic first successful edit, not the largest score increase.
    example=next(r for r in analysis['edits'] if r['contributions'])
    ordered=sorted(example['contributions'],key=lambda r:abs(r['delta_log_odds']),reverse=True)
    rows=ordered[:12]
    if len(ordered)>12:rows.append({'feature':'Other changed features','group':'mixed','delta_log_odds':sum(r['delta_log_odds'] for r in ordered[12:])})
    rows=rows[::-1]
    fig,ax=plt.subplots(figsize=(11,max(4,len(rows)*.35)))
    ax.barh([r['feature'] for r in rows],[r['delta_log_odds'] for r in rows],color=[COLORS[r['group']] for r in rows])
    ax.axvline(0,color='black',lw=.8);ax.set(xlabel='Contribution to the internal score change (log odds; right = upward)',title='One edit, explained: which measurements moved the score?')
    fig.tight_layout();save_plot(fig,root,'local_contrast');plots.append('local_contrast')
    fig,axes=plt.subplots(3,1,figsize=(13,19),sharex=True,gridspec_kw={'height_ratios':[1,4,4]})
    for ax,group in zip(axes,GROUPS):
        entries=sorted([r for r in coefficients if feature_group(r['feature'])==group],key=lambda r:abs(r['coefficient']))[-20:]
        labels=[r['feature']+(' [URL fixed]' if feature_metadata(r['feature'])['html_edit_role']=='URL fixed' else ' [diagnostic]' if 'diagnostic' in feature_metadata(r['feature'])['html_edit_role'] else '') for r in entries]
        ax.barh(labels,[r['coefficient'] for r in entries],color=COLORS[group])
        ax.axvline(0,color='black',lw=.8)
        ax.set(title={'prompt':'The question alone (prompt)','doc':'The page alone (doc)','promptXdoc':'The question–page match (promptXdoc)'}[group]+' — strongest weights',xlabel='Model weight on a comparable scale (log odds per training standard deviation)')
    fig.tight_layout();save_plot(fig,root,'separated_coefficients');plots.append('separated_coefficients')
    rows=sorted([r for r in permutation if feature_group(r['feature']) in editable],key=lambda r:r['auc_drop'])[-20:]
    fig,ax=plt.subplots(figsize=(11,7))
    ax.barh([r['feature'] for r in rows],[r['auc_drop'] for r in rows],xerr=[r['std'] for r in rows],color=[COLORS[feature_group(r['feature'])] for r in rows])
    ax.set(title='Which measurements matter when ranking different records?',xlabel='Ranking performance lost when shuffled (ROC-AUC drop; mean ± shuffle SD)')
    fig.tight_layout();save_plot(fig,root,'document_permutation');plots.append('document_permutation')
    matched=analysis['matched_support']['prompt_and_host']
    max_control=max((abs(r['serialization_delta_probability']) for r in analysis['edits']),default=0)
    edit_table=['| Edit | Pages where it applied | Websites | Average change | Middle change | Range |','|---|---:|---:|---:|---:|---:|']
    for action,summary in analysis['summary'].items():
        if summary['rows']:
            edit_table.append(f"| {LABELS[action]} | {summary['rows']} / {len(analysis['sample_record_ids'])} | {summary['hosts']} | {100*summary['mean_delta']:+.2f} points | {100*summary['median_delta']:+.2f} points | [{100*summary['min_delta']:+.2f}, {100*summary['max_delta']:+.2f}] points |")
        else:
            edit_table.append(f"| {LABELS[action]} | 0 | 0 | — | — | — |")
    selected=set(analysis['feature_groups'])
    feature_table=['| Feature | Dependency | HTML-edit role | Selected v5 | Plain-language definition / rationale | Source |','|---|---|---|---|---|---|']
    for name,meta in REGISTRY.items():
        feature_table.append(f"| `{name}` | {meta['dependency']} | {meta['html_edit_role']} | {'yes' if name in selected else 'no'} | {meta['reason']} | {meta['source']} |")
    values={
        'edit_table':'\n'.join(edit_table), 'feature_table':'\n'.join(feature_table),
        'serialization_change':f'{max_control*100:.6f}', 'example_action':LABELS[example['action']],
        'example_prompt':example['prompt'], 'before_score':f"{100*example['before_probability']:.2f}%",
        'after_score':f"{100*example['after_probability']:.2f}%",
        'example_delta':f"{100*(example['after_probability']-example['before_probability']):+.2f}",
        'example_record':example['record_id'], 'example_logit':f"{example['delta_log_odds']:+.5f}",
        'mixed_groups':str(matched['mixed_label_groups']), 'mixed_rows':str(matched['mixed_label_rows']),
        'repeated_groups':str(matched['repeated_groups']), 'repeated_rows':str(matched['repeated_rows']),
        'cross_host_groups':str(analysis['matched_support']['prompt']['mixed_label_groups']),
    }
    template=Path(__file__).with_name('fixed_prompt_report_template.md').read_text()
    md=re.sub(r'{{([a-z_]+)}}',lambda match:values[match[1]],template)
    import hashlib
    counts={g:sum(feature_group(n)==g for n in selected) for g in GROUPS}
    audit_result={'selected_raw_counts':counts,'candidate_counts':{g:sum(m['dependency']==g for m in REGISTRY.values()) for g in GROUPS},
                  'transformed_counts':{g:sum(feature_group(r['feature'])==g for r in coefficients) for g in GROUPS},
                  'features':REGISTRY,'source_analysis_sha256':hashlib.sha256((source/'analysis.json').read_bytes()).hexdigest(),
                  'coefficient_sha256':hashlib.sha256(Path('trad_ml_scorer/v5/coefficients.json').read_bytes()).hexdigest()}
    (root/'audit.json').write_text(json.dumps(audit_result,indent=2)+'\n')
    (root/'report.md').write_text(md)
    rendered=MarkdownIt().enable('table').render(md)
    for name in plots:
        svg=(root/f'{name}.svg').read_text();svg=svg[svg.index('<svg'):]
        rendered=re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,rendered)
    # Keep the main story approachable; make the full inventory available on demand.
    main_story,separator,appendix=rendered.partition('<h2>Technical appendix</h2>')
    if separator:
        rendered=main_story+'<details><summary>Technical appendix · calculations, provenance and all 142 features</summary>'+appendix+'</details>'
    (root/'report.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>What happens when we edit a page?</title><style>body{font:17px/1.65 system-ui;max-width:1100px;margin:32px auto;padding:24px;color:#243343;background:#fcfdfd}p,li{max-width:880px}h1{font-size:2.5rem;line-height:1.2}h2{margin-top:52px;line-height:1.3}h3{margin-top:32px}table{display:block;overflow-x:auto;border-collapse:collapse;width:100%;font-size:14px;margin:24px 0}td,th{padding:10px;border-bottom:1px solid #dce4e8;text-align:left;overflow-wrap:anywhere;min-width:95px}th{background:#edf4f5}svg{max-width:100%;height:auto}blockquote{margin:24px 0;padding:8px 24px;border-left:4px solid #247e8b;background:#edf6f6}summary{cursor:pointer;font-weight:700;font-size:1.15rem}details{margin-top:44px;padding:20px;border:1px solid #cedddd;border-radius:8px}code{font-size:.86em;overflow-wrap:anywhere}pre{padding:16px;background:#edf1f3;overflow:auto}</style></head><body>'+rendered+'</body></html>')


if __name__=='__main__':main()
