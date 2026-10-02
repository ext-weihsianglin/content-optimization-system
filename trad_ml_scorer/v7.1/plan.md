# V7.1: Markdownify context correction

Rebuild the 45 v7 context columns from the user-supplied immutable
`processed/markdownify-corpus-v1-complete` documents. Preserve all ten existing
Markdownify/OpenAI similarities, exact row order, labels and host splits. Keep
v7 semantic_context feature order and C=.001; no hyperparameter search or Platt
calibration. Compare the corrected refit to frozen mixed-parser v7 on training
host-grouped CV and validation. Also quantify what happens if corrected inputs
are passed to the old model, as a diagnostic of the reported webapp mismatch.

Use unique `trad_ml_scorer/v7.1/` artifacts on the shared data volume.
Never replace v7 or corpus artifacts. Validate corpus/run/record/document hashes,
source identities, and semantic alignment lineage. Compute the 45 features with
the existing robust scoring view; expose one canonical ordered assembly function.
Missing values retain the existing imputation policy. Abort rather than silently
substitute legacy context if a selected document is unavailable.

Freeze the model recipe before evaluating validation; same four hostname-grouped
training folds, seed 137. Fit imputer/scaler/LR on each training fold, then all
training rows. Report AUC, within-host AUC, log loss, Brier, AP, accuracy and paired
host-bootstrap validation differences. Test metadata/feature construction may be
audited; do not score or tune on test labels. No new embeddings or API calls.

Check feature and probability parity between saved Markdownify documents and
fresh offline parsing of 20 fixed validation HTML snapshots. Record parser and
feature-code fingerprints, embedding/serializer identity, ordered column names,
and model checksum for webapp integration. The webapp is not in this checkout;
do not claim deployment or arbitrary rewrite/cache invalidation is complete.
