"""Publish the fixed-recipe Markdownify v7 retrain and webapp handoff."""
import json
import re
from pathlib import Path
from markdown_it import MarkdownIt
from trad_ml_scorer.train_lr import plt,save_plot
from trad_ml_scorer.retrain_markdownify import OUTPUT, REPORT


def main():
    r=json.loads((REPORT/'results.json').read_text());v=json.loads((REPORT/'verification.json').read_text())
    names={'original_v7':'Original v7 / legacy context','old_model_markdownify_inputs':'Old model / Markdownify context','retrained_markdownify':'Retrained / Markdownify context'}
    changed=[d for d in r['manifest']['drift'] if d['changed_development_rows']]
    plotted=sorted(changed,key=lambda d:d['changed_development_rows'])
    fig,ax=plt.subplots(figsize=(11,7))
    ax.barh([d['feature'] for d in plotted],[d['changed_development_rows'] for d in plotted],color='#247e8b')
    ax.set(xlabel='Train + validation rows whose value changed (out of 8,485)',title='The same feature functions produced different values under Markdownify')
    fig.tight_layout();save_plot(fig,REPORT,'context_drift')
    delta=r['paired_validation_delta']['retrained_markdownify']
    rows=['# V7.1: retrained with consistent Markdownify inputs','',
          '**Completed:** all 45 context features now come from the same saved Markdownify corpus as the ten semantic similarities. The original v7 is preserved. The new model is `lr-semantic-v7.1`.','',
          'The old model learned page structure from an earlier parser, while the webapp uses Markdownify. Paragraph boundaries and other measurements can change even when the feature functions have the same names. This refit fixes that training-input mismatch. It does not tune a new model family.','',
          '## What changed','',
          f"Rebuilt 45 context columns on all **9,432** existing eligible rows, with **zero new exclusions**. The ten semantic columns are identical to the saved v7 cache. All 55 feature names/order, labels, hostname splits, C=.001, missing-value handling and scaling policy are unchanged. **{len(changed)} context columns** changed somewhere in train/validation.",'',
          '![Context changes](context_drift.svg)','',
          '## Evaluation','',
          '| Configuration | Validation AUC | Within-host AUC | Log loss | Brier | Accuracy |','|---|---:|---:|---:|---:|---:|']
    for name,m in r['validation'].items():
        rows.append(f"| {names[name]} | {m['roc_auc']:.5f} | {m['mean_within_host_auc']:.5f} | {m['log_loss']:.5f} | {m['brier_score']:.5f} | {m['accuracy_at_0_5']:.5f} |")
    rows+=['',f"Corrected four-fold training-host CV AUC: **{r['cv_auc']:.5f}** (original v7: .67440). Validation: 945 rows / 97 hosts. Retrained-versus-original validation AUC difference: **{delta['delta']:+.5f}**, paired 95% website-bootstrap interval **[{delta['low']:+.5f}, {delta['high']:+.5f}]**, 1,000 samples. The difference is small and uncertain. The reason to adopt this artifact is consistent preprocessing, not demonstrated accuracy uplift.",'',
          'The middle row isolates passing Markdownify inputs to the old model, mirroring the reported mismatch. It is diagnostic, not a candidate selected for deployment. Validation is reused development evidence. No test predictions/metrics, new feature selection, regularization search, embedding calls or Platt scaling were performed.','',
          '## Provenance and parity','',
          '- Verified corpus manifest and records/documents indexes against v7 embedding provenance; each loaded compressed document is SHA-checked and its content identity/chunk partition validated.',
          '- Joined by original source-file hash and row; checked prompt, URL, hostname, snapshot, payload, label, split and embedding extraction identity. Never joined by URL alone.',
          '- All imputation/scaling/LR fits use training hosts only; zero hostname overlap between partitions.',
          f"- On **{v['rows']} fixed validation HTML snapshots**, freshly parsed context features and probabilities match those from saved documents within 1e-12. Actual maximum feature delta: {max(x['max_feature_delta'] for x in v['checks']):.2g}; probability delta: {max(x['probability_delta'] for x in v['checks']):.2g}.",
          '- All checked parser files match the corpus fingerprints. The parity check reuses existing semantic scores; it does not rerun the embedding pipeline or execute the webapp.',
          '- Model save/reload produces identical validation predictions. Training recipe, feature hashes, document provenance and runtime dependencies are recorded alongside the artifact.','',
          '## Webapp handoff','',
          'Use the new artifact and shared assembly function together. The legacy v7 model should not receive these recomputed context features.','',
          f'**Model:** `{OUTPUT / "model.joblib"}`','',
          f'**Model SHA256:** `{r["model_sha256"]}`','',
          '```python',
          'from trad_ml_scorer.predict_markdownify import load_model, predict_document',
          '',
          f'model = load_model("{OUTPUT / "model.joblib"}")',
          '# document: current Markdownify structured document with source inventory.',
          '# similarities: all ten named original-space cosines for this prompt/document.',
          'score = predict_document(model, prompt, document, similarities)',
          '```','',
          'The loader rejects the original mixed-parser model, wrong feature order and changed feature-code fingerprints. The assembly function requires Markdownify provenance and the original source word count; it never substitutes old context columns or treats missing cosine as zero.','',
          '**Remaining webapp work:** The webapp is not in this checkout and was not modified or deployed. Wire this model/adapter into it. Its embedding producer must use the same 3,072D OpenAI model, `blocks-v3-markdownify` serializer, chunking, normalization and pooling recipe as the saved run. For proposed edits, rebuild derived text/outline/chunks and invalidate/recompute embeddings for the changed document revision. This adapter cannot detect a caller supplying stale semantic scores. Arbitrary rewritten-document parity and cache invalidation remain part of issue #15.','',
          '## Reuse / reproduce','',
          f'All prepared features, per-row resumable checkpoints, joined IDs, manifest and fitted model persist under `{OUTPUT}`. Original v7 and corpus files were not modified.','',
          '```sh',
          'uv run python -m trad_ml_scorer.retrain_markdownify --workers 2',
          '# After interrupted preparation, rerun with the identical recipe.',
          '# If feature preparation finished but training did not:',
          'uv run python -m trad_ml_scorer.retrain_markdownify --reuse-features',
          'uv run python -m trad_ml_scorer.verify_markdownify_refit',
          'uv run python -m trad_ml_scorer.build_markdownify_refit_report',
          '```','',
          'Completed features/results refuse overwrite. No corpus extraction or embedding regeneration is needed. Report artifacts are under `trad_ml_scorer/v7.1/`; full caches and model weights remain outside Git.','']
    md='\n'.join(rows);(REPORT/'report.md').write_text(md)
    html=MarkdownIt().enable('table').render(md)
    svg=(REPORT/'context_drift.svg').read_text();svg=svg[svg.index('<svg'):]
    html=re.sub(r'<img src="context_drift\.svg"[^>]*>',lambda _:svg,html)
    (REPORT/'report.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Markdownify v7 retrain</title><style>body{font:16px/1.65 system-ui;max-width:1120px;margin:40px auto;padding:24px;color:#243343}table{display:block;overflow:auto;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #ddd}h2{margin-top:40px}svg{max-width:100%;height:auto}code{overflow-wrap:anywhere}pre{overflow:auto;background:#eef4f5;padding:16px}</style></head><body>'+html+'</body></html>')

if __name__=='__main__':main()
