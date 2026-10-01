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

- `analysis/extraction-evaluation.html`: completed five-method benchmark.
- `analysis/reader-lm-review.html`: stopped Reader-LM run, matched completed-page comparison.
- `analysis/reader-lm-pilot.html`: three development examples with expanded context/output budgets.
- `analysis/reader-lm-progress.html`: partial run ledger, **not** a final ranking.


The implementation in `preprocessing/` compares the frozen BeautifulSoup baseline,
Trafilatura, Mozilla Readability + Turndown/GFM, conservative DOM blocks, and a
native Markdown/text adapter. It uses only the supplied saved payloads: no browser
rendering, page fetching, remote extraction API, or dynamic index.

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

## Logistic-regression baseline

The handcrafted LR prototype predicts membership in the dataset's within-host `top` class. Its 35 inference-time features cover prompt alignment, prompt style, content structure, URL paths, and extraction quality. See [the result report](trad_ml_scorer/report.html), [Markdown results](trad_ml_scorer/report.md), and [feature definitions](trad_ml_scorer/feature_definitions.md).

Install the locked environment with `uv sync --locked` (or a workspace-local `uv` binary). Run from the repository root:

```sh
uv run python scripts/prepare_lr_data.py --input-dir data/raw --workers 4
uv run python scripts/train_lr.py
uv run python scripts/evaluate_lr.py
uv run python scripts/verify_lr.py --input-dir data/raw
uv run python -m unittest discover -s tests -p test_lr.py -v
```

In this worktree, the raw source was supplied with `--input-dir ../../data/raw`. Preparation writes the local feature table, source/exclusion records, split manifest, and fingerprints to ignored `data/lr/`. The saved inference pipeline is `data/lr/model.joblib`; published metrics, split assignments, and PNG/SVG plots are in `trad_ml_scorer/`. These scripts refuse to overwrite completed data, models, or test evaluations. For an explicitly new experiment, pass a new `--output-dir` to preparation and matching `--data-dir` / `--output-dir` arguments to training and evaluation. Rebuild presentation alone with `uv run python scripts/evaluate_lr.py --report-only`.

Score a supplied snapshot (load only trusted joblib models):

```sh
uv run python scripts/predict_lr.py \
  --prompt "What are the best running shoes?" \
  --html-file /path/to/page.html \
  --url https://example.com/running-shoes
```

Seed 42 fixes the 80/10/10 hostname assignment. After duplicate/conflict/blank-query exclusions, splits contain 7,561 / 947 / 939 rows. Cross-split hostname, URL, exact HTML, nonempty normalized extracted-text, and exact-record overlaps are zero. All imputation and scaling fit on training data. Validation log loss selects the feature variant and `C`; the selected model remains train-only, with no test-driven retuning. Validation-only feature permutation, family ablation, and response curves explain sensitivity without using test labels for selection.

The selected prompt-plus-page LR (`C=0.01`) achieves test ROC-AUC **0.6688** (95% host-bootstrap interval **0.6288–0.7026**), log loss **0.6479**, Brier score **0.2285**, and accuracy **61.45%**. This is a working baseline with modest discrimination, not established production readiness. Earlier full-dataset exploration, repeated prompts across hosts, and possible near duplicates or related host organizations limit claims of completely untouched evaluation. The score is not an absolute citation probability or a causal content-editing effect.
