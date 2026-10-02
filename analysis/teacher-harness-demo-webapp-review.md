# Reusing the demo-webapp source-reference harness

Reviewed 2026-10-01 via authenticated GitHub PR/API reads. This records the original
design recommendation; implementation and run evidence are linked below.

Follow-up: the user subsequently authorized implementation and smoke rerun.
`encoder_scorer/selection.py` now implements `teacher-selection-v1` with keyed
requirements and exact backend whole-block evidence copying. The sections below
preserve the original source review/design rationale; new run reports record
actual execution and measured validity separately in the
[selection smoke findings](teacher-markdownify-gpt5-selection-smoke-v1.md).

## Finding

Yes: [demo-webapp PR #3](https://github.com/ext-weihsianglin/demo-webapp/pull/3)
contains the relevant hardening. The useful principle is **have the model select
source evidence; have the backend copy immutable source fields**. A second change
makes edit identity part of a page-specific schema rather than a freely generated
field. [PR #5](https://github.com/ext-weihsianglin/demo-webapp/pull/5) explicitly
preserves this keyed P2 contract while replacing the P1/parser foundation.

The reviewed implementation is pinned to PR #3 head
`cf84c336302f34cdd8688c1852f994ec87455b6e`, merged by
`1871d146d97e67df46c88f3f4db20baf5f7faf9e`. Immutable source links below use the
head revision, rather than today's mutable default branch.

## What the harness actually does

- **One required slot per editable block.** `response_schema` constructs
  `blocks: {"block-id": replacement-or-null, ...}` with an exact required key
  set and `additionalProperties: false`. The replacement object has no
  `block_id`; the parser gets identity from its key. Null preserves a block.
  This constrains missing/unknown targets and competing edits to one target.
  [Schema and parser](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/rewriting.py#L184-L252)
- **Constrain evidence selection.** Each chunk's schema uses an enum of its
  nonempty source block IDs for evidence references when the batch contains at
  most 900 block memberships. Above that threshold the enum restriction is
  omitted; backend validation still checks IDs and same-chunk membership.
  This implementation detail prevents claiming all possible evidence IDs are
  always constrained at generation time.
  [Evidence schema](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/rewriting.py#L195-L205)
- **Copy provenance and evidence in code.** The model returns replacement,
  rationale, flags, and evidence IDs. `assemble_proposal` resolves those IDs and
  copies original text, snapshot ID, chunk ID, and the complete evidence block's
  source text. The model does not transcribe these strings. This removes quote
  spelling, Markdown punctuation, and source-field transcription failures.
  [Assembler](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/rewriting.py#L76-L95),
  [versioned prompt](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/prompts/rewrite-page-v7.txt)
- **Do not silently choose a conflicting result.** The JSON parser normalizes
  identical duplicate keys once, rejects conflicting duplicates, verifies the
  exact editable key set, and rejects a second `block_id` inside an edit value.
  [Parser](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/rewriting.py#L222-L252),
  [regression tests](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/tests/test_keyed_proposal.py)
- **Bound requests and preserve visible failure.** Schemas exceeding 4,500
  estimated properties or 110,000 serialized characters fail before generation.
  The provider call requests strict structured output; refusal, incomplete
  output, invalid proposals, and API failures remain explicit outcomes. There
  is no repair call or fallback in this rewrite path.
  [Preflight](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/rewriting.py#L215-L219),
  [request and outcomes](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/app/rewriting.py#L342-L430)

The [final recorded matrix](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/verification/keyed-rewrite-final-matrix.json)
has eight successful runs: two saved pages across GPT-4.1 mini/nano and GPT-5
mini/nano, each with one provider call and exact-source/same-chunk checks. It is
explicitly exploratory, not a reserved P2 quality benchmark. The record supports
that this helped those runs; it does not establish a universal no-failure guarantee.
[Evidence assembly tests](https://github.com/ext-weihsianglin/demo-webapp/blob/cf84c336302f34cdd8688c1852f994ec87455b6e/backend/tests/test_evidence_assembly.py)
also check exact backend copying, unknown IDs, mismatched quotes, and cross-chunk
evidence failures. These were inspected, not rerun in this repository.

## Difference from our teacher harness

At research revision `8ed0118be12e436ac124713805c8963e5f5bb217`, our
[contracts](https://github.com/ext-weihsianglin/content-optimization-system/blob/8ed0118be12e436ac124713805c8963e5f5bb217/encoder_scorer/contracts.py)
ask the model for arbitrary-string `block_id` plus an exact substring `quote`.
Requirement IDs and section block IDs are also arbitrary strings in the static
provider schema. Local validation subsequently requires real IDs, exact quotes,
complete distinct requirements, and honest partial-document states.
[Packet requests](https://github.com/ext-weihsianglin/content-optimization-system/blob/8ed0118be12e436ac124713805c8963e5f5bb217/encoder_scorer/packets.py#L100-L112)
use those static schemas, and the
[annotation runner](https://github.com/ext-weihsianglin/content-optimization-system/blob/8ed0118be12e436ac124713805c8963e5f5bb217/encoder_scorer/annotate.py#L111-L122)
allows one repair with the previous output and validation error.

Our [Markdownify smoke report](teacher-markdownify-gpt5-smoke-v1.md) records quote
and block-reference failures and a separate partial-coverage failure. Selecting a
valid but irrelevant block would still be semantically wrong even when copying
its text makes provenance mechanically valid. Consequently, eliminating quote
transcription failures must not be reported as improved teacher accuracy.

## Proposed teacher adaptation

1. **Version a provider selection contract and retain canonical label output.**
   Keep completed smoke results frozen. Generate schemas per packet/stage with
   evidence IDs limited to available nonempty blocks. Resolve evidence into the
   existing `{block_id, quote}` label format deterministically. The simplest
   baseline copies the entire selected block, as the webapp does. Record this
   broader evidence granularity explicitly; do not silently repair a model's
   mismatched quote by finding a similar string elsewhere.
2. **Constrain assessment identity and scope.** Use required keyed assessments
   for frozen requirement IDs, and resolve those keys in code. Derive section
   units from saved packet structure, then expose their IDs as a bounded set;
   avoid requiring an assessment for every raw block. On partial packets, omit
   globally `missing`/`unfulfilled` states from the relevant provider enums and
   retain `unassessable`. This moves existing local constraints into generation
   without relaxing their meaning.
3. **If shorter evidence is needed, select deterministic span IDs.** Build an
   offline source-preserving span catalog with block ID and exact character
   offsets. The model selects an enum of span IDs; code slices the original
   packet text. Span rules must preserve Markdown/code/table fidelity and be
   versioned. This is an optional later refinement: inferred sentence splitting
   must not erase qualifiers or imply entailment.
4. **Keep budgets, diagnostics, and semantic validation.** Preflight schema and
   token limits, reject conflicting duplicate keys, and distinguish transport,
   schema, coverage, and evidence-selection outcomes. Candidate and separate
   support-pack evidence need distinct catalogs/enums. Positive ratings still
   require evidence, partial-view claims remain limited, and full copied text
   does not verify factual support or relevance. For the teacher, exceedance of
   an enum/schema budget should produce an explicit preflight outcome; do not
   copy the webapp's large-batch removal of evidence enums as a permissive
   fallback. Any bounded subdivision needs a new declared view and coverage
   identity rather than silent truncation.
5. **Re-run the same 12 smoke cases in a new versioned directory with approved
   GPT-5 before expanding.** First run offline regression checks against the
   recorded bad outputs. Then compare first-pass acceptance, repair calls,
   failure categories, tokens/cost, and human-reviewed evidence relevance under
   the changed contract. Preserve original outputs for comparison. No new model
   choice or full-corpus execution is implied by this proposal.

These changes target avoidable reference/schema failures. They cannot ensure
that every inference request completes, or that every selected passage supports
the model's judgment. Strict source validation and review remain necessary.
