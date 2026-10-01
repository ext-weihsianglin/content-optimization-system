# Encoder scorer experiments

Phase 1 offline preparation is implemented. **Teacher selection is reserved for
the user; no teacher model has been selected and no API calls have been made.**
Student training and later benchmarking/dogfood have not started.

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

Model/provider adapters, usage/cost ledgers, response persistence, reviewer adjudication, and
human review remain to be implemented after the user chooses the teacher setup.
No API/model defaults are embedded in this package.

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
uv run python -m pytest tests/test_teacher_curation.py -q
```

Tests cover label-blind deterministic curation, split isolation, query-first input
separation, atomic nested structures, invalid evidence and requirement references,
numeric score validation, and abstention for omitted content/missing evidence packs.
