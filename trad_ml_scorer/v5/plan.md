# V5: answer and evidence heuristics

Continue after merged PR #5. Keep v1–v4 frozen, reuse v2 parsed snapshots and
v4 feature matrices, and preserve identical eligible rows/hostname assignments.
Embeddings and projection benchmarking belong to the other session; no embedding
API calls or projection fitting are part of this round.

## Bounded development search

Add three families: unique answer-sentence coverage/proximity; relevant numerical,
unit, definition and linked-evidence cues; table-row/header and numbered-step
alignment. These are lexical cues, not factual verification or semantic similarity.
Use meaningful query tokens with the existing fixed stopword list; deduplicate
sentences before aggregate counts to avoid rewarding exact repetitions.

Compare v4 baseline, each added family, and all families (five variants). C grid
.001/.01/.1/1/10, four training-host-grouped folds (seed 137). Train-only
imputation/scaling/LR. Choose C by CV ROC-AUC; require nondecreasing CV AUC versus
the baseline, then choose by validation ROC-AUC among guardrail-passing finalists.
Keep test closed unless a new candidate wins this development comparison; never
select or revise features using new test readings.

## Guardrails and evidence

Retain coefficient concentration (top1<=20%, top5<=60%), positive permutation
concentration (top1<=45%), and post-parser inflation gates (mean<=.03,p95<=.08).
Inspect family importance. Add diagnostic URL/title substitutions and raw-HTML
query stuffing, reporting their scope honestly rather than asserting robustness.
Freeze model/provenance before optional one-time reused-test evaluation. Publish
HTML/Markdown, visual sensitivity and ELI5 descriptions even if v4 remains best.

## Embedding handoff

Future embeddings should join by exact snapshot_id plus field/extraction version;
query vectors additionally need prompt_hash (or record_id). Do not join by URL.
Record model/revision/dimension/pooling/truncation and preprocessing fingerprints.
Any learned projection, normalization, centering, vocabulary, or feature selection
must fit each training fold only during CV, then training only for final fitting.
Benchmarks must identify split populations and any test exposure. Preserve missing
field indicators; do not silently mix field encodings or substitute missing pages.
This is an integration contract, not an implementation of the other session's work.
