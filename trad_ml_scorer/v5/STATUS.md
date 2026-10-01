# V5 checkpoint

Base: merged PR #5, main f7465ad. This follow-up is packaged with v6 on feat/lr-evidence-v5-v6.

Completed 25 development configurations across five variants and 28 new features.
Selected plus_answer: 10 additional features / 96 total, C=.01. CV ROC-AUC .66185,
validation .67435, reused-test .68088 versus v4 .67904; paired difference interval
[-.00253,+.00604]. This is not a reliable independent gain. Evidence and structured
variants are preserved as evaluated alternatives; no tuning followed test access.

Original concentration/manipulation gates pass. Raw title replacement still causes
~.23 mean probability increase in both v4 and v5; synthetic assertions and URL edits
also inflate predictions. Do not use as an unchecked generation/editing reward.

All 119 tests and 12 subtests pass. Selection verifies full training-only refit,
code/data hashes, unchanged v4 columns and exact row/label/hostname split identity.
Cached-feature parity on 120 validation rows; raw/public inference parity on 20
validation HTML sources. Frozen v1–v4 remain intact. V2 default stays unchanged;
v5 is selected explicitly with data/trad_ml_scorer/v5/model.joblib.

Report.md/report.html include all new and baseline ELI5 descriptions, coefficient
breakdown, permutation/family sensitivity, response curves and raw manipulation
plots. Cache is shared locally with SHA-verified copies; no corpus re-preparation.

Another session owns field embeddings/projection scoping. No embedding calls or
projection work performed here. plan.md records snapshot/field/prompt identities,
encoding provenance, split/test exposure and fold-local projection fitting needed
for later integration. Next round should target grounded evidence and metadata
robustness alongside semantic similarity; use fresh hosts for confirmation.
