# Snapshot preprocessing specification

Status: Draft for implementation

Date: 2026-10-01

Implementation plan: [../plan/snapshot-preprocessing.md](../plan/snapshot-preprocessing.md)

## Objective

Produce faithful, structured, auditable content from the payloads already supplied in the citation parquet files. Measure extraction quality before using the outputs to make content recommendations.

The pipeline must preserve the historical evidence available in each snapshot. It does not simulate a proprietary answer engine or predict citation uplift. “High fidelity” means retaining the supplied document's useful content and structural relationships while identifying boilerplate, ambiguity, and missing content.

## Scope boundary

In scope:

- Offline processing of the existing `data/raw/*.parquet` files.
- Classification of HTML, Markdown, plain text, error payloads, and ambiguous inputs.
- Preservation of source records, distinct snapshots, metadata, and original DOM features.
- Comparison of local extractors, structured content output, deterministic selection, and explicit abstention.
- Human-reviewed extraction evaluation and an offline comparison report.
- Recalculation of citation features and sensitivity analyses using versioned outputs.

Out of scope:

- Browser rendering, Playwright, JavaScript execution, screenshots, OCR, or visual-layout reconstruction.
- Live URL fetching, recrawling, loading remote assets, or updating supplied snapshots.
- Jina Reader API or any other external extraction service.
- Dynamic web-document indexes, crawling infrastructure, retrieval indexes, embeddings, and ranking systems.
- Reconstructing absent PDF binaries from URLs or fetching missing content.
- LLM rewriting, inferred missing text, translation, and generated image descriptions during extraction.
- Content generation, causal citation experiments, and production serving infrastructure.

The preprocessing command performs no network requests. Original URLs provide provenance and a base for resolving relative links as strings; they are never fetched. Dependency installation is a separate setup operation.

## Existing evidence and limitations

The current corpus contains 9,700 citation rows, 970 hostnames, and 9,527 distinct exact URLs. All five input fields are strings: `prompt`, `citation_category`, `href`, `hostname`, and `html_content`.

The audit found 91 blank prompts, 28 excess exact duplicate rows, 14 URLs with both labels, and 58 Markdown-like payloads without recognized HTML. These are observations about this input version, not constants to enforce on future inputs.

The existing `scripts/analyze_content.py` is the baseline. It flattens text, removes broad element categories, selects the largest semantic content container, and selects the longest snapshot per URL. These choices can lose content or retain boilerplate. It is not an HTML-to-Markdown pipeline.

Source sparsity and extraction failure are distinct. A payload that contains almost no text cannot be repaired by a better parser. Similarly, a short extraction may be a valid short product page rather than a failure. Word count alone must not decide validity.

## Data identity and provenance

Preserve three separate concepts:

| Entity | Identity | Purpose |
| --- | --- | --- |
| Citation record | Input file digest + zero-based row number | Preserve every original association, including duplicates and conflicting labels |
| Payload | SHA-256 of the exact UTF-8 encoding of the stored string | Detect identical payloads without modifying source text |
| Snapshot | Payload digest + exact source URL | Preserve different payloads for one URL and URL-dependent interpretation of the same payload |

- Store the original hostname, URL, prompt, and label without destructive normalization.
- Retain source file name, file digest, row number, payload digest, and snapshot ID.
- A shared payload can reuse URL-independent work; URL resolution must still use the correct source URL.
- Keep all distinct snapshots. Do not silently pick the longest one.
- Do not invent capture timestamps from ZIP entry dates, filesystem modification times, or article publication dates.
- Keep citation labels and prompts in the association table, outside the extractor and selection interfaces.
- Downstream analysis must explicitly handle multiple snapshots and conflicting labels. Preprocessing preserves them rather than resolving the label ambiguity.

## Processing stages

### 1. Input classification

Classify the stored payload by its contents, not its URL suffix. Produce `html`, `markdown`, `text`, or `unknown`, plus separate quality flags such as `possible_error_response`, `possible_script_shell`, and `possible_truncation`.

A `.pdf` URL whose stored payload is Markdown uses the Markdown path. Preserve mixed or uncertain input with diagnostic reasons rather than forcing it through an HTML parser. Classification confidence is a heuristic status, not a calibrated probability.

### 2. Source inventory

Before destructive cleaning, capture relevant HTML evidence:

- Document title, language/direction declarations, description, canonical link, and author/date metadata when explicitly present.
- Headings, semantic containers, lists, links, tables, image alt text, and code/preformatted sections.
- JSON-LD blocks, JSON parse outcomes, declared types, and provenance. JSON-decodable does not mean schema-valid.
- Explicit visibility attributes and other static visibility hints, distinguished from unknown computed visibility.

Store metadata separately from visible content. An author or product mentioned only in JSON-LD must not be inserted into body text. HTML document title, extracted article title, and visible H1 are separate fields.

### 3. Candidate extraction

Implement adapters with a common input/output contract:

| Adapter | Role |
| --- | --- |
| Existing BeautifulSoup heuristic | Frozen baseline for comparison; not automatically the production fallback |
| Trafilatura | Local content extraction candidate with explicit preservation settings |
| Mozilla Readability + Turndown/GFM | Independent reader-mode candidate, followed by Markdown serialization |
| Conservative DOM block adapter | Candidate for retaining multiple useful sections on non-article pages |
| Markdown/text adapter | Preserve and structure already-extracted text without HTML conversion |

Python orchestration and dependencies use `uv`. The Readability adapter uses a small Node worker with pinned dependencies and a lockfile. Disable script execution and resource loading in its DOM environment. Avoid spawning a fresh Node process per document.

Do not apply the current destructive cleanup before passing HTML to competing extractors. Each candidate receives the preserved input and owns its documented cleanup policy.

The conservative adapter should use existing DOM structure and bounded heuristics. It is not a custom visual-layout engine. Do not add per-host extraction rules during the initial benchmark.

### 4. Structured representation and serialization

The authoritative content output is an ordered block representation. Markdown and plain text are derived views.

Each block includes:

| Field | Requirement |
| --- | --- |
| `block_id`, `order`, `parent_id` | Stable ordering and nesting within an extraction |
| `type` | Heading, paragraph, list, list item, table, code, image, quote, or other |
| `text` | Source-derived content, with documented whitespace normalization |
| `heading_level` | Original level when applicable |
| `links` | Original target and resolved target; never fetch either |
| `table` | Caption, cells, header roles, row/column positions, row/column spans |
| `source_locator` | Source DOM path or source text range when a reliable mapping exists |
| `mapping_status` | Exact, normalized match, ambiguous, or unavailable |

Do not fabricate source offsets or force an ambiguous match to one source node. Preserve uncertain mappings as such.

Preserve nested list structure, code whitespace, existing image alt text, and heading order. Do not flatten complex tables into misleading GFM tables: retain a structured table and an HTML representation when Markdown cannot express the relationships. DOM order is not claimed to be visual reading order.

### 5. Diagnostics and selection

Compare candidates on content retention, suspected boilerplate, structural survival, extraction errors, and disagreement. Keep candidate outputs available for inspection.

Selection rules must be deterministic and based on extraction evidence. They must not access citation category, target query, query overlap, or downstream top/bottom separation. Do not optimize for shortest output, longest output, or most favorable citation association.

Use statuses such as `selected`, `needs_review`, `source_insufficient`, and `unsupported_format`. Store the chosen adapter, reasons, quality flags, and alternatives. A failed candidate is not automatically a failed source.

Unresolved disagreement should be visible to downstream consumers. Analysis must report coverage and exclusions and include alternate-parser sensitivities rather than treating selected output as unquestionable truth.

## Output contract

Write versioned artifacts under `data/processed/<run_id>/`:

| Artifact | Contents |
| --- | --- |
| `records.parquet` | Every original citation record and its snapshot association |
| `snapshots.parquet` | Payload identity, source context, format, and source-level metadata |
| `source_features.parquet` | Features measured from the original payload, before content selection |
| `extractions.parquet` | Candidate identity, status, diagnostics, metadata, Markdown, and plain text |
| `blocks.parquet` | Ordered content blocks and structural information |
| `selection.parquet` | Selected candidate or abstention with reasons per snapshot |
| `manifest.json` | Input hashes, schema version, dependency/configuration versions, run totals, timings, failures |

Use bounded batches, worker limits, per-document timeouts, and size limits. One malformed document must not abort the corpus. Explicitly record timeouts and unsupported inputs; never silently truncate successful output.

Cache by payload digest, source URL context, adapter version, configuration, and serialization version. Separate deterministic result content from run-specific timing metadata. Completed work must be resumable without duplicate results.

Derived artifacts remain under the existing ignored `data/` tree. Keep code, evaluation definitions, and compact reports in version control; avoid adding another large corpus export to Git by default.

## Evaluation and acceptance

Use the existing 500-row CSV selection as one inspection source, then supplement it with diverse and difficult snapshots. Deduplicate snapshots for extraction evaluation. Do not confuse row-balanced inspection samples with representative quality estimates.

Manually annotate approximately 100 snapshots: 60 development and 40 held-out, separated by hostname. Cover articles, homepages, products/pricing, documentation, tables, multiple languages, mixed formats, and known extraction or source failures. Reviewers should not see citation labels. Keep selection policy frozen during held-out evaluation.

Annotations identify required source-supported content, unwanted boilerplate, key numerical facts, heading/list/table relationships, and whether the snapshot contains enough information to judge extraction.

Proposed acceptance targets, to freeze before held-out evaluation:

- At least 90% of evaluable held-out pages judged usable without material omissions or misleading structure.
- At least 95% recall of annotated required facts/sections, reported with the actual annotation denominator and by page type where sample sizes permit.
- No observed changed numbers/units or invented factual text in reviewed outputs.
- No observed loss of annotated header-to-cell relationships in supported table fixtures; unsupported structures are flagged.
- Improvement over the current extractor on reviewed quality, with regressions documented by page type.
- Every input record accounted for and every failed/abstained extraction explicitly represented.
- Identical content outputs for identical inputs/configuration and no network activity during preprocessing.

These are engineering gates, not evidence of population-wide accuracy. Report counts and uncertainty; a small held-out set cannot establish a universal “highest fidelity” claim. If a target fails, record the failure rather than retuning on the held-out set and reporting it as untouched evaluation.

## Analysis integration

Recompute source-HTML features separately from extracted-content features. Preserve current v1 results for comparison.

Produce a v1-versus-v2 report covering changes in content length, headings, tables, query coverage, usable sample size, and top/bottom associations. Break down changes by extraction status, label, page type, and language where supported. Keep literal token overlap labeled as such; word counts are not LLM token counts.

An improved parser does not fix query confounding, missing exposure/count data, or conflicting citation labels. Re-run within-host, page-type, quality-filtered, and same-query sensitivity analyses with explicit page/snapshot weighting.

## Reference documentation

- [Trafilatura extraction options](https://trafilatura.readthedocs.io/en/latest/corefunctions.html)
- [Mozilla Readability](https://github.com/mozilla/readability)
- [Turndown and GFM plugins](https://github.com/mixmark-io/turndown)

These tools are benchmark candidates, not guarantees of compatibility with any proprietary search-engine ingestion pipeline.
