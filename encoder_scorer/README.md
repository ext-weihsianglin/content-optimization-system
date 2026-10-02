# Encoder scorer experiments

Two independent workstreams now guide delivery: **ModernBERT citation prediction**
trained on original labels and benchmarked against LR, and **LLM judge quality
scores** refined and integrated alongside P1 during webapp analyze. See the revised
[specification](../spec/encoder-reward-scorer.md) and
[plan](../spec/encoder-reward-scorer-plan.md). Judge distillation is an optional
later efficiency experiment; it does not gate the binary classifier. Current code
and evidence below implement the judge preparation/smoke harness, not a trained
ModernBERT classifier or a shipped webapp judge.

This session focuses on the LLM judge. ModernBERT classifier implementation is
tracked separately in [issue #18](https://github.com/ext-weihsianglin/content-optimization-system/issues/18).

The runtime `teacher-selection-v1` harness is now implemented in `selection.py`.
Provider schemas constrain evidence IDs and use required keyed assessments for
frozen requirements. Backend code copies complete selected source blocks exactly
into canonical evidence; raw model selections are saved separately in traces.
Partial views exclude globally missing/unfulfilled states. Canonical validation
still checks score applicability, evidence presence and section membership.
The changed contract completed a fresh smoke on the same saved Markdownify packets:
**12/12 accepted body stages, 36/36 first-pass valid calls, zero retries, $1.50422125
estimated cost**, using approved GPT-5 medium. Review the
[new plain-language report](../analysis/teacher-markdownify-gpt5-selection-smoke-v1-eli5.html)
and [comparison findings](../analysis/teacher-markdownify-gpt5-selection-smoke-v1.md).
The run is `gpt5-smoke-selection-v1/` under the ready package root below.
Historical results below remain frozen. No human review, training or expansion.

The original GPT-5 medium smoke on the markdownify packages is complete: 12 valid
requirements/title stages each and 9 valid body stages. Three body failures remain
unlabeled after bounded repair. Review [latest judgments](../analysis/teacher-markdownify-gpt5-smoke-v1.html)
and [findings/costs](../analysis/teacher-markdownify-gpt5-smoke-v1.md). The
[plain-language review](../analysis/teacher-markdownify-gpt5-smoke-v1-eli5.html)
explains the scores and failures with all 12 cases, exact evidence, and trace links.
It is a separate presentation of the frozen results; no labels were changed. No human review,
student training or bulk expansion. Factual support lacks separate evidence packs.

The [historical GPT-5 report](../analysis/teacher-gpt5-smoke-v1.html) used older LR v2
source documents; its labels were not transferred or reused. GPT-5.6 Luna/Sol were
unavailable to the API key when teacher choice was discussed; the user approved GPT-5.

**Current source of truth:** the completed shared markdownify corpus. Recreated
packages are ready at
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/encoder-scorer/teacher-markdownify-v2-ready/`.
See the [preparation report](../analysis/teacher-markdownify-packages-v2.html).
They contain 120 pilot packets, 12 smoke packets (6 full / 6 partial), and 18 blinded
edit pairs. New smoke traces/labels are under `gpt5-smoke-v1/` in this root.
No historical labels have been transferred.
The [source audit](../analysis/teacher-source-markdownify-audit-v1.json) describes the
historical mismatch; old packets, labels, and reports remain separate.

Specification: [component scorer](../spec/encoder-reward-scorer.md).
Sequence: [delivery plan](../spec/encoder-reward-scorer-plan.md).
Rubric: [development v1](../evaluation/teacher/rubric.md).

## Offline curation and packet preparation

Use saved markdownify documents; never rerun extraction to build teacher inputs.
`repackage` preserves the frozen 120 pilot record IDs, host splits and queues. LR v2
records supply only verified row/split references, never page content. The joins
verify raw-file hash/source row, snapshot, payload hash, hostname, URL and prompt.
Document/index checksums and extraction run identity are checked before preparation.
No test document is opened. All output directories must be new.

```sh
SCORER_CORPUS=/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/markdownify-corpus-v1-complete
SCORER_RUN=/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/encoder-scorer/teacher-markdownify-new
uv run --offline python -m encoder_scorer.repackage \
  --reference data/encoder_scorer/teacher-v1/curation/manifest.json \
  --split-source ../../data/trad_ml_scorer/v2 \
  --corpus "$SCORER_CORPUS" --output "$SCORER_RUN/curation"
uv run --offline python -m encoder_scorer.packets \
  --manifest "$SCORER_RUN/curation/manifest.json" --source "$SCORER_CORPUS" \
  --output "$SCORER_RUN/pilot-packets"
uv run --offline python -m encoder_scorer.packets \
  --manifest "$SCORER_RUN/curation/manifest.json" --source "$SCORER_CORPUS" \
  --output "$SCORER_RUN/smoke-packets" --smoke-only
uv run --offline python -m encoder_scorer.edits \
  --packets "$SCORER_RUN/smoke-packets/packets.jsonl" --output "$SCORER_RUN/edit-pairs"
```

In this worktree use `../../.tools/uv` if `uv` is absent from PATH. A different
machine needs an artifact transfer. Persistent source packages stay outside Git.
The earlier curation command/report reproduces historical LR v2 preparation only;
it is not the source for future annotation.

Recipe `teacher-blocks-markdownify-v2` sends saved `inline_markdown` as block `text`
for content-bearing v3 HTML blocks. Code keeps exact text whitespace; tables retain
structured cells, headers and spans; empty containers keep their child relationships.
Native formats keep their saved native block text. The packet is a block-addressable
Markdown view, not a byte-identical copy of the whole convenience `document.markdown`.
Evidence quotes must match the exact representation sent to the teacher. Source
quality status/flags stay attached. Embedded source links/images can remain; explicit
provenance and browser title are withheld from body assessment.

Whole block trees remain atomic under the 60,000-character bound. Every omitted
block ID is recorded; no block is shortened. This is not a token budget. Six new
smoke views are partial because inline Markdown increases the serialized size.
Tokenizer budgeting occurs in the approved adapter before paid generation.

## Annotation stages and validation

`contracts.py` defines strict provider-neutral JSON schemas for four passes:

1. Query-only requirements (no page content).
2. Body intent fulfillment and section usefulness, using frozen requirements.
3. Title/body consistency, receiving title in a separate pass.
4. Evidence support, receiving a separately identified evidence pack.

`packets.request()` builds a body request only after query requirements exist.
`contracts.validate_response()` checks structure, applicability/score consistency,
exact quote spans, requirement coverage, section references, and missing-input
abstention. Mechanical validity cannot certify semantic correctness. Grounding is
unassessable when no evidence pack exists; an original-page pack certifies fidelity
only. Pilot evidence packs have not yet been curated.

Schema snapshots are in `evaluation/teacher/schemas/`. Eighteen blinded edit pairs
from three full-body training cases are prepared, with mutation intent stored in a
separate provenance file. These controls are not reviewed preferences or quality
labels. Prose removal and moving a source passage first may or may not harm/improve
an answer; a reviewer must judge them. Original-page packs check fidelity only.

The OpenAI adapter saves requests, visible responses, usage, latency, validation,
and at most one repair per stage. Teacher model selection is an explicit CLI argument.
Reviewer adjudication and human review remain pending. No student training is enabled.

## Run the approved teacher smoke

```sh
uv run python -m encoder_scorer.annotate \
  --packets "$SCORER_RUN/smoke-packets" \
  --output "$SCORER_RUN/gpt5-smoke-new" \
  --model gpt-5 --effort medium --budget-usd 10
uv run python -m encoder_scorer.annotation_report \
  --run "$SCORER_RUN/gpt5-smoke-new" \
  --packets "$SCORER_RUN/smoke-packets" \
  --output analysis/teacher-gpt5-smoke-new
```

Requires `OPENAI_API_KEY`; credentials and source-bearing call traces remain local.
Requests use strict JSON schemas, `store: false`, no tools, and explicit output caps.
The token-count endpoint counts actual input/instructions; a conservative schema
and overhead allowance is added to the pre-call reservation. No content is truncated
to fit. Usage-based costs use standard uncached input/output rates, including billed
reasoning output tokens; they are conservative estimates, not billing invoices.

Three model passes run per case: requirements, body, and title. Evidence support
abstains deterministically because these packets contain no separate evidence pack;
it must not be presented as a teacher grounding judgment. Returned snapshot identities
are saved, alongside the requested alias. No cross-model or human reliability claim
is made by a single-teacher smoke run.

The adapter rejects historical plain-block packets; use the new markdownify package.
The [demo harness review](../analysis/teacher-harness-demo-webapp-review.md) informed
the new fixed requirement slots and backend-resolved evidence. Historical smoke
results use the original schemas; new run manifests name the selection contract.
Use `--stop-after 1` to inspect the first case without changing the frozen 12-case
plan, then rerun the identical command with `--resume` and no stop flag. Completed
valid responses are reused. Ambiguous transport failures are retained for inspection.
The default does not retry them; `--allow-transport-retry` permits one bounded retry,
retaining the unknown call's full cost reservation. `--concurrency 2` processes two
cases at a time with atomic shared budget reservations. A code revision can reuse validated calls via
`--seed-from` with identical inputs/model/rubric/settings, recording parent manifest
and trace hashes. The first actual run was carried into `gpt5-smoke-v2` after a
tuple/list configuration-serialization fix; its initial three calls were reused.
The final run uses `gpt5-smoke-v3`, seeded from v2 after its title call timed out;
the recorded timeout was retried once, and five valid calls were reused. Both earlier
run directories and code snapshots remain local for provenance.

## Demo integration inventory

The adjacent `profound/demo-webapp` repository contains Content Studio, with
Next.js and FastAPI. Its inspected README describes mock query/clarity grades and
deterministic title edits; `/api/analyze` and `/api/draft` are the integration seams
in `backend/app/main.py`. Actual workstream branches may be ahead of this checkout.
No files in that repository or its worktrees were modified. Recheck its owner/branch
and contracts before phase 4; persistent durable source IDs and optimizer grounding
must survive integration.

## Verification

```sh
uv run python -m pytest tests/test_teacher_curation.py tests/test_teacher_annotation.py tests/test_teacher_markdownify.py -q
```

Tests cover label-blind deterministic curation, split isolation, query-first input
separation, atomic nested structures, invalid evidence and requirement references,
numeric score validation, and abstention for omitted content/missing evidence packs.
Provider tests cover exact resume and migration, bounded repairs/retries, incomplete
responses, durable cost accounting, and concurrent spend-cap enforcement.
