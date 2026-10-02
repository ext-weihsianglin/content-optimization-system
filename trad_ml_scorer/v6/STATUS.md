# V6 controlled-experiment checkpoint

Completed all three requested ideas as independent ablations plus combined and
v5 baseline: 25 configurations, fixed four training-host folds and the same records.
The selected 96 v5 columns were copied exactly; only additional/replacement
features were derived from frozen cached documents. No corpus reparse or embeddings.

Outcome: retain v5. New variants slightly improved validation but all slightly
reduced grouped CV AUC, failing the predeclared non-regression gate. Corroboration
and combined also failed repetition-stress gates; normalization additionally failed
the relative raw-edit gate. No test evaluation was performed or used for selection.

Corroboration lowers title mean inflation .2300 -> .1418 and URL .0661 -> .0185,
but query-repetition p95 rises .0657 -> .1120. Combined p95 rises to .1308. This
is a robustness tradeoff, not a deployable improvement. Report.md/report.html retain
all metrics, paired fold differences, importance, response and manipulation plots,
and ELI5 definitions. Read plan.md for the predeclared protocol.

123 tests / 12 subtests pass. Full training-only refit and hash/split/feature-column
identity verified during finalization. Cached feature parity checked on 120
validation records; fresh raw-parser parity on the same 20 validation HTML sources
as v5. Original v1–v5 reports/models/defaults preserved. The original v5 runtime
model remains the candidate to use; v6 model bundles are experimental audit artifacts.

V6 matrices/models are shared in the main repository's ignored data/trad_ml_scorer/v6
with per-file SHA inventories. No prep rerun is needed in another local session.
This work is packaged with the preceding v5 iteration on feat/lr-evidence-v5-v6.
Await the other session's embedding/projection results; no scope overlap performed.
