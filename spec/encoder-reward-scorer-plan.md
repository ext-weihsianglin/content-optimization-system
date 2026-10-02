# ModernBERT citation classifier and LLM judge delivery plan

Status: two independent workstreams agreed 2026-10-02. This supersedes the original
serial teacher curation -> encoder distillation -> LR benchmark -> webapp plan.
See the [specification](encoder-reward-scorer.md). No student training or webapp
integration has run; completed judge evidence remains frozen.

| Workstream | Objective | Supervision / evaluation | First delivery |
| --- | --- | --- | --- |
| A: ModernBERT classifier | Improve estimated P(top-cited category \| prompt, document, hostname) over incumbent LR | Original citation-category labels; paired host-held-out comparison | Frozen classifier and LR comparison report |
| B: LLM judge | Refine content-quality criteria and expose complementary scores during webapp analyze | Reviewed query/page judgments and controlled edit preferences | Versioned judge service and evidence-backed analyze scores |

Neither workstream waits for the other. Judge distillation into an encoder is an
optional later cost/latency experiment; teacher scores do not replace citation
labels or become a prerequisite for workstream A.

## Existing evidence and shared source contract

The completed saved Markdownify corpus remains the source of truth. Preserve raw
payload references, document hashes, record joins, original host splits and frozen
LR artifacts. Do not rerun extraction or fetch live websites to prepare inputs.
Use `uv` for Python. Raw datasets, model weights, caches and source-bearing traces
remain outside Git; important reports and specifications belong in delivery PRs.

The user-approved GPT-5 medium judge smoke is complete: 12 cases, all three stages
first-pass valid, 36 valid calls, zero rejected calls/retries, $1.50422125 estimated
cost. [New ELI5 report](../analysis/teacher-markdownify-gpt5-selection-smoke-v1-eli5.html),
[findings](../analysis/teacher-markdownify-gpt5-selection-smoke-v1.md),
[source preparation](../analysis/teacher-markdownify-packages-v2.html).
`teacher-selection-v1` implements fixed requirement slots, allowed evidence IDs,
backend whole-block copying and scope-aware states. Mechanical validity is not
reviewed grading accuracy. The 120-case pilot and 18 blinded edit pairs are prepared,
but pilot annotation and human review have not run. No support packs exist.

Four smoke cases have PDF URLs but stored Markdown/text payloads. Their title-like
body text survives; separate title metadata is unavailable. Defer title inference,
show "No title metadata", and mask unavailable title targets. Quantify prevalence
by source format before training; a missing field must not become a zero grade.

## Workstream A — Citation-category classifier

### A1. Freeze the comparison and prepare the encoder inputs

1. Inventory current LR bundles and predictions; pin exact model, preprocessing,
   feature, split and population hashes. Operational incumbent: the webapp's v7
   `semantic_context` scorer. Retain v5 as an additional reference because frozen
   v7 validation did not establish an improvement over v5. Historical v2/v4 are
   optional diagnostics, not the only comparators.
2. Reuse original top/bottom labels and record/host assignments. Do not consume
   judge component labels in the initial classifier experiment. Check population
   parity and availability without evaluating test performance during development.
3. Freeze a versioned query/title/body representation from saved Markdownify
   documents and a declared hostname input policy. Profile lengths, formats,
   missing metadata and long-document coverage. Preserve code, tables and lists.
4. Include a content-only baseline and a hostname-aware candidate. Hostname is
   available conditioning information in the user's target, never the prediction
   target. Fit any hostname vocabulary/features only on training data; define
   unseen-host behavior and retain disjoint training/validation/test host groups.
   Audit hostname reliance. No random row split that leaks a host across partitions.
5. Record the webapp v7 `markdownify-context-v1` serving contract and its disclosed
   upstream context-feature mismatch (issue #15). Frozen-cache benchmarking and
   live serving behavior need distinct provenance; do not claim an encoder-only
   effect when preprocessing/input contracts differ.

Deliverable: predeclared experiment protocol, source/model inventory, input-length
profile, hardware estimate and reproducible bounded training smoke plan.

### A2. Train and select on training/validation data

1. Pin ModernBERT checkpoint/tokenizer and dependencies; verify a small batch's
   shapes, loss, reload parity, runtime and memory before an expensive fit.
2. Train a binary citation head on original labels. Predeclare a small search over
   learning rate, fine-tuning strategy and input budget using training-host folds.
3. Compare a bounded body view with chunk/page aggregation if lengths justify it.
   Page labels supervise the page-level model, not every chunk independently.
   Keep selection and coverage explicit, including original/edit consistency.
4. Evaluate hostname-aware versus content-only inputs and calibration. Reserve
   calibration data or use training-fold out-of-fold predictions. Consider LR
   feature fusion only as an explicit later ablation if initial results justify it.
5. Freeze selected weights, tokenizer, serialization, calibration and inference
   contract. Use fixed seeds for shortlisted fits and preserve failed experiments.

Gate: reproducible inference, population/split integrity and a frozen model chosen
without test feedback. No teacher annotation reliability gate applies to this fit.

### A3. Benchmark and decide whether to replace LR

Report paired ROC-AUC, average precision, log loss, Brier score and within-host
ranking on matching eligible examples, with paired host-bootstrap intervals.
Inspect calibration, host/query/format/length strata, latency, memory and coverage.
Run bounded fixed-query edit stress cases to detect scoring shortcuts.

Freeze promotion criteria before model selection. A replacement should meet the
agreed predictive/calibration and practical gates; document tradeoffs and retain
LR if evidence is inconclusive. The existing test population has been inspected
historically: one frozen-model comparison is a reused benchmark, not fresh-host
confirmation. Do not retune against it or repeatedly evaluate alternatives there.

Deliverables: LR/ModernBERT Markdown and HTML report, paired predictions, model
manifest and replace/retain recommendation. Any webapp scorer switch is a separate
reviewable integration with version identity and rollback; do not change defaults
merely because a candidate trained successfully.

## Workstream B — Refine the judge and ship analyze scores

### B1. Evaluate the rubric, not just the response schema

1. Review the 12-case smoke's checklists, scores, selected evidence and abstentions.
   Hide citation labels and LR predictions from judge/reviewer input. Independently
   review a stratified subset and disagreements; record human adjudication.
2. Use prepared edit pairs and additional bounded cases to test answering versus
   mentioning, useful versus repeated sections, title promises, changed qualifiers,
   unsupported claims, loading/error pages and partial views. Include ties.
3. Freeze numeric acceptance criteria for rubric reliability, evidence relevance,
   edit preference and operational latency/cost. Refine prompts on development
   examples; reserve separate cases for checking a selected prompt.
4. Prioritize intent fulfillment and section usefulness. Keep title consistency a
   separate applicability-aware diagnostic: all eight supplied smoke titles scored
   3, including a loading screen. Factual support is unassessable without a separately
   supplied pack; copied source text does not establish real-world truth.
5. Keep the approved GPT-5 model unless the user approves a change. Bound additional
   paid runs explicitly; no corpus-scale annotation is required to ship this stream.

Deliverables: versioned judge criteria/prompt, reviewed examples, edit-preference
and failure report, frozen evaluation cases and measured cost/latency. Promote a
rubric only after semantic review; 36/36 valid calls do not certify accuracy.

### B2. Integrate in the webapp analyze phase

Read-only inspection found `demo-webapp` main at
`6c2cae734995e6aed1afb446512c9c9a62e99efd` (merged PR #5).
Its [scoring contract](https://github.com/ext-weihsianglin/demo-webapp/blob/6c2cae734995e6aed1afb446512c9c9a62e99efd/backend/app/scoring.py#L27-L29)
identifies v7 and the disclosed context-feature mismatch.
[`backend/app/main.py` analyze](https://github.com/ext-weihsianglin/demo-webapp/blob/6c2cae734995e6aed1afb446512c9c9a62e99efd/backend/app/main.py#L120-L151)
returns measured P1 separately from mocked Query alignment/Answer clarity and a
heading-count Structural integrity heuristic. Introduce a separate `judge` result
alongside `p1`, then replace/clearly retire the corresponding mocked editorial
cards. Existing classifier outputs retain their own model identity and meaning.

1. Integrate in an owned checkout/branch and separate demo-webapp PR; read that
   repository's applicable instructions first. This planning change modifies only
   content-optimization-system; no other checkout is edited.
2. Score each distinct target query against the same parsed saved-source document.
   Preserve snapshot/block identity, exact source representation, coverage, title
   applicability and separately supplied evidence-pack identity.
3. Return per-query components, score/applicability, reasons, source pointers,
   coverage and judge execution status. Include prompt/rubric/model version and
   trace/cache identity for reproducibility. Scores are ordinal 0–3, not classifier
   probabilities. Display unavailable checks as unavailable, not zero.
4. Keep extraction and P1 analysis usable if the judge is pending, unavailable or
   fails. Choose a bounded background/on-demand execution path after measuring
   latency. Prevent repeated paid evaluation when draft internally calls analyze:
   cache by complete document/query/view/prompt/model/evidence identity and reuse
   valid original-page results. Changed content or criteria must invalidate cache.
5. Preserve structured selections/backend copying, source distrust, budget caps,
   schema preflight and visible failures. Missing title metadata and missing factual
   packs follow current abstention rules; do not add title/PDF inference as a gate.
6. Dogfood 10–20 offline scenarios: inspect explanations, appropriate abstentions,
   useful and misleading edits, frontend states, latency and cost. Keep this exercise
   qualitative and distinct from reserved classifier or judge evaluation evidence.

Deliverables: judge API adapter, evidence-backed analyze UI, request/cache traces,
meaningful integration tests, inspected demo cases and a separate webapp PR.
Gate: genuine measured judge outputs replace mock signals, users can inspect their
basis, and judge failure cannot erase independently available P1 results.

### B3. Use judge scores as P2 feedback after analyze is useful

Compare original/revised content under the same frozen query requirements, rubric,
evidence and view policy. Initially expose component deltas. Select scalar weights
only from reviewed edit preferences; preserve masks and grounding gates. Do not
change GEPA candidate selection or optimize the judge prompt against generated edits
silently. The current open [demo-webapp PR #8](https://github.com/ext-weihsianglin/demo-webapp/pull/8)
is a GEPA plan with mean-P1 selection, not an implemented judge integration.
Coordinate any objective change in its own reviewed update.

## Optional later connection: distill a validated judge

If measured judge latency/cost warrants it, curate reviewed train/validation labels
and train an encoder component model or multi-task variant. Mask unassessable and
not-applicable targets. Evaluate imitation against the frozen judge and usefulness
against independent reviewed edit preferences. Keep it distinct from the binary
citation classifier and compare multi-task citation performance rather than assume
an improvement. No distillation or bulk annotation is needed for either initial
workstream delivery.

## Decisions before expensive execution or promotion

- A: exact comparator bundles/serving contract, hostname encoding and unseen-host
  behavior, long-document policy, hardware, training budget and numerical gates.
- B: semantic acceptance thresholds, review cases, additional annotation budget,
  factual-pack scope and analyze execution/cache policy after latency measurements.
- Both: pinned versions, reproducible artifacts and evaluation provenance. Neither
  stream establishes prospective citation uplift or human gold for an entire corpus.
