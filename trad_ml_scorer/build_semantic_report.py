"""Plain-language development results for the embedding prototype; no edit advice."""
import json
import re
from pathlib import Path
from markdown_it import MarkdownIt
import numpy as np
from trad_ml_scorer.train_lr import plt, save_plot
from trad_ml_scorer.semantic_features import DESCRIPTIONS

LABELS = {'v5_reference':'V5 reference', 'semantic_fields':'5 field similarities', 'semantic_sections':'10 field + section similarities', 'semantic_context':'10 similarities + 45 context features'}


def main():
    root = Path('trad_ml_scorer/v7')
    result = json.loads((root/'results.json').read_text())
    finalists = result['finalists']
    manifest = result['manifest']
    positions = np.arange(len(finalists))
    fig,ax = plt.subplots(figsize=(11,5))
    ax.barh(positions-.17,[r['cv_auc'] for r in finalists],height=.32,label='Training: four host-separated folds',color='#247e8b')
    ax.barh(positions+.17,[r['validation']['roc_auc'] for r in finalists],height=.32,label='Validation: 97 different hosts',color='#d89432')
    ax.set(yticks=positions,yticklabels=[LABELS[r['variant']] for r in finalists],xlim=(.5,.72),xlabel='ROC-AUC (larger is better; axis starts at 0.5)',title='How well does each model separate top from bottom records?')
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.18),fontsize=8,ncol=2)
    fig.tight_layout();save_plot(fig,root,'comparison')
    entries = [r for r in finalists if r['variant']!='v5_reference']
    fig,ax = plt.subplots(figsize=(11,4))
    for i,row in enumerate(entries):
        delta = row['validation_auc_delta_vs_v5']
        ax.plot([delta['low'],delta['high']],[i,i],lw=3,color='#247e8b')
        ax.scatter([delta['delta']],[i],color='#d89432',zorder=3)
    ax.axvline(0,color='#555',lw=1)
    ax.set(yticks=range(len(entries)),yticklabels=[LABELS[r['variant']] for r in entries],xlabel='Validation ROC-AUC difference versus v5',title='Paired comparisons: dot = difference; line = 95% website-bootstrap interval')
    fig.tight_layout();save_plot(fig,root,'paired_validation')
    best = next(r for r in finalists if r['variant']==result['selected_semantic_variant'])
    delta = best['validation_auc_delta_vs_v5']
    lines = ['# Embedding-similarity prototype: v7','',
        '**Purpose:** Replace literal question-word matching with vector-based question–page similarities. This report measures predictive performance. Page-edit interpretation and recommendations are on hold.','',
        'An embedding turns text into a list of numbers. We compare the direction of two lists (cosine similarity): one for the question, another for a page field. This can recognize related wording without requiring identical words. It does not verify factual accuracy or whether a page truly answers the question.','',
        f"**Development result:** The CV-selected prototype is **{LABELS[best['variant']]}**. Its training CV ROC-AUC is **{best['cv_auc']:.4f}**, while validation ROC-AUC is **{best['validation']['roc_auc']:.4f}**. V5 validation is **{finalists[0]['validation']['roc_auc']:.4f}**. This is not evidence of a validated replacement. The default scorer remains unchanged; the test benchmark was not evaluated.",'',
        '## What we compared','',
        '| Variant | What goes into the model |','|---|---|',
        '| V5 reference | Existing 96 handcrafted measurements. Its fixed C=.01 refit reproduces frozen validation predictions exactly. |',
        '| 5 field similarities | Question compared with title, best H1, outline, whole page and URL path. No term-overlap features. |',
        '| 10 field + section similarities | The five field matches plus five summaries of question-to-section-chunk similarity. |',
        '| 10 similarities + 45 context features | The ten matches plus existing prompt-only/document-only measurements, such as page structure and metadata. No lexical prompt–document matching. |','',
        'All versions use logistic regression. The three semantic variants each try five regularization settings (C=.001/.01/.1/1/10). C and the preferred semantic variant are chosen only by average ROC-AUC over four training folds, with entire websites kept together. Missing-value handling and scaling are fitted separately inside every fold, then on training rows for each final prototype.','',
        '## Results on the same records','',
        'ROC-AUC measures how often a randomly chosen top record scores above a randomly chosen bottom record. Within-host AUC averages that calculation separately across websites. These are high/low label predictions, not estimates of absolute citation probability.','',
        '![Training and validation comparison](comparison.svg)','',
        '| Variant | Features | C | CV AUC | Validation AUC | Within-host AUC | Log loss ↓ | Brier ↓ | Average precision | Accuracy |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in finalists:
        m = r['validation']
        lines.append(f"| {LABELS[r['variant']]} | {r['raw_features']} | {r['C']} | {r['cv_auc']:.4f} | {m['roc_auc']:.4f} | {m['mean_within_host_auc']:.4f} | {m['log_loss']:.4f} | {m['brier_score']:.4f} | {m['average_precision']:.4f} | {m['accuracy_at_0_5']:.4f} |")
    lines += ['', 'Log loss and Brier measure prediction error; lower is better. Accuracy uses a 0.5 threshold. Feature counts exclude automatically added missingness flags. Full confusion matrices, folds and candidate scores are in results.json.','',
        '![Uncertainty around validation differences](paired_validation.svg)','',
        f"The selected prototype differs from v5 by **{delta['delta']:+.4f} validation AUC**, with a paired 95% website-bootstrap interval **[{delta['low']:+.4f}, {delta['high']:+.4f}]**. We resample the same websites for both models, 1,000 times. The interval describes this development comparison; it does not include training or model-selection uncertainty. Validation has already been reused in previous iterations, so this is not independent confirmation.",'',
        '## Where the features came from','',
        '- Corpus: `processed/markdownify-corpus-v1-complete/`.',
        '- Representation run: `representations/runs/markdownify-openai-v1/`.',
        '- Encoder: supplied OpenAI `text-embedding-3-large`, 3,072 dimensions; serializer `blocks-v3-markdownify`.',
        '- Page and outline embeddings can be content-weighted pooled vectors from chunks. H1 similarity takes the best available H1. Section statistics are over chunks, not necessarily one score per unique section.',
        '- Source artifacts and matching corpus records/documents were SHA256-verified. No API calls, live-page fetching or embedding regeneration were needed.','',
        '**Why not use the supplied 32D coordinates?** Query, title, page and other fields have separately fitted PCA axes. Comparing their coordinates directly would compare different coordinate systems. Those fits also use the whole training partition, which includes the held-out fold during training CV. We use original-space similarities, which require no dataset-fitted projection. A projected comparison would need one shared basis applied to both sides, fitted afresh inside each training fold.','',
        '**Comparison limitation:** The new semantic signals come from Markdownify, while v5 uses the retention parser. Thus this comparison changes representation and parsing together. The context variant mixes Markdownify semantic features with the frozen retention-based context. It does not isolate an embedding-only causal effect or establish the incremental benefit over a context-only model.','',
        '## Identity, coverage and leakage checks','',
        'Records join on original source-file hash + source row, then require matching snapshot, payload hash, exact prompt, URL, hostname, label and split. We never join by URL alone. Existing eligible records and host assignments are unchanged; host overlap is zero. Preparation checks test metadata/coverage, but no test predictions or test metrics were computed.','',
        '| Split | Eligible rows | Hosts | Page and section similarities available |','|---|---:|---:|---:|']
    for split,a in manifest['availability'].items():
        lines.append(f"| {split} | {a['rows']} | {a['hosts']} | {a['page_and_section_available']} |")
    lines += ['', 'All 9,432 existing eligible rows match; no new exclusions. The common page-and-section-available validation subset is therefore the full 945 rows. Some optional fields are absent; absence remains NaN until training-fitted imputation, rather than being silently replaced with a zero similarity.','',
        '| Feature | Train missing | Validation missing | Test missing (metadata only) |','|---|---:|---:|---:|']
    for name in DESCRIPTIONS:
        values = [manifest['availability'][s]['missing_per_feature'][name] for s in ('train','validation','test')]
        lines.append(f"| {name} | {values[0]} | {values[1]} | {values[2]} |")
    verification = manifest['verification']
    lines += ['', f"On 20 deterministically selected validation records, we independently recomputed **{verification['similarities_recomputed']} similarities** from the original vectors. Maximum absolute disagreement with the supplied alignment was **{verification['maximum_absolute_error']:.2g}**. This is a bounded numerical/provenance check, not an exhaustive semantic-quality assessment.",'',
        '## Each semantic feature in plain language','',
        'All ten similarities depend on both the prompt and the document. Their values use cosine in the same original embedding space. A higher value means a closer embedding match, not necessarily a better citation outcome.','',
        '| Feature | Meaning |','|---|---|']
    for name,description in DESCRIPTIONS.items():lines.append(f'| `{name}` | {description} |')
    lines += ['', '## Reuse and reproduce','',
        'Saved prototype models and prepared features are under the ignored `data/trad_ml_scorer/v7/` directory. Reuse them to avoid data preparation. Model bundles require the named precomputed features in the saved order; this is an offline prototype, not a live HTML-to-score endpoint. Raw embeddings and fitted weights are not checked into Git.','',
        '```sh',
        'uv run python -m trad_ml_scorer.prepare_semantic --run /path/to/markdownify-openai-v1 --corpus /path/to/markdownify-corpus-v1-complete',
        'uv run python -m trad_ml_scorer.semantic_experiment',
        'uv run python -m trad_ml_scorer.build_semantic_report',
        'uv run python -m pytest -q',
        '```','',
        'Preparation and training refuse to overwrite frozen outputs. Rebuild only the report when caches/results already exist. `results.json` stores source hashes, the complete search and fold assignments; `validation_predictions.json` enables paired checks. `plan.md` records the comparison fixed before fitting.','',
        '## Scope of this prototype','',
        'No further tuning based on these validation readings, no test reopening, no automatic promotion, and no page-edit recommendations in this round. A later round could separate context-only effects, compare encodings under the same parser, or test a shared fold-fitted projection. Any additional comparison should be planned before it is run.','']
    md = '\n'.join(lines)
    (root/'report.md').write_text(md)
    html = MarkdownIt().enable('table').render(md)
    for name in ('comparison','paired_validation'):
        svg = (root/f'{name}.svg').read_text();svg=svg[svg.index('<svg'):]
        html = re.sub(r'<img src="'+name+r'\.svg"[^>]*>',lambda _:svg,html)
    (root/'report.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Embedding similarity prototype</title><style>body{font:16px/1.65 system-ui;max-width:1150px;margin:36px auto;padding:24px;color:#243343}h2{margin-top:42px}table{display:block;overflow:auto;border-collapse:collapse;font-size:14px}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}th{background:#edf4f5}svg{max-width:100%;height:auto}pre{overflow:auto;background:#edf4f5;padding:16px}code{overflow-wrap:anywhere}</style></head><body>'+html+'</body></html>')
    status = f"# V7 status\n\nDevelopment prototype complete. Selected semantic variant: {best['variant']}, C={best['C']}.\nTraining CV AUC {best['cv_auc']:.5f}; validation AUC {best['validation']['roc_auc']:.5f}.\nV5 validation AUC {finalists[0]['validation']['roc_auc']:.5f}. No promotion or test evaluation.\nPrepared cache and fitted prototypes: data/trad_ml_scorer/v7/.\nSee report.html / report.md, results.json, validation_predictions.json and plan.md.\n"
    (root/'STATUS.md').write_text(status)

if __name__=='__main__':main()
