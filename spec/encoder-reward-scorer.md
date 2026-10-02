# Encoder P1 scorer and component rewards for P2

Status: implementation authorized; the user approved GPT-5 at medium reasoning
for the 12-case teacher smoke on 2026-10-01. Implementation sequence and gates:
[delivery plan](encoder-reward-scorer-plan.md).

## Objective and scope

Develop a query-conditioned P1 scorer that combines a learned citation-label
prediction with interpretable content-quality components to guide P2 page edits.
First curate evidence-backed annotations from stronger teacher models; then distill
those judgments into a ModernBERT-style encoder; benchmark against frozen LR
scorers; finally inspect end-to-end behavior in the demo webapp.

The initial P2 use case is improving an existing page using supplied factual
material. New-page generation can follow using an explicit evidence pack. This
implementation keeps teacher-model choice with the user before any teacher calls.
It does not change inference defaults automatically.

The citation target remains top versus bottom within a hostname among already-cited
pages. It is not cited versus uncited, absolute citation probability, or causal
editing uplift. Quality components are separately supervised hypotheses about
useful content; their relationship to citation performance must be measured.

## Evidence motivating the design

Committed baseline: [LR v4 report](../trad_ml_scorer/v4/report.md). V2 is the
repository inference default. V4's historical test AUC is 0.67904 versus 0.67689
for v2; the paired improvement is small and uncertain. Duplicate-heading stress
demonstrates that prediction quality and editing-reward behavior need separate
evaluation.

Additional evidence was read from `trad_ml_scorer/v6/report.html`, `audit.json`,
`coefficients.json`, and `selection.json` in the user-designated local worktree
`deck-prototype-trad-ml-scorers`. On inspection, its HEAD was
`f7465ad3fdc0e669dd76597b78800087fc964c33`, but v5/v6 artifacts were **uncommitted**.
The following is a reviewable summary of that local evidence, not a committed v6
release or a reproducible artifact bundle. Benchmarking those versions requires
a separately frozen artifact inventory and implementation provenance.

V6 retained v5: all new candidates failed one or more predeclared development
gates. Retained validation AUC: 0.67435; historical v5 test AUC: 0.68088 on 947
rows / 97 hosts. No new test evaluation was performed in v6.

Retained-baseline validation permutation results:

| Feature | Mean AUC drop on shuffle |
| --- | ---: |
| path_query_precision | 0.01634 |
| path_homepage | 0.01045 |
| log_heading_count | 0.00986 |
| mean_section_coverage | 0.00908 |
| log_list_items | 0.00845 |
| prompt_comparison | 0.00706 |
| format_html | 0.00706 |
| unique_word_fraction | 0.00622 |

Joint family drops: lexical 0.07323, URL 0.02065, content size 0.01951,
section alignment 0.01850, prompt 0.01802, composition 0.01339, answer 0.00616.
These quantities are not additive, causal effects, or certainty-ranked editing
recommendations. Correlation and shuffle-created implausible inputs limit them.
In particular, unique-word fraction has a negative fitted coefficient; it does not
justify a vocabulary-diversity reward.

Lexical corroboration reduced mean title-edit inflation from +0.2300 to +0.1418
and URL-edit inflation from +0.0661 to +0.0185 on 20 validation HTML snapshots.
However, repeated-query-prose p95 inflation on the separate 120-document
post-parser audit rose from +0.0657 to +0.1120. This motivates distinguishing
topic mention, actual answer delivery, and evidence-supported answer delivery.
The sampled stress outcomes do not establish comprehensive robustness.

## Component definitions

| Component | Teacher annotation target | Motivation |
| --- | --- | --- |
| Intent fulfillment | Query task, explicit constraints, and defensible implied requirements; answered/partial/missing/contradicted per requirement | Query type and lexical alignment |
| Title/body consistency | Specific title promises and whether body passages fulfill each promise | Metadata sensitivity and failed lexical corroboration |
| Section usefulness | New answer, evidence, prerequisite context, repetition, or unrelated material; heading/body agreement | Heading count and section alignment |
| Decision/procedure completeness | Comparison criteria, tradeoffs, conditional recommendations; or prerequisites, actions, and outcomes | Comparison queries, lists, and table alignment |
| Passage self-sufficiency | Entities, conditions, units, qualifications, and necessary context within an answer passage | Hypothesis beyond lexical sentence/window coverage |
| Evidence support | Supported, unsupported, contradicted, or unassessable claims relative to supplied evidence | Prevent fabricated prose from becoming corroboration |

Prioritize intent fulfillment, title/body consistency, and section usefulness in
the first pilot, with evidence support as a separate check. Other components enter
after rubric review. Use explicit not-applicable states: a factual lookup should
not be penalized for lacking comparison criteria or procedural steps.

Page role and query intent may condition evaluation. Homepage status, URL patterns,
HTML format, raw counts, and query type must not directly become P2 editing targets.
Reward distinct useful content rather than more sections, lists, or keywords.

Support against an original snapshot means fidelity to that snapshot, not verified
real-world truth. Record whether evidence is an original page or separately approved
material. An external link's existence does not prove the linked claim; preprocessing
and evidence extraction remain offline and snapshot-only.

## Teacher dataset contract

Reuse cached retention documents, source hashes, eligibility rules, record IDs,
and frozen hostname assignments. Preserve quality flags and raw-source traceability.
Do not rerun extraction, alter frozen documents, or silently substitute clean views.

Derive requirements from the query before reading the page. Distinguish explicit
constraints from inferred requirements and record ambiguity. Evaluate body quality
without citation labels, LR predictions, or hostname identity; inspect titles in a
separate consistency pass. Keep URLs as provenance outside the body judge input.

Each annotation record must contain:

- Versioned schema/rubric, record and snapshot IDs, split, payload/document hashes.
- Teacher identity/version, prompt version/hash, decoding settings, input-view hash,
  evidence-pack identity, token coverage and omitted block IDs, and execution status.
- Query requirements and task type; component ordinal scores with rubric anchors
  (0 absent/failed, 1 weak, 2 adequate, 3 strong), plus not-applicable/unassessable.
- Per-requirement states, claim support states, exact evidence spans and block IDs,
  concise justifications, uncertainty, and missing information.
- Reviewer/disagreement/adjudication status; estimated and actual annotation cost.

Keep page-present evidence distinct from independently supplied evidence. Check
span existence and ID validity mechanically. Untrusted source instructions must not
change annotation rules. Failed, incomplete, or truncated calls remain explicit.
Teacher self-confidence alone does not determine label reliability.

The runtime provider contract `teacher-selection-v1` uses fixed required slots
for frozen requirement assessments and packet-specific enums for evidence IDs.
GPT-5 selects IDs; backend code copies the complete selected block's exact input
text into canonical `{block_id, quote}` evidence. This deliberately uses whole-block
evidence, not model-transcribed substrings. Candidate and support-pack choices
remain separate. Partial body/title views exclude globally missing/unfulfilled
states in the provider schema, while canonical local validation remains active.
Unknown IDs, conflicting duplicate keys and oversized schemas fail visibly before
acceptance; no guessed IDs, quote normalization or permissive schema fallback.
Runtime requirements instructions evaluate static pages rather than requiring
conversational follow-up. Saved packets, the original rubric and historical smoke
are preserved; run manifests record the changed prompt/code hashes and contract.
Mechanical validity does not establish that selected evidence supports the judgment.

Use a second independent teacher or reviewer on a stratified subset and disagreements.
Human review establishes a limited reviewed subset, not human gold for the whole
dataset. No top/bottom labels or inspected test outcomes may influence the quality
rubric. Teacher-generated quality labels must not replace original citation labels.

## Student scorer contract

Proposed backbone: pinned `answerdotai/ModernBERT-base` (149M parameters, native
8,192-token context; [official model card](https://huggingface.co/answerdotai/ModernBERT-base)).
The exact revision, tokenizer, dependencies, hardware/backend, and training recipe
must be frozen for each experiment. Backend compatibility and cost require a bounded
smoke test; full-context training is not assumed to fit the local machine.

Jointly encode query, title, and structured content for a citation-label head.
Distill teacher component labels through separate supervised heads, masking missing,
unassessable, and not-applicable labels. Keep citation loss and component losses
separate and report their weights. Compare citation-only and multi-task training;
do not assume auxiliary labels improve citation AUC.

Section/passage components may use local encodings and page-level aggregation.
Do not copy a page's top/bottom label onto every chunk. Measure tokenizer lengths
first: existing 6,000-character chunks are not model token budgets. Preserve tables,
code, and nested lists where possible; oversized blocks need explicit handling and
coverage reporting. Version truncation/selection/aggregation policies. Ensure edited
candidate blocks are included consistently so selection does not hide or fabricate
score changes. Include a content/title-only baseline before metadata or LR hybrids.

Outputs include citation logit and sampled-label probability, applicable component
scores, uncertainty/coverage flags, and document/model provenance. Evidence pointers
must come from an explicitly evaluated extraction/selection mechanism; classification
heads alone do not provide faithful explanations. Teacher rationales are audit data,
not a claim that the student reproduces reasoning.

## P2 use and evaluation boundaries

Initially expose a component vector. Compare original and edited content with the
same query, evidence pack, fixed page context, and model/view versions. Unchanged
metadata should not dominate a content-edit reward. Significant unsupported or
contradicted claims reject a candidate; unassessable important claims trigger review.
Other component gains must not compensate for grounding failures.

Generate a bounded number of revisions, score them, and inspect the selected result.
No reinforcement-learning implementation is proposed for the first iteration.
Any eventual scalar weights or stopping thresholds must be selected on development
edit preferences and frozen before evaluation. Model agreement is not independence.

Evaluate citation discrimination/calibration, component agreement, edit preference,
manipulation sensitivity, and practical cost separately. Historical test results are
reused evidence. Fresh-host confirmation, human review, and prospective citation
uplift remain separate rollout gates.
