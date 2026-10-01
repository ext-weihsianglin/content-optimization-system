# Citation dataset exploration

Preliminary analysis for `project-brief.md`, before choosing a content-generation prototype.

## Setup

Use `uv` for all Python environment and dependency operations. A workspace-local copy is available at `.tools/uv` if `uv` is not on `PATH`.

```sh
.tools/uv sync
```

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

If an upstream evaluation export omits prompts, add `--raw-root data/raw` to `prepare`. Hydration verifies the raw file hash and source-row payload/URL before reading original prompts and labels. Preparation refuses incomplete upstream runs or broken provenance/joins. `--limit` includes both selected and abstained snapshots; unavailable units stay explicit.

Set `OPENAI_API_KEY`, `VOYAGE_API_KEY`, or `OPENROUTER_API_KEY` in the environment for the corresponding adapter. Never put keys in configuration. For Qwen, copy `representations/config.json`, pin `provider_order` to a verified OpenRouter route, and pass the copy to `prepare --config`. Queries get the documented Qwen instruction; Voyage uses query/document modes; OpenAI uses the same embedding interface for both roles. API routing and dimensions must be verified on the chosen endpoint.

The first input policy uses lossless UTF-8 byte ceilings (4,096-byte sections; 7,000-byte full-page inputs), rather than claiming tokenizer counts. This conservative policy avoids local model/tokenizer downloads and fits the shortest candidate context with instruction headroom. Oversized page/outline/title/path views retain all chunks and a separately marked byte-weighted pooled vector. Prompts exceeding the common ceiling abstain. No input is silently truncated.

`embed --max-requests 12` bounds new API work for a smoke test. Run `--resume --retry-failed` to explicitly retry failed requests; compatible successful requests are cached. A bounded run stays marked partial. `align` may inspect partial coverage; model selection and corpus conclusions require completed, reviewed inputs.

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
