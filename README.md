# Citation dataset exploration

Preliminary analysis for `project-brief.md`, before choosing a content-generation prototype.

## Setup

Use `uv` for all Python environment and dependency operations. A workspace-local copy is available at `.tools/uv` if `uv` is not on `PATH`.

```sh
.tools/uv sync
```

## Offline extraction benchmark

**Current workflow decision:** retention-first HTML parsing using conservative DOM
blocks, with native Markdown/text handling. Source warnings remain attached rather
than dropping content. See `spec/downstream-document.md` for the document/chunk
contract and reproduction instructions. `analysis/retention-export.json` records
the 100-snapshot structured export; full-corpus migration is not yet performed.

Report index:

- `analysis/markdownify-corpus-v1/README.md`: default markdownify-powered extraction,
  full-corpus re-extraction and separately scoped development/held-out evidence.
- `analysis/extraction-evaluation.html`: completed five-method benchmark.
- `analysis/inline-fidelity-v2/README.md`: issue #10 structured inline fidelity fix,
  development markdownify comparison, and separate held-out diagnostics.
- `analysis/reader-lm-review.html`: stopped Reader-LM run, matched completed-page comparison.
- `analysis/reader-lm-pilot.html`: three development examples with expanded context/output budgets.
- `analysis/reader-lm-progress.html`: partial run ledger, **not** a final ranking.


The implementation in `preprocessing/` compares the frozen BeautifulSoup baseline,
Trafilatura, Mozilla Readability + Turndown/GFM, conservative DOM blocks, and a
native Markdown/text adapter. It uses only the supplied saved payloads: no browser
rendering, page fetching, remote extraction API, or dynamic index.

The active HTML retention pipeline now uses **python-markdownify 1.2.3** rather
than the handwritten Markdown serializer. Structured blocks own provenance and
source boundaries; custom converters preserve code whitespace and table/definition
HTML where Markdown is lossy. Native Markdown/text keeps native parsing. Full-corpus
extraction is independently versioned; existing frozen evaluation outputs stay intact.

Persistent local data lives at
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/`.
Use `raw/` for source snapshots and versioned `processed/` directories for exports
and checkpoints. See `AGENTS.md` for cross-session storage and resume conventions.
This worktree's ignored `data/` symlink resolves to that shared directory.

```sh
uv sync --locked
uv run --offline python -m preprocessing.corpus \
  --input-dir /path/to/local/data/raw \
  --output data/processed/markdownify-corpus-v1-replay --workers 4
uv run --offline python -m preprocessing.markdownify_report --mode corpus \
  --corpus-export data/processed/markdownify-corpus-v1-replay \
  --output analysis/markdownify-corpus-v1-replay/corpus
```

The export retains a reference for every source row and a gzip document per exact
payload-plus-URL snapshot, including full metadata, blocks and chunks. JSONL and
Parquet indexes accompany a fingerprinted manifest. Original raw data and full
exports stay outside Git; delivery reports contain bounded, escaped previews.

```sh
.tools/uv sync --dev
npm ci --prefix preprocessing/node
.tools/uv run --offline python -m preprocessing.prepare_eval --materialize
.tools/uv run --offline python -m pytest -q
.tools/uv run --offline python -m preprocessing.fixture_benchmark
.tools/uv run --offline python -m preprocessing run --split all --output data/processed/replay
.tools/uv run --offline python -m preprocessing.benchmark --results data/processed/replay/results.jsonl
.tools/uv run --offline python -m preprocessing.selection_report --run data/processed/replay
open analysis/extraction-evaluation.html
```

Raw parquet files must first be present at `data/raw/`. Materialization verifies
their hashes and restores the existing evaluation snapshots; it does not resample.
The checked-in manifest freezes 100 distinct hosts (60 development, 40 held-out),
with no hostname or identical-payload overlap between splits. All five candidates
receive every snapshot and report unsupported formats explicitly. To resume an
interrupted run, repeat the run command with `--resume`; changed extraction code,
dependencies, configuration, or evaluation manifest invalidate cached results.

`analysis/extraction-evaluation.html` provides metrics, denominators, structural
fixture results, and filterable per-document candidate output/anchor comparisons.
Its JSON companion contains detailed per-method, per-split, per-stratum metrics.
References in `evaluation/extraction/annotations.json` are **AI-assisted source-only
anchors, not human gold or exhaustive annotations**. Retention and boilerplate
leakage are anchor-based measurements, not whole-document recall and precision.
The human acceptance gates remain unassessed; held-out non-HTML cases contain
Markdown only, so plain-text quality has no held-out estimate. Synthetic structural
checks are separate from real-page accuracy. No citation-uplift claim is made.

Local run artifacts include `results.jsonl`, `extractions.parquet`, `blocks.parquet`,
`source_features.parquet`, `records.parquet`, `snapshots.parquet`, and a versioned
run manifest. Source metadata/JSON-LD remain separate from candidate text, while
structured blocks preserve tables, nested lists, code, links and source mappings
where available. Selection proposals are diagnostic and abstain on disagreement;
they are not a validated production policy. The current selection default is the
retention-first policy; the earlier precision proposal is retained as
`select_precision_candidate` for provenance. The runner currently targets the frozen
evaluation set, not full-corpus ingestion. Original v1 analysis stays unchanged;
human review, corpus migration, and extractor-sensitive reanalysis remain follow-up
work in `plan/snapshot-preprocessing.md`.

### Held-out results

For the additive Hugging Face Reader-LM benchmark served locally on Apple Silicon,
see `preprocessing/READER-LM.md`. It has separate dependencies, resource limits,
run artifacts, and report; it does not replace the frozen five-candidate run.

HTML content scores cover 32 evaluable pages, 129 required anchors and 50 unwanted
anchors; five additional held-out HTML snapshots were source-unevaluable. Higher
retention and lower leakage are better.

| Method | Required-anchor retention | Unwanted-anchor leakage |
| --- | ---: | ---: |
| Frozen baseline | 121/129 (93.8%) | 30/50 (60.0%) |
| Trafilatura | 100/129 (77.5%) | 11/50 (22.0%) |
| Readability + Turndown | 111/129 (86.0%) | 11/50 (22.0%) |
| Conservative DOM | 126/129 (97.7%) | 46/50 (92.0%) |
| Native adapter — 3 Markdown pages only | 13/13 (100%) | 2/2 (100%) |

The native result is not directly comparable to HTML rows. Readability retains
more selected content than Trafilatura on held-out HTML at equal measured leakage,
reversing their development retention ranking. Conservative extraction preserves
content but also substantial boilerplate. These results do not establish a universal
winner or justify changing the development-frozen selection policy on the test set.
The complete run has 500 explicit outcomes, including unsupported formats and six
empty outputs, with zero exceptions or timeouts. Resume preserved result bytes.

The provided ZIP remains in Downloads. Five parquet files are extracted into `data/raw/`; these files and the local environment are excluded from Git. Archive provenance and its verified SHA-256 are in `analysis/provenance.json`.

## Reproduce the analysis

### Textual embedding pipeline

The implemented `representations` package consumes the selected structural outputs from snapshot preprocessing. It prepares query, document-title/H1, outline, section, page, and URL-path views; calls hosted embedding APIs; derives query alignment; saves PCA fits; and builds offline UMAP explorers. It does not require a local GPU or re-extract HTML.

Read [the specification](spec/embedding-representations.md) and [implementation plan](plan/embedding-representations.md) for evaluation boundaries. OpenAI `text-embedding-3-large` is the initial hosted baseline (3,072 dimensions), with Voyage 4 Large and hosted Qwen3 available for comparison. A baseline is not a reviewed model winner.

Install from the updated lockfile with `uv sync` (or the available `.tools/uv`). Start with a small upstream sample:

```sh
uv run python -m representations prepare \
  --input data/processed/<preprocessing_run_id> \
  --output data/representations/<run_id> \
  --limit 20

uv run python -m representations review \
  --run data/representations/<run_id> \
  --output data/representations/<run_id>/relevance-review.json

uv run python -m representations embed \
  --run data/representations/<run_id> --model openai-large --resume

uv run python -m representations align \
  --run data/representations/<run_id> --model openai-large

uv run python -m representations project \
  --run data/representations/<run_id> --model openai-large \
  --view page --components 2 --exploratory --umap

uv run python scripts/build_embedding_report.py \
  --run data/representations/<run_id> --output analysis/embedding-explorer.html
```

For the full corpus, use PR #2's shared prepared cache as `--input` (on this machine: `/Users/ext-weihsiang.lin/Documents/profound/content-optimization-system/data/trad_ml_scorer/v2`). `prepare` only serializes saved documents into embedding inputs; it does not rerun extraction or scorer preparation. It preserves retained `needs_review` content, source chunk/block IDs, original record provenance, exclusions, and existing splits. The 9,551-snapshot input adapter has been checked across all 9,700 records; the original full-corpus OpenAI run is complete (see the corpus summary below). See [adapter validation](analysis/embedding-retention-validation.json) and the [20-snapshot retention evidence report](analysis/embedding-retention-explorer.html).

If an upstream evaluation export omits prompts, add `--raw-root data/raw` to `prepare`. Hydration verifies the raw file hash and source-row payload/URL before reading original prompts and labels. Preparation refuses incomplete upstream runs or broken provenance/joins. `--limit` includes both selected and abstained snapshots; unavailable units stay explicit.

The current default scope is hosted OpenAI (`OPENAI_API_KEY`) and local Voyage nano on Apple silicon. Voyage large and hosted Qwen adapters remain available in historical/custom configurations but are deferred. Never put keys in configuration. For Qwen, copy `representations/config.json`, pin `provider_order` to a verified OpenRouter route, and pass the copy to `prepare --config`. Queries get the documented Qwen instruction; Voyage uses query/document modes; OpenAI uses the same embedding interface for both roles. API routing and dimensions must be verified on the chosen endpoint.

Shared persistence and local inference are described in [embedding storage](spec/embedding-storage.md). On this machine all data lives in `/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system`; the main checkout and embedding worktree's `data` paths link there. The default cache uses the persistent sibling `data/<repository name>/representations/shared-store` when present, otherwise the main checkout's data directory. Set `CONTENT_OPTIMIZATION_DATA_ROOT` for another project volume. Batch-size, timeout and concurrency changes do not invalidate saved embeddings. Existing paid run-local vectors migrate automatically on resume. Current execution is OpenAI only; local MLX was stopped with completed batches retained.

```sh
uv sync --extra local-embeddings
uv run --extra local-embeddings python -m scripts.download_voyage_nano
uv run --extra local-embeddings python -m representations cache-status
uv run python -m representations cache-backup \
  --cache-root /path/to/shared-store --output /path/to/new-backup
uv run python -m representations reuse-inputs \
  --run /path/to/frozen-input-run --output /path/to/new-model-run --config /path/to/config.json
uv run --extra local-embeddings python -m representations embed \
  --run /path/to/new-model-run --model voyage-nano
```

Local nano requires the official checkpoint at `<main checkout>/data/models/voyage-4-nano`, its `source.json`/checksum manifest, and the pinned backend from `uv.lock`. An explicit `model_path` in a custom config can override the location. It checks token limits before inference; no silent truncation is allowed. See [local pilot](analysis/embedding-voyage-local-pilot.json) and [two-model evidence smoke](analysis/embedding-model-comparison-smoke.html). The latter covers 20 snapshots and does not establish which model is better.

The first input policy uses lossless UTF-8 byte ceilings (4,096-byte sections; 7,000-byte full-page inputs), rather than claiming tokenizer counts. This conservative policy avoids local model/tokenizer downloads and fits the shortest candidate context with instruction headroom. Oversized page/outline/title/path views retain all chunks and a separately marked byte-weighted pooled vector. Prompts exceeding the common ceiling abstain. No input is silently truncated.

`embed --max-requests 12` bounds new API work for a smoke test. Run `--resume --retry-failed` to explicitly retry failed requests; compatible successful requests are cached. A bounded run stays marked partial. `align` may inspect partial coverage; model selection and corpus conclusions require completed, reviewed inputs.

The completed OpenAI corpus has seven independent 32-dimensional training-fit projections: query, document title, H1, outline, page, section, and URL path. The [corpus summary](analysis/embedding-openai-corpus.json) records coverage, fit sizes, and explained variance. Shared artifacts are under `<main checkout>/data/representations/runs/retention-full-v1`; `features/openai-v1.json` maps named fields to their coordinate and fit files. Alignment covers all 9,700 rows, with 9,555 usable query–section matches. The full evidence HTML is stored in that run's `reports/` directory; it is large and ignored by Git.

The saved markdownify corpus is supported as a separate input version; use
`--split-reference` to carry the original verified raw-row splits/exclusions forward.
`blocks-v3-markdownify` keeps saved inline formatting and structural provenance.
Exact unchanged inputs reuse the shared vector cache across preprocessing versions.
See [data lineage and reproduction](spec/data-lineage.md) for the raw → document →
embedding → projection joins. The persistent volume's `lineage/index.html` is the
full searchable tracker; the versioned run keeps complete record/unit lineage
Parquets and the saved field feature bundle. The original retention run stays intact.
The published [lineage tracker sample](analysis/data-lineage-markdownify-openai.html)
and [markdownify embedding summary](analysis/embedding-markdownify-openai-corpus.json)
are compact, checked-in counterparts to the full local artifacts.

```sh
uv run python -m representations training-manifests --run /path/to/run --model openai-large
uv run python -m representations project --run /path/to/run --model openai-large \
  --view title --subview document_title --components 32 \
  --fit-manifest /path/to/run/fit-manifests/document_title.json
uv run python -m representations corpus-summary --run /path/to/run \
  --model openai-large --output /path/to/summary.json
```

Training manifests reuse original hostname splits, exclude upstream-ineligible and mixed-split source units, and remove exact held-out content from the fit. Coordinates are produced for all available units, including retained flagged sources. Large fits use seeded randomized SVD, with solver/power recorded; vectors load lazily to avoid duplicating the full corpus in RAM. The 32-dimensional output is an initial representation baseline, not a validated optimum. Use original-space vectors for query–field cosine; separate field PCA spaces are not comparable.

For predictive PCA, supply a JSON `--fit-manifest` containing `scope: "training"`, `unit_ids`, and `heldout_unit_ids`. Fitting rejects overlapping IDs/hostnames and known duplicate content. `project --exploratory` explicitly fits available corpus vectors for visualization. Keep these maps separate from held-out predictive features. Use `apply --projection <folder> --output <parquet>` to transform compatible runs without refitting.

Review manifests contain editable relevance grades (0–3) and fixed query/candidate identities. Complete all candidate grades before `evaluate --annotations <review.json> --output <metrics.json>`. Metrics describe the judged pools, not whole-corpus recall. `analyze --output <analysis.json>` runs grouped structural/path/alignment ablations and fold-fitted PCA; it requires sufficient independent hosts and both labels. It excludes label-conflicted URLs, averages repeated snapshots/queries explicitly, and reports uncertainty. Small smoke tests do not establish citation uplift.

Run meaningful offline integration checks without credentials:

```sh
uv run python -m unittest discover -s tests -v
```

Vectors and run data remain under ignored `data/`. Image asset references are reserved in the unit schema; fetching images, visual embeddings, and learned fusion are deferred.

Run from the repository root:

```sh
.tools/uv run python scripts/audit_data.py
.tools/uv run python scripts/analyze_quality.py
.tools/uv run python scripts/analyze_content.py
.tools/uv run python scripts/analyze_sensitivity.py
```

The scripts produce machine-readable results in `analysis/`. See their individual outputs for feature definitions, sample sizes, and caveats.

## HTML report

Open `analysis/brief-report.html` for the briefing, charts, and 20 searchable sample rows with expandable extracted text and escaped raw payload excerpts. The sample combines three matched pairs, six quality/language examples, and eight deterministic random rows balanced by label. Exact source locations and payload hashes are in `analysis/report_samples.json`.

Rebuild after the analysis outputs exist:

```sh
.tools/uv run python scripts/build_report.py
```

## Dataset audit

| Measure | Observed value |
| --- | --- |
| Parquet files | 5, SNAPPY compression; 616,945,207 bytes total |
| Rows | 9,700 |
| Hostnames | 970, each with exactly five top and five bottom rows |
| Distinct exact URLs | 9,527 |
| Distinct nonblank exact prompts | 9,011 |
| Null values | Zero across all five columns |
| Blank prompts | 91: 70 top, 21 bottom |
| Excess exact duplicate rows | 28 |
| URLs carrying both labels | 14, involving 76 rows |
| Median raw HTML length | 126,218 characters |
| Maximum raw HTML length | 6,777,759 characters |

All columns are strings: `prompt`, `citation_category`, `href`, `hostname`, and `html_content`. Four parquet parts contain 2,263 rows each; the fifth contains 648. Row totals agree with file metadata, and ZIP integrity checks pass.

The quality audit normalizes prompts with Unicode NFKC, case folding, and whitespace collapse while preserving punctuation. Only 50 hosts share any nonblank normalized prompt across labels; 920 share none. There are 74 shared host/query groups, of which 42 contain different URLs across labels. These are candidate comparisons before removing label conflicts or scrape failures. Different wording can still express the same intent, so these counts do not establish the number of semantically comparable questions.

Conservative text heuristics flag 185 error/blocked-page candidates (69 top, 116 bottom). Of 64 rows without recognized HTML markup, 58 look like Markdown. These flags are not verified HTTP statuses or MIME types. URL path hints also differ across labels: top has 143 homepage rows versus 22 bottom, while editorial-looking paths occur in 1,348 top versus 1,517 bottom rows. Page purpose and retrieval quality need sensitivity checks before making editing recommendations.

Excluding conflicting URLs and requiring recognized HTML without failure or sparse-body flags leaves 36 matched host/query groups. The content sensitivity analysis applies a further minimum of 100 extracted words and deduplicates pages, so its eligible count can be smaller.

## Examples to discuss

- BryteFlow: for the same SAP HANA-to-Redshift migration query, the top URL is `/sap-to-redshift`, while the bottom URL is `/sap-on-aws-fundamentals`. The bottom snapshot has more body text. This motivates investigating query-specific coverage; it does not establish that shorter content is better.
- AccuKnox: the same runtime-defense query pairs a top CWPP article with a bottom snapshot titled “Page Not Found.” Scrape quality can produce an apparent content-performance difference.
- Bouqs: the same homepage and prompt occur with both labels, and the static snapshot contains almost no body text. This is unsuitable as an uncomplicated top-versus-bottom editing example.

These observations come from supplied snapshots, not live website checks. Full URLs, prompts, titles, and excerpts are in `analysis/quality_analysis.json`.

## Preliminary content associations

Content extraction collapses 173 repeated page rows into 9,527 page records and excludes 14 conflicting-label pages from comparisons. It selects the largest `main`/`article`/`role=main` text container when available, otherwise a cleaned body, after removing common boilerplate. There are 24 pages with multiple HTML snapshots; the longest snapshot is selected deterministically. This is an approximation of main content, not a browser-rendered extraction.

The stricter sensitivity excludes 328 unique URLs with any failure, sparse-body, or non-HTML flag, then requires at least 100 extracted words and an unambiguous label. It retains 8,687 pages overall and 931 hosts with both labels available. Not every retained page belongs to a paired host.

| Feature | Median within-host top-minus-bottom mean difference | Hosts higher / lower / tied |
| --- | --- | --- |
| Query token coverage in title | +7.64 percentage points | 651 / 275 / 5 |
| Query token coverage in body | +7.83 percentage points | 633 / 294 / 4 |
| Extracted heading count | +4.00 | 656 / 263 / 12 |
| Extracted word count | +214.4 | 602 / 326 / 3 |

Coverage is literal token overlap with a small English stopword list, not semantic relevance or answer completeness. Top prompts are shorter on average and more often contain English comparison markers (34.2% versus 23.5%), which can confound coverage. Language and query intent are not controlled by hostname pairing.

The directions above also appear within editorial-looking URL paths, covering 2,640 pages and up to 357 paired hosts. However, heading density per 1,000 words has a weaker editorial-only association; heading count partly reflects content length. Tables occur more often in top pages broadly, but the median host difference is zero. List presence becomes weak after quality filtering. Article schema has no consistent positive association, and JSON-LD presence is nearly unchanged in editorial-only comparisons. None supports a universal formatting prescription.

### Same-query sensitivity

After all filters, there are only 29 matched host/query groups across 27 hosts and 66 unique pages. Differences are computed within query, then averaged within host so that hosts remain equally weighted.

| Feature | Hosts favoring top / bottom / tied | Median host difference |
| --- | --- | --- |
| Title token coverage | 13 / 1 / 13 | 0 |
| Body token coverage | 8 / 10 / 9 | 0 |
| Heading count | 14 / 8 / 5 | +1 |
| Word count | 15 / 12 / 0 | +43 |
| Table presence | 1 / 2 / 24 | 0 |

Title alignment remains a promising hypothesis, but this subset is small and selected. Body overlap, length, and table presence do not show the broad dataset's consistent direction here. Do not interpret the broad +214-word difference or +4-heading difference as an editing target. No held-out predictive validation or prospective citation experiment has been performed.

## Brainstorming directions

1. **Page improvement assistant:** Given a target query, existing page, and approved factual material, identify coverage gaps and generate a revised title/outline/section. Attach the relevant dataset evidence and its limitations to each proposed edit. This is the strongest initial direction if a compact, inspectable demo is the priority.
2. **Query-specific content blueprint:** Generate a draft for one query class from approved sources. Use structural findings as optional hypotheses, conditional on page purpose, and retain source traceability for factual claims.
3. **Evidence explorer with generation:** Let the user inspect matched examples, change quality/page-type filters, select a hypothesis, and generate a corresponding draft. This makes uncertainty visible when findings vary by subset.

For any direction, a trial-sized success criterion is an end-to-end draft with traceable evidence, useful query coverage, and no unsupported factual additions. Citation uplift is a separate future evaluation. Clarify label construction, engine/time coverage, citation counts and exposure, scrape timing, and factual grounding material before claiming performance improvements.

## Interpretation

The top/bottom labels describe relative performance within a hostname. Both classes already appeared in answer-engine citations. The supplied schema contains prompts, labels, URLs, hostnames, and HTML, but no cleaned Markdown, citation counts, exposure denominators, engine identifiers, or observation dates.

Treat associations as exploratory hypotheses. Page purpose, query intent, language, scrape failures, shared templates, and repeated URLs can distort comparisons. An observed association does not show that changing the feature increases citations. A content prototype should ground its factual claims in supplied source material and trace its editing rules to the analysis. Measuring citation uplift requires a separate prospective evaluation.

## Traditional ML scorer

The current **v2 scorer uses the retention-first parser as its source of truth**. LR code, plans, visual reports, and feature explanations live in [`trad_ml_scorer/`](trad_ml_scorer/README.md), with frozen original results in [`trad_ml_scorer/v1/`](trad_ml_scorer/v1/report.md) and retention-based results in [`trad_ml_scorer/v2/`](trad_ml_scorer/v2/report.md). See the [v2 HTML report](trad_ml_scorer/v2/report.html) for feature importance and sensitivity charts.

The full corpus is parsed once per exact payload-plus-URL snapshot. Queries and labels are joined afterward; original metadata, structured blocks, sections, lists, and table headers provide features. V2 reuses v1's hostname assignments and reports both its own eligible population and refitted comparisons on common rows. Training transformations and regularization/feature-variant selection use train and validation respectively. Test results are explicitly a **reused v1 host benchmark**, not new independent confirmation.

Run from the repository root:

```sh
uv sync --locked
uv run python -m trad_ml_scorer.predict_lr \
  --prompt "How to choose running shoes" \
  --html-file /path/to/page.html \
  --url https://example.com/shoes
uv run python -m pytest tests/test_lr.py tests/test_retention_scorer.py -q
```

The default model is `data/trad_ml_scorer/v2/model.joblib`; pass `--model data/lr/model.joblib` for the preserved v1 model. Models and intermediate source documents stay outside Git. See the [scorer guide](trad_ml_scorer/README.md) for full-corpus preparation, fitting, evaluation, and artifact verification commands. V2 returns parser quality status and abstains if no usable content is selected. Scores describe the sampled within-host top class among already-cited pages; they do not establish absolute citation probability or causal editing uplift.
