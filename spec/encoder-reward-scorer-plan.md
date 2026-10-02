# Teacher curation, encoder distillation, and P2 evaluation plan

Status: implementation authorized; Phase 1 offline preparation complete and GPT-5
smoke complete awaiting human review, 2026-10-01. Contract and evidence:
[encoder reward scorer spec](encoder-reward-scorer.md).

The initial plan was submitted in PR #12. The user subsequently authorized
implementation and explicitly reserved teacher-model choice for discussion.
The user approved GPT-5 at medium reasoning for all 12 smoke cases with a $10
bounded run budget. GPT-5.6 Luna/Sol were unavailable to the current API key;
there was no automatic model substitution. Offline curation, response
contracts, draft rubrics, smoke packets, and controlled edit pairs are available in
[encoder_scorer](../encoder_scorer/README.md); see the
[preparation report](../analysis/teacher-curation-v1.html). Training and later phases
remain gated on reviewed teacher evidence. The [smoke review](../analysis/teacher-gpt5-smoke-v1.md)
records 11 valid body labels, one unavailable stage, rejected attempts, and cost;
completion of the smoke does not satisfy the phase 1 reliability gate.

The markdownify corpus is now the source of truth for future annotation. Recreated
120-case pilot and 12-case smoke packages preserve the frozen case/split/queue IDs;
see the [new preparation report](../analysis/teacher-markdownify-packages-v2.html).
The earlier GPT-5 labels concern LR v2 source documents and are not transferred.

## Phase 1 — Curate supervision from stronger models

Distillation begins with collecting and reviewing teacher judgments; student
parameter training follows in phase 2.

1. Inventory cached retention documents, original labels, frozen host splits, and
   LR models. Freeze versioned references without changing existing artifacts.
   Locate the demo webapp branch/app contract as a read-only integration prerequisite.
2. Draft anchored rubrics and annotation examples for intent fulfillment, title/body
   consistency, section usefulness, and evidence support. Include ambiguous queries,
   insufficient evidence, benign context, comparisons, tables, and repeated content.
3. Curate 100–200 train/validation query-page cases across hosts, query types, page
   roles, lengths, formats, and quality flags. Keep source/evidence identity explicit.
   This small pilot is development evidence, not a held-out performance estimate.
4. Run a 10–20-case teacher smoke test with a fixed model/prompt and bounded budget.
   Inspect actual labels, evidence pointers, omissions, disagreement, latency, and
   cost before expanding. Choose teacher models through a small reviewed comparison,
   rather than assuming a named provider is strongest. Record credentials and budget
   requirements before any paid execution; never store secrets in artifacts.
5. Annotate the pilot, independently double-review about 25% plus ambiguous cases,
   and adjudicate rubric failures. Review a human subset. Hide citation labels and
   LR scores from annotation inputs; derive query requirements before page assessment.
6. Curate controlled edits: supported missing-answer additions, answer removal,
   improved comparisons/steps, misleading titles, repeated headings/query prose,
   unrelated padding, unsupported facts, and changed units/qualifications.
   Obtain per-component labels and blinded pairwise preferences. Include ties.
7. Freeze pilot findings and the revised rubric. Set numerical agreement and evidence
   fidelity acceptance thresholds from reviewed examples before bulk annotation.
   Expand annotation on training data only after the pilot passes; freeze validation
   annotations separately. Keep all edit siblings and evidence-derived variants in
   their source host split. Never use test annotations for rubric or model selection.

Deliverables: rubric and schema, curation manifest, teacher-run provenance/cost
ledger, reviewed examples, disagreement report, frozen teacher labels, and an edit
benchmark partition with development versus evaluation roles declared in advance.
Raw pages and bulk annotation caches remain ignored; commit important reports and
small shareable examples consistent with dataset permissions.

Gate: evidence pointers validate, coverage is explicit, reviewed judgments distinguish
answering from mentioning and support from assertion, and measured reliability meets
the predeclared thresholds. Stop and revise if the teacher rewards manipulation.

## Phase 2 — Train the ModernBERT classifier and distill components

1. Profile token lengths and available hardware. Verify a pinned encoder/tokenizer
   on a small batch using `uv`; inspect output shapes, losses, coverage, runtime,
   and memory before an expensive run.
2. Implement versioned input serialization and explicit long-document handling.
   Compare a bounded content view with chunk/page aggregation if length requires it.
   Keep selection deterministic, traceable, and consistent for original/edit pairs.
3. Train a citation-only content/title model against original binary labels using
   the existing training-host population. Keep hostname identity and citation labels
   out of model input; preserve LR population parity for primary comparisons.
4. Train a multi-task candidate with the reviewed teacher component labels. Mask
   unavailable labels. Keep a narrow predeclared search over fine-tuning strategy,
   learning rate, loss weights, and input budget. Use training-host folds and validation
   for selection; run multiple fixed seeds for shortlisted candidates.
5. Add metadata and an encoder-plus-LR-feature hybrid only as explicit ablations if
   the initial results justify them. Evaluate whether they improve prediction while
   weakening edit behavior. Keep the selected LR default unchanged.
6. Freeze student weights, training/config hashes, data manifests, score calibration,
   output schema, and inference fixtures. Verify reload parity and train-only fitting.
   If calibration is needed, use a reserved development partition or training-fold
   out-of-fold predictions; document its separation from final evaluation.

Deliverables: versioned scorer module/configuration, ignored weight artifacts,
training ledger, component/citation ablations, inference examples, and model report.

Gate: reproducible inference, valid coverage handling, useful component agreement,
and no unacceptable tradeoff between citation performance and edit robustness.
Teacher-score imitation alone is insufficient; use independent reviewed examples.

## Phase 3 — Benchmark against LR and evaluate editing rewards

Freeze the evaluation protocol before student selection. Primary comparators are
committed v2/v4 on exactly the same eligible records. Include v5 retained by v6 only
after its currently local artifacts and inference implementation have been frozen
and made reproducible. V6 rejected variants remain diagnostics, not the default.

| Axis | Measurements |
| --- | --- |
| Citation classification | ROC-AUC, average precision, log loss, Brier score, within-host AUC; paired host-bootstrap intervals |
| Component fidelity | Ordinal agreement/error, per-requirement agreement, claim-state errors, evidence-pointer validity, applicability and coverage |
| Edit preferences | Agreement with blinded reviewed preferences, ties, gains on useful edits, regressions on harmful edits |
| Manipulation | Mean/p95/max score inflation for post-parser and raw-snapshot edits; report sample sizes and uncertainty |
| Practical operation | Latency, throughput, peak memory, teacher/training cost, input coverage and failure rates |

Reproduce historical LR stress inputs where available; apply the same edits to both
models and add semantic counterexamples from phase 1. Include raw title/URL edits,
query repetition, duplicate headings, padding, misleading claims, and changed numbers.
Compare original/edit score deltas under fixed context. Stratify by query intent,
page role, source format, and length; small strata are diagnostic, not confident claims.

The existing 947-row test has already been inspected historically. Evaluate a frozen
student once for comparability and explicitly label it a reused benchmark. Do not
retune against those outcomes. Fresh hosts require a separately acquired offline
snapshot/label dataset; resplitting already-inspected hosts is not fresh confirmation.
If unavailable, report that limit and defer the independent claim.

Deliverables: paired LR/student report in Markdown and HTML, manipulation examples,
prediction manifest, component errors, and a promote/retain/revise recommendation.

Gate: promotion criteria must include edit behavior and grounding, with numerical
thresholds frozen during development. An AUC gain cannot override unsupported-claim
failures. Do not change defaults automatically after benchmarking.

## Phase 4 — Qualitative end-to-end dogfood in the demo webapp

The webapp is not present in this branch at plan creation. Locate its owner, branch,
scorer interface, and existing generation flow before implementation; do not modify
another worktree. Integrate through a separate reviewed change using its established
UI and backend conventions.

Use 10–20 curated scenarios covering factual lookup, comparison, how-to, long pages,
tables, and insufficient evidence. Keep any scoring evaluation scenarios separate
from rubric/training examples; label this small exercise qualitative dogfood.

For each scenario:

1. Load a local snapshot, target query, and supplied evidence pack.
2. Show original LR/student predictions and applicable components with limitations.
3. Identify a concrete missing requirement or title/body mismatch and generate a
   bounded set of source-grounded candidate edits through the demo's existing P2 flow.
4. Reject unsupported candidates or flag unassessable claims for review; rank the
   remaining candidates with the frozen development policy.
5. Show before/after content, component changes, evidence pointers, and unchanged
   context. Preserve provenance in downloadable/session artifacts.
6. Review usefulness, factual fidelity, readability, excessive edits, misleading
   feedback, response time, and whether a score gain corresponds to a better page.
   Record cases where LR and student disagree, including student failures.

Deliverables: inspectable session captures, a small reviewed case report, failure
inventory, and next-step recommendation. No live webpage extraction, publishing,
prospective citation measurement, or RL training is required for this phase.

Gate: reviewers can trace suggestions to evidence and understand score limitations;
the flow produces useful edits without hiding grounding or coverage failures.

## Decisions to resolve during implementation

- Teacher reliability and any comparison-model choice after reviewing the approved
  GPT-5 smoke; expansion budget and data-handling constraints before bulk annotation.
- Approved factual-material scope versus original-page fidelity.
- Backend/hardware and long-document policy after token profiling.
- Numerical rubric reliability, reward robustness, and promotion thresholds before
  bulk annotation or model selection.
- Frozen v5 artifact availability, independent-host dataset availability, and the
  actual demo integration location.

Preserve frozen analysis and prior scorer artifacts throughout. Report partial-run
limitations explicitly. Broad model quality, human certification, and causal citation
uplift are not outcomes this plan can establish.
