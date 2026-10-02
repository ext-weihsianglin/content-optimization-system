# V7: embedding-similarity prototype

Use the supplied markdownify-corpus-v1-complete / markdownify-openai-v1 pair.
This is a development experiment, not a new editing interpretation or deployment.
Freeze this plan before fitting; leave the existing test benchmark closed.

## Inputs and leakage controls

Join original source-file SHA256 + source row, then assert snapshot, payload hash,
prompt, URL, hostname, label and split parity with the existing v5 eligible rows.
Preserve their hostname assignments and full population; missing semantic fields
stay missing and receive training-fitted imputation/indicators. Report availability
by split and a common available validation subset, with no new exclusions.

Reuse 3072D OpenAI original-space cosine alignment: query to title, best H1,
outline, page, URL path; section-chunk maximum, top-three mean, median, Q25, Q75.
Page/outline vectors may pool chunks according to the upstream serializer. This
changes parsing and representation together versus the retention-based baseline;
it does not isolate the effect of replacing lexical similarity alone.

Independently fitted per-field 32D PCA coordinates are not cross-field comparable.
Do not compute cosine between those coordinates. Also, a whole-training PCA fit
is not a fold-local fit for training CV. No PCA, API calls or corpus-fitted embedding
transform is used in this round. Verify artifacts and independently recompute
alignment on a deterministic bounded development sample from original vectors.

## Controlled comparisons

- Frozen v5 reference: selected 96 features, C=.01, refit on the same train rows.
- Semantic fields: five query-to-field similarities, no term-overlap features.
- Semantic fields + sections: all ten similarity summaries.
- Semantic + context: ten similarities plus v5's 45 prompt-only/document-only
  features. No lexical prompt–document matching; clearly distinguish this mixed
  parser diagnostic from the purely semantic variants.

For the three semantic variants, C = .001/.01/.1/1/10. Use existing four
StratifiedGroupKFold hostname folds, seed 137. Fit imputation/scaling/LR within
each fold. Choose C and primary semantic variant by mean training CV ROC-AUC;
validation is a reported development check, not another tuning loop.

Report ROC-AUC, average precision, log loss, Brier, accuracy and within-host AUC;
paired website bootstrap validation AUC difference against reference, 1000 samples.
Save fitted prototypes and reusable feature caches locally, plus source hashes,
joined identities, fold membership, predictions, metrics and standalone HTML/MD.
No test predictions, editing advice, feature-sensitivity interpretation or default
model change. No promotion claim without later robustness and confirmation work.
