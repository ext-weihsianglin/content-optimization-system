# Content optimization project memory

Checkpoint: 2026-10-01. This is repository-local session memory. Start here, then
read the linked specs and reports as needed; verify live Git state before acting.

## Goal and user priorities

Latest storage/execution decision (2026-10-01): all local project data now lives in
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system`.
The main checkout and this embedding worktree's `data` paths are compatibility
symlinks to that root. Existing persistent raw/processed outputs were preserved;
five duplicate raw parquet files were SHA-256 verified before deduplication.
Other directories moved on the same filesystem, preserving file inodes. Local
audit: `<persistent root>/storage-migration-2026-10-01.json`.
Set `CONTENT_OPTIMIZATION_DATA_ROOT` for an explicit alternate project volume;
`EMBEDDING_CACHE_ROOT` still overrides only the vector cache. Do not recreate
worktree-local data copies or redo preparation/inference.

The user explicitly stopped local Voyage MLX: its process exited and the catalog
marks the job interrupted, with 115,554 completed unique vectors retained. Do not
resume it without user direction. OpenAI is complete and is the current model for
downstream work. Older active-job statements below are historical.

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
Full-corpus OpenAI embeddings are now complete (see the later checkpoint). Serializer is `blocks-v2`.
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

## Shared embedding store and active full-corpus execution

User chose a shared durable cache instead of a vector DB, and limited execution to
OpenAI hosted text embeddings plus local Voyage nano/MLX. Qwen-8B and Voyage large
are deferred; large does not have published local weights. The nano checkpoint is
official, revision `67fabc9bef010dabc5f6024aa1b1b6b93410426f`, with a pinned community
MLX backend revision `5001811de8d5ab39bcdab1c9b40b925d8d7d3983` and BF16 compute.
MLX uses the Apple M4 Pro GPU through Metal, explicitly selected by the adapter.

Shared store: `<main checkout>/data/representations/shared-store`. Stable semantic
identities exclude batch/concurrency/timeout settings. SQLite provides lookup and
job history; immutable checksummed shards preserve completed batches. Model locks
prevent duplicate writers; fully cached readers can export concurrently. Legacy
paid vectors migrate without API calls. Recovery, portable backups, cache status,
input reuse and disk-backed exports are implemented. See `spec/embedding-storage.md`.
Do not rerun parsing or launch duplicate inference jobs; check `cache-status` and
live processes first. Large data/checkpoints/exports remain ignored by Git.

Full-corpus measurements: 323,751 unique inputs, 86,942,039 OpenAI tokens,
88,924,281 Voyage text tokens / 90,883,231 including retrieval prefixes. No input
exceeds model context. OpenAI list-price estimate is $11.30 before cache reuse;
actual usage is recorded per batch. Float32 unique vectors need 3.98 GB OpenAI /
2.65 GB Voyage, plus exports/indexes/backups. The tokenizer vocabularies for Voyage
large and nano were verified byte-identical. `analysis/embedding-corpus-scale-v2.json`
is a cache snapshot taken before later inference, not live progress.

The 512-section local pilot measured 29.14 inputs/s, 4,575.54 tokens/s, and 1.48 GB
peak MLX memory. Extrapolation suggests several hours; inputs and cache/export work
vary. A completed 20-snapshot two-model smoke aligns all 20 records for both models
and includes six exploratory maps. It does not establish a relevance winner.
Reports: `analysis/embedding-model-comparison-smoke.html` and companions;
`analysis/embedding-voyage-local-pilot.json`.

The user explicitly authorized full OpenAI speed and overnight MLX inference.
Active full runs live under the main checkout's shared directory:
- `data/representations/runs/retention-full-v1`: OpenAI, batch 128, concurrency 4.
- `data/representations/runs/retention-voyage-nano-v1`: local MLX, batch 32,
  concurrency 1, 8 GB allocation cap and 16K padded-token batch cap.
- Voyage detached log: `data/representations/jobs/voyage-nano-full-v1.log`.

At launch OpenAI ran under tool-managed process 95457; Voyage was restarted as a
proper detached session (uv PID 3323, parent 1). These PIDs are historical hints,
not current state. A first shell-background Voyage launch did not remain alive;
no full-corpus progress was lost. The detached run was verified writing batches
with `device: metal_gpu` in usage. Monitor using:
`uv run --extra local-embeddings python -m representations cache-status`.
Latest verification: 143 tests and 12 subtests passed; explorer script checks pass.
Full-job completion, alignment/PCA and full-corpus quality analysis are pending;
check live state before asserting completion or scheduling follow-up work.

## Completed OpenAI full-corpus features

OpenAI inference finished in 28.6 minutes: 323,751 unique inputs, 376,337 exported
logical vectors, zero failures. Original vectors persist in the shared store and
`data/representations/runs/retention-full-v1/vectors/`.

Full-corpus alignment and PCA now completed without new API calls. Alignment has
9,700 rows, 9,555 available and 145 unavailable; quality flags/source references
remain visible. Seven separate 32D PCA fits/transforms: query, document title, H1,
outline, page, section, path. Fit uses original eligible train-only sources;
held-out exact-content repeats are excluded. Mixed-split queries stay outside the
fit. Large fits use seeded randomized SVD (power 3), recorded in metadata.

Training/projected unit counts: query 7,076/9,011; title 7,332/9,364;
H1 8,335/11,964; outline 7,329/9,392; page 7,478/9,501;
section 213,388/287,293; path 7,309/9,360. The 32D fits retain roughly 32–39% of
variance and are initial feature baselines, not optimized dimensionality choices.
Original-space cosine remains authoritative; different field PCA bases cannot be
compared by cosine. Human relevance/model selection and predictive benchmarking
with these features remain pending.

Shared package entry: `data/representations/runs/retention-full-v1/features/openai-v1.json`.
This maps each named field to coordinate Parquet and saved PCA fits. Source units,
record associations, fit exclusions and checksums accompany the run. Checked-in
compact summary: `analysis/embedding-openai-corpus.json`. Full query-first report:
`data/representations/runs/retention-full-v1/reports/openai-corpus.html` (~45 MB,
ignored by Git). Latest verification: 144 tests and 12 subtests; explorer scripts
pass, including field separation and held-out perturbation invariance.

Voyage MLX continues in its detached GPU process. Check cache-status/live processes
for its current progress; do not launch a duplicate. The earlier active-job notes
are historical, and OpenAI no longer needs an inference restart.

## Traditional ML scorer handoff (v2 through v4)

PR #2 completed the full-corpus retention integration under `trad_ml_scorer/`.
9,700 rows reference 9,551 exact payload-plus-URL snapshots; the 149 difference
is shared references, not missing data or a split artifact. Eligible v2/v4 rows:
7,540 train, 945 validation, 947 test with frozen hostname assignments.

The v3/v4 follow-up preserves both iterations. V3 adds lexical relevance and
composition features; balanced importance still allowed duplicate-heading score
inflation. V4 suppresses repeated and unsupported headings in a scoring view,
without modifying parser documents. It has 86 features and C=.01. Four training
host-grouped folds choose regularization; validation AUC chooses among candidates
passing coefficient, permutation, and three post-parser manipulation gates.

Validation AUC: v2 0.66070, v4 0.67206. Reused-test AUC: v2 0.67689, v4 0.67904;
paired difference +0.00215, 95% host-bootstrap interval [-0.01517, +0.01775].
The gain is small and statistically uncertain, not independent confirmation.
V4 top coefficient share is 5.83%, top positive permutation share 10.51%.
Duplicate-heading mean score inflation fell from 0.113 to 0.013 (p95 .224 to .031).
These checks do not certify arbitrary manipulation resistance or causal uplift.

Read `trad_ml_scorer/v3/STATUS.md` for the historical iteration and
`trad_ml_scorer/v4/report.md` / `report.html` for final metrics, visual importance,
sensitivity, all feature explanations and next-round ideas. V2 remains default;
select v4 with `--model data/trad_ml_scorer/v4/model.joblib`. Full test suite:
114 tests / 12 subtests; training-only refit verification and raw inference parity
on six development snapshots passed. Do not retune against the inspected test.

**Reuse prepared data rather than redoing preparation.** Shared ignored caches in
the main repository's `data/` contain `lr/` and `trad_ml_scorer/{v2,v3,v4}/`, with
SHA-256 copy inventories. New local worktrees may link them if destinations are
absent; a separate machine needs an artifact transfer. Models and raw/prepared data
are not committed. All LR code, manifests, report outputs and predictions belong
under `trad_ml_scorer/`; original analysis and frozen v1/v2 are preserved.

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
4. Full-corpus scorer migration and versioned feature/sensitivity analysis are complete.
   Remaining work includes fresh-host confirmation, human reference review, broader
   manipulation checks, model-specific token budgeting and factual grounding checks.
   A prospective citation experiment remains separate.

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

## Completed markdownify OpenAI projection and lineage (2026-10-01)

The user requested embeddings against PR #11's completed saved markdownify corpus.
No extraction was rerun and no PR #11 parser code was copied into this branch.
The saved-document adapter verifies original raw rows, six prepared export hashes,
9,551 compressed document checksums/content identities, and ordered structure.
It imports the original splits/exclusions from the prior completed retention run
by raw-file hash/source row after checking query, URL, payload, host and label.

Persistent run: `representations/runs/markdownify-openai-v1` under the golden volume.
Input recipe: `blocks-v3-markdownify`; inline Markdown preserved for v3 blocks,
code whitespace intact, tables serialized as structured cell text/header/span JSON.
Prepared 409,730 logical units / 354,112 unique inputs for all 9,700 records.
89,650 unique inputs reused paid vectors; 264,462 new inputs completed.
OpenAI exported 408,746 vectors, zero failed requests; 984 unavailable input units
remain explicit. Inference plus portable export took 1,280.916 seconds (21.35 min),
with 146,741,037 newly reported API tokens across 2,104 batches.

Seven independent 32D training-only PCA fits are saved, along with their coordinates:
query 7,076/9,011; document title 7,332/9,364; H1 8,347/11,979;
outline 7,329/9,392; page 7,478/9,501; section 226,780/302,368; path 7,309/9,360
(training/projected unit counts). Alignment: 9,555 available / 145 unavailable
records. Saved fits reproduce sample coordinates in every field; every coordinate
is finite and has 32 dimensions. Variance retained is roughly 32–42%; this is
a baseline, not an optimized dimension or relevance evaluation.

Shared feature entry: `representations/runs/markdownify-openai-v1/features/openai-v1.json`.
Full evidence: that run's `reports/openai-corpus.html`. Full searchable lineage:
`lineage/index.html` on the persistent volume, with `lineage/registry.json`.
Versioned run lineage: `lineage/{manifest.json,records.parquet,units.parquet,tracker.html}`.
Exact joins connect raw file/row/payload -> snapshot/document -> block/chunk/unit ->
semantic request -> shard/row/SHA -> exported matrix row -> saved PCA field.
Pooled units have full member and weight provenance rather than a direct request.
Publication verified 4,632 referenced immutable vector shards and their request
metadata against catalog rows, plus raw/preprocessed and run artifact checksums.

Published compact artifacts: `analysis/data-lineage-markdownify-openai.html` (50
traceable sample records), `.json`, and `analysis/embedding-markdownify-openai-corpus.json`.
Validation: 151 tests and 12 subtests; lineage interactions/escaping tested on both
the actual sample and full tracker. Visual browser rendering was not reviewed.
Original retention artifacts remain separate; Voyage MLX remains stopped.

## Issue #10 follow-up: structured inline fidelity (2026-10-01)

`deck/markdownify-fix` adds `dom-blocks-v2`: source-referenced inline nodes,
code/deletion/hard-break/media serialization, definition containers, thematic
breaks, table cell inline annotations and version-aware chunk identities.
Frozen outputs and original analysis remain unchanged. New parser outputs require
versioned exports; corpus caches/features/models were not regenerated.

Evidence and reproduction: `analysis/inline-fidelity-v2/README.md`, with development
and held-out reports in separate subdirectories. Markdownify 1.2.3 was evaluated on
12 hand-authored development fixtures only; its default code whitespace handling
and spanning-table output prevent direct replacement. It remains a development
comparison dependency. Held-out diagnostic: 37 HTML snapshots, 32 evaluable;
required anchors 126/129 and unwanted 46/50 unchanged; 22,412 valid declared
locations, zero invalid. Sparse AI-assisted anchors do not establish semantic
accuracy. Native inline source locations remain explicitly unavailable rather
than claiming generated HTML paths. Final suite: 141 tests / 12 subtests passed.

## Markdownify default and complete corpus export (2026-10-01)

User follow-up explicitly requested replacing the incumbent conversion backend
with markdownify and redoing extraction at full-corpus scale. The active pipeline
now uses pinned runtime `markdownify==1.2.3`, via `markdownify-structured-v1`, with
custom code/terminal-break/media/table/definition converters. Handwritten Markdown
conversion is removed from the active path; structured provenance remains separate.
`conservative_dom` still names the retention-region policy. New blocks (including
native plain text) declare `dom-blocks-v3`; chunk identities include that version.

Complete new export in the shared local data volume:
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/markdownify-corpus-v1-complete/`.
All 9,700 rows reference 9,551 exact
payload-plus-URL snapshots; the 149 additional references were preserved. Zero
extraction errors/timeouts. Statuses: 9,167 selected, 334 needs review, 47 source
insufficient, 3 unsupported. 3,309,747 blocks / 278,479 chunks / 2,448 oversized chunks.
8,973,098 declared HTML locations valid, zero invalid; missing/ambiguous mappings
stay explicit. Independent verification reread all original rows and checked all
document file/content checksums, six artifact hashes and ordered chunk coverage.
Full documents/raw data stay out of Git; original caches and frozen outputs unchanged.

Report/reproduction: `analysis/markdownify-corpus-v1/README.md`; release development,
held-out and corpus reports live in separate subdirectories. Development fixtures
12/12 expected outputs; reused held-out HTML selected anchors unchanged at 126/129
required and 46/50 unwanted. Not human semantic gold or citation-uplift evidence.
CLI: `python -m preprocessing.corpus` (offline, versioned, bounded, resumable) and
`python -m preprocessing.markdownify_report` for independently scoped evidence.
Final regression suite: 154 tests / 12 subtests passed. Four-worker complete run
(including indexing): 1,191.539 seconds. Models/features were not retrained or
regenerated; that remains separate from this completed extraction request.

## Shared persistent data volume (2026-10-01)

The user designated `/Users/ext-weihsiang.lin/Documents/profound/data` as the golden
local data volume. This project's namespace is `content-optimization-system/`.
Five original Parquet inputs were copied into its `raw/` and verified byte-for-byte
with SHA-256; their existing repository location was left untouched. This worktree's
entire `data/processed/` (including completed exports and interrupted-run journals)
was moved into the shared namespace. Its ignored `data/` is now a symlink to that
namespace. The completed corpus manifest is unchanged. Other worktrees were not
modified. Existing manifest paths describe the original extraction environment;
the shared paths above identify the current storage location. Follow `AGENTS.md`
for unique run directories, identity-checked resume, and cross-session discovery.
