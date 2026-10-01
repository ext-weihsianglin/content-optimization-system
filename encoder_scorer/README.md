# Encoder scorer experiments

Phase 1 offline preparation is implemented. The user approved **GPT-5 at medium
reasoning** for the 12-case smoke annotation. The run is complete: 12 requirements/title labels
each and 11 body labels passed validation; one body stage remains unavailable.
Review [actual judgments](../analysis/teacher-gpt5-smoke-v1.html) and
[findings/costs](../analysis/teacher-gpt5-smoke-v1.md). Student training and later
benchmarking/dogfood have not started. GPT-5.6 Luna/Sol model endpoints returned
404 with the available key; no model was substituted before user approval.

Specification: [component scorer](../spec/encoder-reward-scorer.md).
Sequence: [delivery plan](../spec/encoder-reward-scorer-plan.md).
Rubric: [development v1](../evaluation/teacher/rubric.md).

## Offline curation and packet preparation

Use an existing frozen LR v2 cache; do not prepare the corpus again. All scripts
below use the Python standard library. Raw/source packets stay under ignored `data/`.
Outputs refuse replacement; reruns must use new paths.

```sh
uv run --no-project python -m encoder_scorer.curate \
  --source ../../data/trad_ml_scorer/v2 \
  --output data/encoder_scorer/teacher-v1/curation
uv run --no-project python -m encoder_scorer.packets \
  --manifest data/encoder_scorer/teacher-v1/curation/manifest.json \
  --source ../../data/trad_ml_scorer/v2 \
  --output data/encoder_scorer/teacher-v1/smoke-packets --smoke-only
uv run --no-project python -m encoder_scorer.edits \
  --packets data/encoder_scorer/teacher-v1/smoke-packets/packets.jsonl \
  --output data/encoder_scorer/teacher-v1/edit-pairs
uv run --no-project python -m encoder_scorer.report \
  --curation data/encoder_scorer/teacher-v1/curation/manifest.json \
  --packets data/encoder_scorer/teacher-v1/smoke-packets \
  --edits data/encoder_scorer/teacher-v1/edit-pairs/manifest.json \
  --output analysis/teacher-curation-v1
```

Use the repository's `.tools/uv` if needed. In this worktree, the shared executable
is `../../.tools/uv`; `../../data/` is read only to these commands. No links or
environment modifications are needed. A different machine needs an artifact transfer.

The candidate pool contains at most one eligible record per development hostname,
prioritizing rare metadata strata before loading cached documents. Then a greedy
coverage policy selects 96 training and 24 validation cases. It never uses labels
to select or opens test documents. This deliberately varied pilot is not a random
sample, a human-reviewed dataset, or held-out evidence. Citation labels remain in
the original LR cache and may be joined for later training through frozen IDs.

Packets preserve complete top-level block trees within a character bound, retain
tables, and report every omitted block ID. This is a preparation guard, not a model
token budget. Adjust budgeting after the approved teacher tokenizer is known; freeze
a new packet version rather than replace the existing one. Source text can contain
brand names or embedded URLs; only explicit identity/provenance fields are withheld.

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
  --packets data/encoder_scorer/teacher-v1/smoke-packets \
  --output data/encoder_scorer/teacher-v1/gpt5-smoke-new \
  --model gpt-5 --effort medium --budget-usd 10
uv run python -m encoder_scorer.annotation_report \
  --run data/encoder_scorer/teacher-v1/gpt5-smoke-new \
  --packets data/encoder_scorer/teacher-v1/smoke-packets \
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
uv run python -m pytest tests/test_teacher_curation.py tests/test_teacher_annotation.py -q
```

Tests cover label-blind deterministic curation, split isolation, query-first input
separation, atomic nested structures, invalid evidence and requirement references,
numeric score validation, and abstention for omitted content/missing evidence packs.
Provider tests cover exact resume and migration, bounded repairs/retries, incomplete
responses, durable cost accounting, and concurrent spend-cap enforcement.
