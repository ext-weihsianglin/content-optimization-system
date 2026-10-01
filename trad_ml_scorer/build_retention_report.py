"""Build portable v2 reports and plots from frozen results; no model reselection."""

import argparse
import base64
import csv
from collections import Counter
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import RocCurveDisplay

from trad_ml_scorer.retention_features import FEATURE_NAMES, WHOLE_NAMES
from trad_ml_scorer.lr_features import FEATURE_NAMES as V1_NAMES
from trad_ml_scorer.train_lr import save_plot


def glossary():
    notes = Path(__file__).with_name("lr_report_notes.md").read_text().split("## Interesting and promising")[0]
    descriptions = {}
    for line in notes.splitlines():
        if line.startswith("| "):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 3:
                descriptions[cells[0]] = cells[1] + " " + cells[2]
    descriptions.update({
        "log_word_count": "How much text did the retention parser keep across the document? Large counts are squeezed with log1p. This includes retained surrounding content, not only a main article.",
        "coverage_body": "How many of the question's meaningful word tokens appear anywhere in the retained document? Surrounding text can contribute.",
        "coverage_headings": "How many question words appear across all retained headings? Uses structured heading blocks.",
        "coverage_intro": "How many question words appear in the first 200 retained tokens? A site header can come before the article.",
        "log_heading_count": "How many retained heading blocks are there? Large counts are squeezed with log1p.",
        "log_h1_count": "How many retained heading blocks are top-level H1 headings? Counts are squeezed with log1p.",
        "log_list_items": "How many retained list-item blocks are there, including nested items? Container and child text are not counted twice.",
        "log_table_count": "How many structured table blocks were retained? Counts tables, not rows or cells.",
        "log_paragraph_count": "How many paragraph blocks did the parser keep? This includes prose inside list items; it is not just the number of original P tags.",
        "log_code_count": "How many preformatted code blocks were retained? Inline code is not counted separately.",
        "log_ordered_steps": "How many items directly belong to numbered lists? Nested unordered bullets do not count as numbered steps.",
        "has_table": "Is at least one structured table retained?",
        "has_list": "Is at least one structured list retained?",
        "headings_per_1000_words": "How many retained headings are there per 1,000 retained word tokens? Missing when there are no tokens.",
        "list_items_per_1000_words": "How many retained list items are there per 1,000 retained word tokens? Missing when there are no tokens.",
        "log_source_script_count": "How many script tags did the new parser inventory find in the original HTML? Counts are squeezed; scripts never become article text.",
        "retained_text_fraction": "What share of the parser's original source-text tokens survived into the retained text? Capped at one. This replaces v1's main-content focus and removal fractions.",
        "needs_review": "Did the retention policy flag this selected document for review? A warning stays visible even when its content can be scored.",
        "possible_error_response": "Did the new source inventory spot error-like wording? It can also match an article discussing errors, so it is a clue rather than proof.",
        "sparse_body": "Does the retained document have at most 30 word tokens?",
        "format_html": "Did the new format classifier identify HTML? Markdown and plain text use their native parser.",
        "coverage_h1": "How many question words appear in the retained top-level headings?",
        "coverage_table_headers": "How many question words appear in table header cells? Only cells marked as headers count.",
        "best_section_coverage": "Which heading-delimited section matches the most question words, and what fraction does it match?",
        "mean_section_coverage": "On average, how much of the question does each retained section mention?",
        "matching_section_fraction": "What fraction of retained sections mention at least one meaningful question word?",
        "best_section_heading_coverage": "Does the heading of the best-matching section itself mention the question? Ties choose the first section.",
        "best_section_position": "How far down the list of sections is the best match? Zero means first, one means last. If all sections score zero, the first section wins the tie.",
        "comparison_x_table_header_coverage": "For comparison-style questions, do table headers mention the question words? Zero for other question styles.",
        "how_to_x_ordered_steps": "For 'how to' questions, how many numbered steps are available? Uses the squeezed step count; zero for other questions.",
    })
    return descriptions


def render(lines, output):
    (output / "report.md").write_text("\n".join(lines).rstrip() + "\n")
    parts, table = [], []
    def flush():
        if not table:
            return
        rows = [[html.escape(c.strip()) for c in r.strip("|").split("|")] for r in table]
        parts.append('<div class="table"><table><thead><tr>'+''.join('<th>'+c+'</th>' for c in rows[0])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+c+'</td>' for c in r)+'</tr>' for r in rows[2:])+'</tbody></table></div>')
        table.clear()
    for line in lines:
        if line.startswith('|'):
            table.append(line)
            continue
        flush()
        if not line:
            continue
        if line.startswith('!['):
            title, filename = line[2:].split('](')
            encoded = base64.b64encode((output / filename[:-1]).read_bytes()).decode()
            parts.append(f'<img alt="{html.escape(title)}" src="data:image/png;base64,{encoded}">')
        elif line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            parts.append(f'<h{level}>'+html.escape(line[level:].strip())+f'</h{level}>')
        else:
            parts.append('<p>'+html.escape(line).replace('**','').replace('`','')+'</p>')
    flush()
    css='body{margin:0;background:#edf2f7;color:#24364b;font:16px/1.65 system-ui,sans-serif}main{max-width:1120px;margin:32px auto;background:white;padding:40px 48px;border-radius:16px}h1{color:#123b58}h2{margin-top:38px;border-top:1px solid #dce5ee;padding-top:24px}img{width:100%;height:auto}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid #dae3ed}th{background:#e9f1f8}td:first-child{overflow-wrap:anywhere;min-width:160px}@media(max-width:700px){main{margin:0;padding:20px}}'
    (output / 'report.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Retention LR v2 results</title><style>'+css+'</style></head><body><main>'+''.join(parts)+'</main></body></html>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('trad_ml_scorer/v2'))
    parser.add_argument('--data-dir', type=Path, default=Path('data/trad_ml_scorer/v2'))
    args = parser.parse_args()
    output = args.output_dir
    selection = json.loads((output / 'selection.json').read_text())
    manifest = json.loads((output / 'dataset_manifest.json').read_text())
    results = json.loads((output / 'test_metrics.json').read_text())
    records = [json.loads(line) for line in (args.data_dir / 'records.jsonl').read_text().splitlines()]
    references = Counter(row['snapshot_id'] for row in records)
    accounting = {'input_records': len(records), 'distinct_snapshots': len(references),
                  'extra_snapshot_references': sum(n - 1 for n in references.values()),
                  'shared_snapshots': sum(n > 1 for n in references.values()),
                  'records_on_shared_snapshots': sum(n for n in references.values() if n > 1),
                  'records_without_archive': sum(not (args.data_dir / 'documents' / (r['snapshot_id'] + '.json.gz')).exists() for r in records)}
    assert accounting['records_without_archive'] == 0
    (output / 'snapshot_accounting.json').write_text(json.dumps(accounting, indent=2) + '\n')
    selected_name = selection['selected_name']
    chosen = results['models'][selected_name]
    m = chosen['all']
    ci = chosen['host_bootstrap_95_percent']['roc_auc']
    with (output / 'test_predictions.csv').open() as stream:
        predictions = list(csv.DictReader(stream))
    chosen_predictions = [r for r in predictions if r['variant'] == selected_name]
    y = np.array([int(r['is_cited_high']) for r in chosen_predictions])
    p = np.array([float(r['probability']) for r in chosen_predictions])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    RocCurveDisplay.from_predictions(y, p, ax=axes[0], name=selected_name)
    axes[0].plot([0,1],[0,1],'--',color='gray')
    axes[0].set_title('Reused host benchmark: ROC')
    observed, predicted = calibration_curve(y, p, n_bins=8, strategy='quantile')
    axes[1].plot(predicted, observed, 'o-', color='#16836b')
    axes[1].plot([0,1],[0,1],'--',color='gray')
    axes[1].set(xlim=(0,1),ylim=(0,1),xlabel='Mean predicted P(top)',ylabel='Observed top fraction',title='Sample calibration')
    matrix = np.array(m['confusion_matrix'])
    axes[2].imshow(matrix,cmap='Blues')
    for (i,j), value in np.ndenumerate(matrix):
        axes[2].text(j,i,str(value),ha='center',va='center',color='white' if value>matrix.max()*.6 else 'black')
    axes[2].set(xticks=[0,1],yticks=[0,1],xticklabels=['bottom','top'],yticklabels=['bottom','top'],xlabel='Predicted',ylabel='Actual',title='Threshold 0.5')
    fig.tight_layout()
    save_plot(fig,output,'test_diagnostics')
    names=['v1_common','retention_whole_common','retention_sections_common']
    fig, axes=plt.subplots(1,2,figsize=(12,4))
    for ax,metric,title in zip(axes,['roc_auc','log_loss'],['ROC-AUC (higher is better)','Log loss (lower is better)']):
        values=[results['models'][name]['all'][metric] for name in names]
        ax.barh(names,values,color=['#8293a7','#327bb0','#16836b'])
        for i,value in enumerate(values): ax.text(value,i,f' {value:.4f}',va='center')
        ax.set(xlim=(0,max(values)*1.2),title=title)
    fig.suptitle('Same common rows and hostname assignments; each C selected on common validation')
    fig.tight_layout()
    save_plot(fig,output,'common_population')
    data=np.load(args.data_dir/'features.npz')
    mask=(data['splits']=='train') & data['common']
    drift=[]
    for name in set(V1_NAMES)&set(FEATURE_NAMES):
        old=data['X_v1'][mask,V1_NAMES.index(name)]
        new=data['X'][mask,FEATURE_NAMES.index(name)]
        valid=np.isfinite(old)&np.isfinite(new)
        if not valid.any(): continue
        scale=float(np.std(old[valid]))
        difference=float(np.mean(np.abs(new[valid]-old[valid])))
        drift.append({'feature':name,'mean_absolute_change':difference,'relative_to_v1_sd':difference/scale if scale else 0.,'changed_fraction':float(np.mean(~np.isclose(old[valid],new[valid]))),'finite_common_train_rows':int(valid.sum())})
    drift.sort(key=lambda r:r['relative_to_v1_sd'],reverse=True)
    (output/'feature_drift.json').write_text(json.dumps(drift,indent=2)+'\n')
    fig,ax=plt.subplots(figsize=(10,6))
    rows=list(reversed(drift[:12]))
    ax.barh([r['feature'] for r in rows],[r['relative_to_v1_sd'] for r in rows],color='#7559ad')
    ax.set(xlabel='Mean absolute feature change / v1 training standard deviation',title='Representation drift on common training rows (shared feature names)')
    save_plot(fig,output,'feature_drift')
    lines=['# Retention-first LR v2','',f'Selected by validation log loss: {selected_name}, C={selection["selected"]["C"]}; {len(selection["selected"]["feature_names"])} fitted raw features. The model is fit on train only.','',
           f'Reused host-benchmark ROC-AUC: {m["roc_auc"]:.4f} (95% host-bootstrap interval {ci["low"]:.4f}–{ci["high"]:.4f}); {m["rows"]} rows across {m["hosts"]} hosts. This is not a fresh independent test.','',
           '## Source of truth and corpus coverage','',
           'All page content, structure, and source metadata now come from the preprocessing retention-first contract: source_inventory → conservative_dom for HTML or markdown_text for native formats → retention-first selection → downstream document. No v1 extraction fallback is used. Shared v1 helpers supply only tokenization, lexical coverage, and fixed URL regexes.','',
           f'Processed {manifest["unique_snapshots"]} exact snapshots for all {manifest["raw_rows"]} input records. Each compressed document retains blocks, outline, chunks, metadata, quality status, and a source Parquet-row reference with payload/file hashes. Snapshot identity includes both exact payload and exact URL; prompt and label are joined afterward.','',
           f'No input records were lost: {accounting["shared_snapshots"]} snapshots are referenced by {accounting["records_on_shared_snapshots"]} records, giving {accounting["extra_snapshot_references"]} extra references to shared documents. All {accounting["input_records"]} records have an archived snapshot. This deduplicates parsing work, not prompt/label rows, and is unrelated to splitting. Modeling exclusions are accounted for separately below.','',
           'Snapshot statuses: '+json.dumps(manifest['snapshot_statuses'])+'. Unsupported, failed, or contentless snapshots are recorded and excluded rather than silently replaced. Selected content marked needs_review remains scoreable with its warning.','',
           '## Frozen split and eligibility','',
           '| Split | v2 rows | Hosts | Common v1/v2 rows |','| --- | ---: | ---: | ---: |']
    for split,row in manifest['splits'].items(): lines.append(f'| {split} | {row["rows"]} | {row["hosts"]} | {row["common_rows"]} |')
    lines+=['',f'Eligible population: {manifest["eligible_rows"]} v2 rows; {manifest["common_rows"]} in common with v1; {manifest["v1_only_rows"]} v1-only and {manifest["v2_only_rows"]} v2-only. Exclusion counts overlap: '+json.dumps(manifest['exclusions_overlapping'])+'.','',
            'Host assignments are copied from v1, never reshuffled. Hostname, URL, exact HTML, nonempty normalized retained-text, and record overlaps across splits are zero. Repeated prompts across hosts are permitted for this unseen-host scenario.','',
            '## Reused-benchmark results','',
            '| Variant | Population | Rows | ROC-AUC | Log loss | Brier | Accuracy | Within-host AUC |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name,entry in results['models'].items():
        row=entry['all']
        lines.append(f'| {name} | {"common" if name.endswith("_common") else "v2 eligible"} | {row["rows"]} | {row["roc_auc"]:.4f} | {row["log_loss"]:.4f} | {row["brier_score"]:.4f} | {row["accuracy_at_0_5"]:.4f} | {row["mean_within_host_auc"]:.4f} |')
    clean=chosen['clean']
    lines+=['',f'Selected model on the v2 clean subset: n={clean["rows"]}, ROC-AUC={clean["roc_auc"]:.4f}, log loss={clean["log_loss"]:.4f}. This subset uses the new parser status plus a 100-word minimum and differs from v1 cleaning. Constant training-prevalence benchmark log loss: {results["constant"]["log_loss"]:.4f}.','',
            'The common comparison refits every model on the same common training records and chooses C on the same common validation records. It controls population differences, but compares representation AND feature definitions: it is not a pure causal parser ablation. The whole-versus-sections comparison within v2 isolates the added section-feature family more closely. Common models are diagnostic and cannot replace the primary winner based on test performance.','',
            '## Visual comparisons','', '![Reused benchmark diagnostics](test_diagnostics.png)','', '![Common population comparison](common_population.png)','', '![Training feature drift](feature_drift.png)','',
            '## Model importance and sensitivity','',
            'Coefficients use training-standardized measurements. Permutation importance, family-removal refits, and one-feature response curves use validation only. Shuffle error bars are shuffle standard deviations, not confidence intervals. Correlation and unrealistic feature combinations can affect these plots; none estimates the effect of editing a page.','']
    for filename,title in [('coefficients','Final model coefficients'),('permutation_importance','Validation permutation importance'),('family_ablation','Validation family ablation'),('sensitivity_curves','Validation response curves')]:
        lines += [f'![{title}]({filename}.png)','']
    lines += ['## ELI5 guide to the v2 feature pool','',
              f'The whole-document variant has {len(WHOLE_NAMES)} raw features. The section variant adds {len(FEATURE_NAMES)-len(WHOLE_NAMES)}, for {len(FEATURE_NAMES)} total. Log means log1p: very large counts are squeezed. Coverage matches distinct meaningful question-word tokens, not semantic meaning. Missing measurements are imputed and flagged using training data only.','',
              '| Feature | Plain-language meaning |','| --- | --- |']
    descriptions=glossary()
    for name in FEATURE_NAMES: lines.append(f'| {name} | {descriptions[name]} |')
    lines += ['', '## Verification and limits','',
              'The selected model and historical v1 are stored separately. Feature/model/data fingerprints, exact snapshot joins, train-only preprocessing, train/validation disjointness, saved-model parity, and structured-document inference are checked. Frozen benchmark artifacts are not overwritten by retraining.','',
              'Retention is broader, not lossless: navigation and selected elements are removed, some source formats are unsupported, and retained boilerplate can inflate coverage. No browser JavaScript or factual validation is performed. The probability concerns balanced top/bottom labels among already-cited pages, not absolute citation likelihood.','',
              'V1 exploration and its test results were already known before this migration. Test figures here are a reused historical benchmark; fresh hosts or new data are required for independent next-round confirmation. Host-bootstrap intervals describe sampling variability, not freedom from development bias.','',
              '## Promising next round','',
              'Validate query-relevant section selection against retained source blocks, add title phrase alignment and question-to-page-purpose compatibility, and inspect whether boilerplate is driving whole-document coverage. Use development-only host-grouped comparisons. A fresh independently sourced host set is the next evaluation priority; do not keep tuning against this benchmark.','']
    render(lines,output)
    print(output/'report.html')


if __name__ == '__main__':
    main()
