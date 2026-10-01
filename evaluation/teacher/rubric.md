# Teacher annotation rubric v1 — development draft

This rubric has not passed teacher/human review. Do not expand annotation or train
against it until reviewed pilot outcomes meet frozen reliability gates.

## Query-first requirements

Derive a short checklist from the query alone. Mark each requirement explicit or
inferred and essential or optional. Do not invent prices, dates, audience, geography,
or a preferred answer. Broad "best" queries can require selection criteria and
tradeoffs, but do not imply that a particular product must win. Ambiguous questions
may be evaluated conditionally; preserve ambiguity instead of silently narrowing it.

## Shared scoring anchors

Scores concern the supplied retained-content view, not citation likelihood.

| State | Meaning |
| --- | --- |
| 0 | Applicable and assessable, but substantive fulfillment is absent or fails |
| 1 | Weak: mentions the topic or provides fragments with essential gaps |
| 2 | Adequate: fulfills the central task, with limited noncritical gaps |
| 3 | Strong: fulfills essential requirements with useful specificity and qualifications |
| null / not_applicable | Component does not apply to this task or input |
| null / unassessable | Missing evidence, ambiguous requirements, or omitted content prevents judgment |

Positive scores require exact, nonempty quotes and valid block IDs. A quote establishes
traceability, not correctness of the judgment. Assess each query requirement once.
When body blocks are omitted, an unseen answer may exist: use unassessable instead
of claiming globally missing content. Mentioning all query words is not answering.

## Intent fulfillment

Assess each essential requirement as answered, partial, missing, contradicted, or
unassessable. "Answered" requires substantive information relevant to the actual
question and constraints, not a heading or repeated phrase. A score of 3 requires
all assessable essential requirements to be addressed; optional extras cannot
compensate for an essential gap. Preserve uncertainty when the query is underspecified.

## Section usefulness

Identify distinct sections and the blocks they contain. Label their contributions:
answer, evidence, prerequisite context, repetition, unrelated, mixed, unassessable.
Useful background can support an answer without repeating query terms. Reward
organization that helps a reader find distinct useful information. Extra headings,
list items, and synonyms do not themselves improve the score. A single coherent
answer can score strongly without many sections. Exact or paraphrased repetitions
receive no additional informational credit. Heading/body mismatch counts against
usefulness when it makes the answer harder to locate.

## Title/body consistency

Extract specific promises from the title: topic, scope, audience, comparison,
procedure, claimed evidence, or time qualification. Locate the body information
that fulfills each promise. A title such as "Best shoes for marathon beginners"
is not fulfilled by a generic list of brands unless it addresses the audience and
choice criteria. Topic overlap alone is weak. Missing title is not_applicable;
partial input may make fulfillment unassessable. Do not require promotional claims.

## Evidence support

Assess important claims against a supplied evidence pack, identifying both the
page claim span and the supporting/contradicting evidence span. Evidence must match
entities, relations, amounts, units, conditions, and qualifications. A citation link,
authority badge, self-declared freshness, or repeated assertion does not prove a claim.
Without a supplied pack, mark support unassessable; do not equate no evidence with
falsehood. If the pack is an original page, assess fidelity only, not external truth.
Do not score the same assertion as its own independent support.

## Later components

Decision/procedure completeness and passage self-sufficiency are proposed extensions.
They have no numeric pilot labels yet. Review task-specific anchors before adding
heads or data: comparisons need meaningful criteria/tradeoffs, procedures need
prerequisites/actions/outcomes, and answer passages need entities/conditions/units.

## Calibration examples (synthetic, not dataset annotations)

- Query: "How to reset a router?" Body: "Router reset router reset." Topic mention
  earns no procedure fulfillment. It supplies no executable steps.
- Query: "Compare A and B for a small team." Body compares costs and administration
  with source-supported qualifications. This may fulfill the query without choosing
  a universal winner; judge the actual information, not the presence of a table.
- Title promises "2026 prices"; body provides no dated prices. On full body coverage,
  that promise is unfulfilled. On partial coverage it may be unassessable.
- Claim: "A costs $10 monthly." Evidence: "$10 per user monthly when billed annually."
  Omitting billing conditions is a fidelity gap even though number tokens match.
- A section explains a necessary definition. It can be useful prerequisite context
  even if lexical coverage is low. An appended repeated question adds no new answer.

## Pilot review and expansion gate

Before any bulk teacher expansion, freeze a revised rubric and numerical thresholds
using reviewed pilot cases. Proposed starting gates to review after the smoke test:
100% mechanically valid evidence pointers; at least 90% reviewed evidence spans
support the stated judgment; at least 80% double-reviewed component scores within
one ordinal point; no systematic preference for harmful edits over their originals.
Report denominators, uncertainty, disagreement by component, and abstention rates.
These proposed thresholds are not certified or sufficient to claim human gold.
