# Content optimization project memory

Checkpoint: 2026-10-01. This is repository-local session memory. Start here, then
read the linked specs and reports as needed; verify live Git state before acting.

## Goal and user priorities

Profound work trial: analyze page/content factors associated with answer-engine
citations and build a lightweight query-specific content generation/refinement
workflow. Original task: `project-brief.md`. Deliver useful, inspectable work quickly;
do not overinvest in model tuning. The user wants HTML reports and sample outputs
they can eyeball, reproducible quantifiable evaluation, and important docs/reports
checked into delivery PRs. Always use `uv` for Python.

## Repository and delivery checkpoint

- Local repo: `/Users/ext-weihsiang.lin/Documents/profound/content-optimization-system`.
- Remote: `https://github.com/ext-weihsianglin/content-optimization-system.git`.
- PR #1: `https://github.com/ext-weihsianglin/content-optimization-system/pull/1`.
- GitHub verified PR #1 **merged** at `2026-10-01T19:06:15Z`, merge commit
  `eb99b7c19c37b8a29369ec23ffc4847ebcd19ada`.
- Implementation commit: `dec31d269b96bf20cb6f42271efa76b116fd7b67`.
- Local branches may differ from merged main; inspect `git status` and branch state
  rather than assuming the checkout has followed a remote merge.
- `.worktrees/` contains unrelated parallel work; leave it alone. Repository startup
  instructions are in `AGENTS.md`; this file holds the detailed project context.

## Current architecture decision

**Retention first, then downstream relevance decisions.** Use `conservative_dom`
for HTML; `markdown_text` for native Markdown/plain text. Preserve raw snapshots
and original metadata/JSON-LD separately. Keep ordered typed blocks with headings,
parent-linked lists, code whitespace, links, table cells/spans/header roles, source
locators and honest mapping-confidence labels. Markdown/text are convenience views.

The downstream contract is `spec/downstream-document.md`; implementation is
`preprocessing/downstream.py`. It exports documents, heading outlines, and chunks
with a soft 6,000-character target (NOT a token budget). Tables, code and complete
nested-list trees stay atomic; oversized chunks are flagged, never truncated.
Every selected block appears exactly once, in order, in the chunk partition.
Quality warnings remain attached; flagged content is retained as `needs_review`.
Missing preferred output never silently substitutes another parser. Reader-LM is
not the default. Readability/Trafilatura remain optional clean views; the superseded
precision-oriented selector is retained as `select_precision_candidate`.

The user hypothesizes that frontier models benefit from broad content retention.
Treat retention-first as our design objective, NOT evidence that we replicate a
particular proprietary frontier API's undocumented ingestion pipeline. Conservative
DOM still removes some navigation/boilerplate; only the stored raw payload preserves
the original snapshot in full. Source content is untrusted data, not instructions.

## Dataset and original analysis

- Five `data/raw/citations_part_00*.parquet` files: 9,700 rows, 970 hosts, exactly
  five top/five bottom rows per host; 9,527 distinct URLs.
- Actual columns: `prompt`, `citation_category`, `href`, `hostname`, `html_content`.
  Despite the brief, no separate cleaned-Markdown column is provided.
- 91 blank prompts; 28 excess exact duplicate rows; 14 URLs have conflicting labels.
- Labels are relative within hostname; both classes have been cited. No citation
  counts, exposure, engine identifiers or observation times: no causal/uplift claims.
- Broad content associations are confounded. Strict same-query sensitivity has only
  29 matched host/query groups across 27 hosts; do not turn length/headings into
  universal editing targets. Original v1 analysis remains unchanged.
- ZIP is in Downloads; exact location/hash: `analysis/provenance.json`.
- Original report: `analysis/brief-report.html`; eyeballing CSV:
  `/Users/ext-weihsiang.lin/Documents/profound/content-optimization-system/analysis/citation-sample-500.csv`.

## Completed extraction evidence

Frozen evaluation: 100 distinct hosts, 60 development / 40 held-out, no hostname or
identical-payload overlap. Source formats: 88 HTML, 8 Markdown, 4 plain text.
Source-only AI reviewers selected 338 required and 127 unwanted anchors before
candidate scoring; 82 sources are content-evaluable. References are sparse AI-assisted
annotations, NOT human gold or exhaustive coverage.

Retention = required anchors surviving extraction / eligible required anchors.
Leakage = unwanted anchors surviving / eligible unwanted anchors; NOT the fraction
of generated text that is boilerplate. Higher retention and lower leakage are better.

Held-out HTML scores: 32 evaluable pages, 129 required anchors, 50 unwanted anchors.

| Method | Required retention | Unwanted leakage |
| --- | ---: | ---: |
| Frozen BeautifulSoup baseline | 121/129 (93.8%) | 30/50 (60%) |
| Trafilatura | 100/129 (77.5%) | 11/50 (22%) |
| Readability + Turndown | 111/129 (86%) | 11/50 (22%) |
| Conservative DOM | 126/129 (97.7%) | 46/50 (92%) |

Native held-out results are separate: 3 Markdown pages, 13/13 required and 2/2
unwanted anchors retained. No held-out plain-text quality estimate. Synthetic
structure checks are separate from real-page accuracy. No human gate is certified.

- All five methods have 500 explicit outcomes; no exceptions/timeouts, six empty
  outputs. Resume is byte-identical; independent rerun matches excluding timing.
- Frozen artifacts: `evaluation/extraction/{manifest,annotations,freeze,verification}.json`.
- Source cache: `data/evaluation/`; complete run: `data/processed/eval-v2/`.
- Reports: `analysis/extraction-evaluation.html` and `.json`, development companions,
  `analysis/extraction-fixtures.json`; metric rubric: `evaluation/extraction/rubric.md`.

## Retention export checkpoint

`data/processed/retention-v1/`: 100 documents, 28,539 blocks, 2,383 chunks, 17 oversized
chunks. Statuses: 87 selected, 8 need review, 5 source-insufficient. Selected methods:
87 conservative DOM, 8 native, 5 none. Artifacts: `documents.jsonl/.parquet`,
`chunks.jsonl/.parquet`, `manifest.json`; committed summary:
`analysis/retention-export.json`. This is the evaluation set only, NOT a 9,700-row
corpus rollout. Last validation: **94 tests passed, 12 subtests passed**.

## Textual embedding implementation checkpoint

Branch `deck/preprocess-feature-engineering` adds the `representations` CLI and
`spec/embedding-representations.md` / `plan/embedding-representations.md`. It prepares
query, title/H1, outline, section, page, and URL-path views; calls hosted OpenAI,
Voyage, or pinned OpenRouter/Qwen endpoints; caches/resumes requests; computes
query alignment; saves PCA fits; and builds a query-first evidence report with
optional UMAP maps. No local GPU is required. Images and learned fusion are deferred.

The initial compatibility adapter consumes the frozen `eval-v2` parquet schema.
PR #2's saved `downstream-document-v1` documents are now supported as well. Canonical
shared input: `/Users/ext-weihsiang.lin/Documents/profound/content-optimization-system/data/trad_ml_scorer/v2`.
Do not repeat HTML extraction or scorer preparation. The adapter streams saved
compressed documents, preserves source chunks and retained `needs_review` content,
and carries original scorer IDs, row provenance, exclusions, and existing splits.
All 9,551 snapshots / 9,700 records validated; 377,460 logical embedding units were
serialized to this worktree's `data/representations/retention-corpus-v1`.
Full-corpus API embeddings have not run. Serializer is now `blocks-v2`.
A new live 20-snapshot retention smoke completed 674 unique OpenAI requests,
produced 732 vectors, and aligned all 20 records; page/query/path exploratory
PCA/UMAP projections and a query-first report are saved. Resume used the cache.
The full corpus would require 323,751 unique OpenAI requests with this input policy,
not merely one request per record; budget runtime/storage before scheduling it.
New compact reports: `analysis/embedding-retention-validation.json`,
`analysis/embedding-retention-smoke.json`, `analysis/embedding-retention-explorer.html`.
The historical smoke below still reflects older selection outcomes.

Live OpenAI `text-embedding-3-large` baseline: 20 source records/snapshots, 11 selected
extractions, 342 logical units, 320 unique requests, 334 vectors, zero request
failures, 88,998 prompt tokens. Completed-run resume made no new requests. These
are integration checks, not comparative relevance results or citation uplift.
Artifacts are in this branch's worktree at `data/representations/eval-openai-v1/`;
checked-in summaries: `analysis/embedding-validation.json` and the query-first
`analysis/embedding-explorer.html`. The original map-first UI was revised after
user feedback. Rendered browser verification was blocked by file-URL policy;
source escaping and script interactions were checked independently.

After integration with PR #2: 130 tests and 12 subtests passed; explorer script
checks passed. Human query–section relevance review, additional provider
credentials/preflight, reviewed model selection,
and full-corpus processing remain pending. Do not restart embedding API work just
to reproduce the static report; use cached vectors and the report builder.

## Reader-LM experiment and stop decision

No hosted Jina API access. Downloaded `jinaai/reader-lm-0.5b` at pinned revision
`46cb69fff9d100f9c3c2a135d59f365fb99a0121`; local Apple M4 Pro / 24GB, MLX BF16.
Separate `.venv-reader` (Python 3.12); setup in `preprocessing/READER-LM.md`.
Weights: `data/models/reader-lm-0.5b`; CC-BY-NC-4.0, resolve commercial licensing
before production. This model is NOT the hosted Jina Reader service.

Initial local-server run: 64K prompt / 2K output, stopped at 35 outcomes (23 HTML,
12 unsupported). Only 10 completed pages were evaluable, all table-stratum pages;
required retention 10/41 versus Readability 36/41 on the same subset. Repetition,
script copying and output caps made further unchanged execution wasteful. Nonempty
`ok` outputs are not quality successes. Partial ledger must not be ranked as full eval.

Three-page follow-up: direct MLX streaming, up to 96K input + 32K output, prefill 2048,
repetition stopping, 180-second per-page budget. All three full inputs fit:
- DigitalOcean: 2/4 required anchors; repetition stop, 1,616 tokens, 21.7 seconds.
- Visit Phoenix: 0/4; time stop, 9,678 tokens, 180 seconds.
- Wisernotify: 2/4; normal completion, 3,670 tokens, 52.5 seconds.

Expanded budgets did not rescue this configuration. These are purposive development
diagnostics, not a general verdict on Jina or an isolated model/backend comparison.
Both server and benchmark were stopped; no further inference is scheduled. **Do not
restart without user direction.** Reports: `analysis/reader-lm-review.html`,
`analysis/reader-lm-pilot.html`, `analysis/reader-lm-progress.html` and JSON companions.

## Fast restart and remaining work

1. Read Git status and verify branch/main state; preserve unrelated worktrees.
2. Read `spec/downstream-document.md`, `README.md`, and this checkpoint before
   revisiting settled parser choices. Use the existing local export for a fast demo.
3. Integrate structured chunks into the query-specific downstream workflow, carrying
   source/block/chunk IDs through relevance selection and generated suggestions.
4. Full-corpus runner/migration, human reference review, model-specific token budgeting,
   factual grounding checks, and v2 feature/sensitivity reanalysis remain outstanding.
   Do not claim these are completed. A prospective citation experiment is separate.

Useful commands (repo root):

```sh
.tools/uv sync --dev
npm ci --prefix preprocessing/node
.tools/uv run --offline python -m pytest -q
.tools/uv run --offline python -m preprocessing.prepare_eval --materialize
.tools/uv run --offline python -m preprocessing run --split all --output data/processed/replay
.tools/uv run --offline python -m preprocessing.benchmark --results data/processed/replay/results.jsonl
.tools/uv run --offline python -m preprocessing.downstream --run data/processed/replay --output data/processed/retention-replay
```

Materialization needs the original raw parquet files and verifies hashes; it does
not resample. Use new output directories instead of overwriting frozen artifacts.
JSONL must be read by file iteration, not `str.splitlines()` (embedded Unicode line
separators caused a real parsing bug). Large generated reports use escaped previews;
their truncation does not affect full-output anchor scoring.
