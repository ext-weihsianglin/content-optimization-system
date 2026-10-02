"""Replot frozen-model importance for fixed-prompt HTML editing, with exact deltas."""
import json
from pathlib import Path
import re
import numpy as np
from markdown_it import MarkdownIt
from trad_ml_scorer.train_lr import plt,save_plot
from trad_ml_scorer.feature_dependencies import feature_group, feature_metadata, REGISTRY, GROUPS

LABELS={'title_from_existing_h1':'Title ← existing H1','relevant_paragraph_first':'Move relevant paragraph earlier','split_long_paragraph':'Split a long paragraph'}
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
           xlabel='Change in predicted high-class probability (percentage points)',
           title='Prompt and URL fixed: coherent HTML edits, all features recomputed')
    ax.text(0,-.25,'Dots: applicable pages. Diamond: mean. Line: 95% host-bootstrap interval of the mean.\nSmall selected development sample; intervals describe model sensitivity, not citation uplift.',transform=ax.transAxes,fontsize=9)
    fig.tight_layout();save_plot(fig,root,'edit_effects');plots.append('edit_effects')
    # Deterministic first successful edit, not the largest score increase.
    example=next(r for r in analysis['edits'] if r['contributions'])
    ordered=sorted(example['contributions'],key=lambda r:abs(r['delta_log_odds']),reverse=True)
    rows=ordered[:12]
    if len(ordered)>12:rows.append({'feature':'Other changed features','group':'mixed','delta_log_odds':sum(r['delta_log_odds'] for r in ordered[12:])})
    rows=rows[::-1]
    fig,ax=plt.subplots(figsize=(11,max(4,len(rows)*.35)))
    ax.barh([r['feature'] for r in rows],[r['delta_log_odds'] for r in rows],color=[COLORS[r['group']] for r in rows])
    ax.axvline(0,color='black',lw=.8);ax.set(xlabel='Exact contribution to edited − original log odds',title='One concrete edit: feature deltas sum exactly to the score change')
    fig.tight_layout();save_plot(fig,root,'local_contrast');plots.append('local_contrast')
    fig,axes=plt.subplots(3,1,figsize=(13,19),sharex=True,gridspec_kw={'height_ratios':[1,4,4]})
    for ax,group in zip(axes,GROUPS):
        entries=sorted([r for r in coefficients if feature_group(r['feature'])==group],key=lambda r:abs(r['coefficient']))[-20:]
        labels=[r['feature']+(' [URL fixed]' if feature_metadata(r['feature'])['html_edit_role']=='URL fixed' else ' [diagnostic]' if 'diagnostic' in feature_metadata(r['feature'])['html_edit_role'] else '') for r in entries]
        ax.barh(labels,[r['coefficient'] for r in entries],color=COLORS[group])
        ax.axvline(0,color='black',lw=.8)
        ax.set(title=group+' — top 20 by absolute coefficient (or all if fewer)',xlabel='Log odds per training standard deviation')
    fig.tight_layout();save_plot(fig,root,'separated_coefficients');plots.append('separated_coefficients')
    rows=sorted([r for r in permutation if feature_group(r['feature']) in editable],key=lambda r:r['auc_drop'])[-20:]
    fig,ax=plt.subplots(figsize=(11,7))
    ax.barh([r['feature'] for r in rows],[r['auc_drop'] for r in rows],xerr=[r['std'] for r in rows],color=[COLORS[feature_group(r['feature'])] for r in rows])
    ax.set(title='Across-query predictive importance: doc + promptXdoc',xlabel='Existing validation ROC-AUC drop after permutation (mean ± shuffle SD)')
    fig.tight_layout();save_plot(fig,root,'document_permutation');plots.append('document_permutation')
    groups={g:[n for n,assigned in analysis['feature_groups'].items() if assigned==g] for g in GROUPS}
    matched=analysis['matched_support']['prompt_and_host']
    max_control=max((abs(r['serialization_delta_probability']) for r in analysis['edits']),default=0)
    lines=['# Feature importance for fixed-prompt HTML editing','',
           '**Model:** frozen v5, retained by v6. No refit, feature selection or test-set evaluation. This companion reinterprets the model; original experiment reports remain frozen.','',
           '## The right quantity is the change for the same prompt','',
           'For a fixed query and URL, prompt-only terms act as a query-specific intercept. They cancel in a before/after **log-odds** comparison. Keep them in the model: they still set the baseline probability and therefore the probability response to an edit. Prompt–document interactions remain variable and belong in the editing analysis.','',
           '`logit P = intercept + prompt contribution + doc contribution + promptXdoc contribution`','',
           '`Δlogit = Σ β_j [z_j(edited HTML, fixed prompt) − z_j(original HTML, fixed prompt)]`','',
           'Here `z` includes the fitted imputer, missing indicators and training scaler. Pure prompt and URL terms have exactly zero delta. Probability change is `sigmoid(original logit + Δlogit) − sigmoid(original logit)`; feature contributions are additive in log odds, not probability points.','',
           'The modeled probability is the sampled within-host high class **among already-cited pages**, not the probability of being cited at all.','',
           '## 1. Primary view: coherent document edits','',
           'We use the first 40 hash-sorted validation HTML snapshots, selected without label or score-gain filtering. The same prompt and URL are supplied before and after every edit; the aggregate combines different fixed-query pairs, not one shared query. All features are recomputed from the edited HTML. Every applicable edit preserves the visible body word multiset; edits insert no new factual assertions or query stuffing. This does not guarantee unchanged semantics or better editorial quality—moving a paragraph can disrupt context, and the existing H1 may make a poor title.','',
           '![Fixed-prompt edit effects](edit_effects.svg)','',
           '| Edit | Applicable / sampled | Hosts | Mean Δ probability | Median Δ probability | Observed range |','|---|---:|---:|---:|---:|---:|']
    for a,s in analysis['summary'].items():
        if s['rows']:
            lines.append(f"| {LABELS[a]} | {s['rows']} / {len(analysis['sample_record_ids'])} | {s['hosts']} | {100*s['mean_delta']:+.2f} pp | {100*s['median_delta']:+.2f} pp | [{100*s['min_delta']:+.2f}, {100*s['max_delta']:+.2f}] pp |")
        else:lines.append(f'| {LABELS[a]} | 0 | 0 | — | — | — |')
    lines += ['',f"Non-applicable edits are recorded, not counted as zero effects. Confidence intervals resample host clusters (1,000 replicates) when at least five hosts are available; they are descriptive for this small development sample and frozen model. Maximum absolute serialization-only probability change was **{max_control*100:.6f} pp**; each record also stores edit-versus-serialization change.",'',
              '## 2. Exact explanation of one edit','',f"First applicable edit with a changed model contribution: **{LABELS[example['action']]}**. This example was not chosen for maximum gain.",'',
              f"Prompt: {example['prompt']}",'',f"Record: `{example['record_id']}`. Predicted score: **{example['before_probability']:.4f} → {example['after_probability']:.4f}**; Δlogit **{example['delta_log_odds']:+.5f}**.",'',
              '![Exact paired contribution](local_contrast.svg)','',
              'All changed transformed-feature contributions, including missingness effects, are stored in analysis.json and verified to sum to the model logit difference. Fixed prompt and URL contributions are checked to be zero for every edit.','',
              '## 3. Replotted global importance by input dependency','',
              'Three panels separate prompt, doc, and promptXdoc dependencies. Document includes URL, content, metadata and parser diagnostics. Dependency is distinct from editability: path_homepage is doc; path_query_precision is promptXdoc, but both stay fixed during HTML-only edits. Supported path-match features also use body support and may change. Bracket annotations identify fixed-URL and diagnostic signals; diagnostics are not optimization targets.','',
              '![Separated coefficients](separated_coefficients.svg)','',
              '![Document and interaction predictive importance](document_permutation.svg)','',
              '**This permutation plot is still across-query predictive importance**, copied from the original validation audit and filtered by dependency. Hiding prompt-only bars does not make it conditional importance, and it does not estimate an edit’s effect. A standardized coefficient describes a fitted slope; a permutation drop describes predictive reliance. Neither is a causal citation recommendation. A negative coefficient on a coverage feature can arise while related coverage inputs carry positive coefficients; it is not a recommendation to remove relevant text. Recompute the full feature vector for a coherent edit instead.','',
              '## 4. Why we do not claim reliable within-query ranking importance','',
              f"Validation has only **{matched['mixed_label_groups']} same-prompt/same-host group with both labels ({matched['mixed_label_rows']} rows)**. It has {matched['repeated_groups']} repeated groups total ({matched['repeated_rows']} rows). Exact-query groups across hosts contain only {analysis['matched_support']['prompt']['mixed_label_groups']} mixed-label group too. A within-query ranking AUC or label-based conditional permutation estimate would be far too fragile here. We report the support count instead of a misleading near-zero importance estimate.",'',
              '## Better computation and interpretation going forward','',
              '| Question | Preferred computation / plot | Interpretation and limits |','|---|---|---|',
              '| What can change this page’s score for this query? | Real HTML edit → reparse → recompute all features; paired Δprobability with exact Δlogit attribution. | Best editing-oriented view. Keep query, URL and factual content fixed; inspect interactions and all side effects. Score increase is not demonstrated citation uplift. |',
              '| Which signals distinguish documents for the same query? | Within-query (preferably within-host) ranking metrics and grouped conditional permutation on a substantially larger matched dataset. | Keep pure-query features constant. Report effective groups/rows; avoid estimates driven by one pair. |',
              '| Which correlated feature families matter? | Joint family permutation on appropriately matched donors, or predeclared family ablation refits. | Shuffling one correlated feature may understate reliance; unrelated donors can create impossible feature combinations. Fit/refit only development data. |',
              '| Is an effect stable across pages? | Paired edit distributions, applicability counts, host-bootstrap intervals and per-query slices. | Do not show only mean gain or cherry-pick winners. Include negative edits, failed cases, serialization controls and manipulation probes. |',
              '| Should we use SHAP, PDP or ALE? | For LR edits, exact paired logit contributions already solve the attribution problem. If adding SHAP, use a query-conditioned background and correlated groups; use feasible fixed-query ICE/ALE ranges only. | Generic backgrounds can assign query/context effects to apparent editing levers. One-feature interventions can violate feature dependencies. None supplies causal evidence. |',
              '| Will an edit increase real citations? | Grounded editorial checks followed by prospective same-query evaluation with engine/time/exposure controls. | Existing observational relative labels and score gradients cannot establish this. Retain factuality and adversarial checks before optimization. |','',
              '## Feature dependency inventory','', 'The full audit below supersedes the dependency labels in the original fixed_prompt companion, whose five groups mixed dependency with intervention constraints. Original analysis.json and verification.json remain unchanged as provenance of that run. Numeric coefficients, permutations and edit outcomes are reused unchanged. Missing indicators inherit their source dependency. Scope: all 142 retention-based v2–v6 candidates; v1 remains a separate frozen extractor.','', '| Group | Raw feature count | Features |','|---|---:|---|']
    for g,names in groups.items():lines.append(f"| {g} | {len(names)} | {', '.join(names)} |")
    lines += ['', '## Every candidate: dependency and HTML-edit role', '', '| Feature | Dependency | HTML-edit role | Selected v5 | Definition / dependency rationale | Source |', '|---|---|---|---|---|---|']
    selected=set(analysis['feature_groups'])
    for name,meta in REGISTRY.items():
        lines.append(f"| `{name}` | {meta['dependency']} | {meta['html_edit_role']} | {'yes' if name in selected else 'no'} | {meta['reason']} | {meta['source']} |")
    import hashlib
    counts={g:sum(feature_group(n)==g for n in selected) for g in GROUPS}
    audit_result={'selected_raw_counts':counts,'candidate_counts':{g:sum(m['dependency']==g for m in REGISTRY.values()) for g in GROUPS},
                  'transformed_counts':{g:sum(feature_group(r['feature'])==g for r in coefficients) for g in GROUPS},
                  'features':REGISTRY,'source_analysis_sha256':hashlib.sha256((source/'analysis.json').read_bytes()).hexdigest(),
                  'coefficient_sha256':hashlib.sha256(Path('trad_ml_scorer/v5/coefficients.json').read_bytes()).hexdigest()}
    (root/'audit.json').write_text(json.dumps(audit_result,indent=2)+'\n')
    lines += ['', '## Reproduction','', '```sh','uv run python -m trad_ml_scorer.analyze_fixed_prompt --input-dir data/raw','uv run python -m trad_ml_scorer.build_fixed_prompt_report','```','',
              'The analysis command refuses to overwrite frozen results. The plotting command writes corrected visuals to interpretation/dependency_audit from the original fixed_prompt/analysis.json. Input snapshots are read locally; no pages are fetched, no embeddings are generated, and no model/default is changed.','']
    md='\n'.join(lines);(root/'report.md').write_text(md)
    rendered=MarkdownIt().enable('table').render(md)
    for name in plots:
        svg=(root/f'{name}.svg').read_text();svg=svg[svg.index('<svg'):]
        rendered=re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,rendered)
    (root/'report.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>Fixed-prompt document editing interpretation</title><style>body{font:16px system-ui;max-width:1250px;margin:40px auto;padding:24px;color:#243343}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left;overflow-wrap:anywhere}svg{max-width:100%;height:auto}h2{margin-top:44px}</style></head><body>'+rendered+'</body></html>')

if __name__=='__main__':main()
