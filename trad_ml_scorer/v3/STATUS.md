# Frontier checkpoint

Active goal: improve LR ROC-AUC with richer features and nonconcentrated importance.
Not complete; no candidate promoted, default remains v2. Test not accessed in v3.

Completed: deterministic cached-document extraction, 25 configurations across five
variants, four training hostname-grouped folds, validation coefficient/permutation
screens, post-parser manipulation checks on 120 hash-selected validation rows.
All 113 tests and 12 subtests passed. V1/v2 artifacts remain unchanged.

Best grouped CV: lexical 0.66320 vs v2 0.65648. Best validation: all 0.66803
vs v2 0.66070. Top positive permutation share for all: 11.7%; top standardized
coefficient share 6.0%. Despite this, 20 duplicated query headings increase all's
probability by mean 0.113 and p95 0.224. Lexical is less vulnerable (mean 0.079,
p95 0.168), but not resolved. See progress.html, search.json, audit.json, stress.json.
The audit's selected entry is provisional, NOT a frozen production selection.

Next: introduce a new versioned experiment using unique-heading/deduplicated-section
features and/or training-only manipulation augmentation, compare ROC-AUC and stress
behavior on development data. Do not tune against test. Then freeze the chosen
model and evaluate the reused benchmark once, generate final importance/sensitivity
report and inference support, and verify train-only preprocessing and feature parity.
Do not call the goal complete based on this initial development gain.

Cached features/models: data/trad_ml_scorer/v3 (local, ignored). Input parsing was
not rerun. Scripts refuse overwriting outputs; new iterations need new paths/version.
Prepare script currently has fixed v3 destination; parameterize for subsequent rounds.

Superseded development checkpoint: v4 completed the next scoring-view experiment;
see ../v4/STATUS.md and ../v4/report.html. V3 remains frozen historical evidence.
