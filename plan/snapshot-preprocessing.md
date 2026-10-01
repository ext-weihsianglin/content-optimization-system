# Snapshot preprocessing implementation plan

Status: Draft; no preprocessing implementation changes included

Date: 2026-10-01

Specification: [../spec/snapshot-preprocessing.md](../spec/snapshot-preprocessing.md)

## Outcome and boundaries

Deliver an offline, evaluated preprocessing pipeline for the existing parquet snapshots, followed by a report showing how improved extraction changes the analysis.

No browser rendering, JavaScript execution, live fetches, remote asset loading, external extraction APIs, snapshot refreshes, or dynamic web-document indexes. Missing source content remains missing and is flagged.

## Milestone 1 — Contracts and evaluation set

Tasks:

- Establish source record, payload, and snapshot IDs and a versioned output schema.
- Preserve existing extraction code and analysis outputs as the v1 baseline.
- Inventory payload formats, multiple snapshots, and ambiguous source cases without altering raw files.
- Create a deterministic evaluation manifest from the existing sample plus targeted difficult cases.
- Select approximately 100 distinct snapshots; split 60 development / 40 held-out by hostname and hide citation labels during review.
- Define annotation instructions and freeze the evaluation metrics before tuning.

Deliverables:

- `preprocessing/schema.py` and `preprocessing/config.py`.
- `evaluation/extraction/manifest.json` and `evaluation/extraction/rubric.md`.
- Development/held-out assignments, source hashes, sampling rationale, and a record of coverage gaps.

Exit gate: Every selected example resolves to its exact saved payload; duplicate handling and the annotation rubric are unambiguous.

## Milestone 2 — Local adapters and comparison viewer

Tasks:

- Add `uv`-managed Python extraction dependencies and a locked Node adapter package.
- Implement format detection and metadata/source-feature extraction before destructive cleanup.
- Implement the baseline, Trafilatura, Readability, and Markdown/text adapters behind one contract.
- Implement a bounded conservative DOM candidate for multi-section/non-article pages.
- Preserve blocks and serialize Markdown/plain text; handle complex tables without silently losing relationships.
- Build an offline HTML comparison viewer showing source text/markup, candidate outputs, diagnostics, and annotation fields or a companion annotation file.
- Keep raw markup escaped; any preview HTML must be sanitized and unable to load assets or execute scripts. A comparison viewer is not a rendering-based extractor.

Deliverables:

- `preprocessing/adapters/` and `preprocessing/node/`.
- `preprocessing/blocks.py`, `preprocessing/serialize.py`, and `preprocessing/quality.py`.
- `scripts/compare_extractions.py` and `analysis/extraction-comparison.html`.

Exit gate: Reviewers can inspect the same saved input across candidates. Structured fixtures retain their required facts and relationships. Preprocessing works with network access disabled.

## Milestone 3 — Review, selection policy, and held-out evaluation

Tasks:

- Annotate the 60 development snapshots without citation labels.
- Measure omissions, boilerplate, factual fidelity, structural preservation, and failure handling by page type.
- Use disagreements to identify defects and establish a deterministic candidate-selection policy.
- Add `needs_review`, `source_insufficient`, and unsupported-format handling instead of forcing successful output.
- Freeze versions/configuration and evaluate on the 40 held-out snapshots.
- Report denominators, observed regressions, and uncertainty. If further tuning is necessary, explicitly retire the used holdout and define a new evaluation set.

Deliverables:

- `preprocessing/select.py`.
- Reviewed annotations and `analysis/extraction-evaluation.json`.
- A candidate comparison and rationale for the selected policy, including page types where no candidate is adequate.

Exit gate: Meet the proposed acceptance criteria in the spec, or explicitly document failed criteria and narrow the supported scope. Do not choose a winner using top/bottom separation or query overlap.

## Milestone 4 — Resumable corpus preprocessing

Tasks:

- Add a CLI that reads parquet in bounded batches and processes distinct snapshots.
- Add caching, deterministic IDs, bounded workers, per-document limits, and a failure ledger.
- Reuse a persistent Node worker or worker pool rather than one process per document.
- Preserve all record associations and multiple snapshots; do not pick the longest payload.
- Validate joins, schema, source hashes, output cardinalities, resumability, and deterministic content results.
- Run the frozen pipeline across the corpus and summarize quality/abstention rates by input format and citation label after extraction completes.

Proposed command interface:

```sh
uv run python -m preprocessing run \
  --input 'data/raw/*.parquet' \
  --output data/processed/<run_id> \
  --config preprocessing/config.json \
  --resume
```

Use `.tools/uv` when `uv` is not on PATH. This command is a planned interface, not an existing executable.

Exit gate: Every citation record maps to a preserved snapshot, each attempted candidate has an outcome, and rerunning does not duplicate work or change deterministic outputs.

## Milestone 5 — Feature migration and evidence reassessment

Tasks:

- Update feature calculation to consume the new preprocessing outputs instead of reparsing HTML independently.
- Keep source-DOM and extracted-content feature namespaces separate.
- Define explicit analytical handling for multiple snapshots, repeated pages, and conflicting labels.
- Rerun broad, within-host, editorial/page-type, quality-filtered, and same-query comparisons.
- Measure sensitivity to the chosen extractor and alternative candidates.
- Update the HTML report with v1/v2 differences and source-backed examples of corrected or unresolved extraction.
- Document which earlier findings remain supported and which require revision.

Deliverables:

- Versioned v2 feature and analysis artifacts.
- `analysis/preprocessing-impact.html` with links to machine-readable summaries.
- README instructions covering setup, preprocessing, evaluation, and reproduction.

Exit gate: Report sample-size changes and parser-dependent conclusions explicitly. Do not overwrite the original findings without preserving their version and methodology.

## Verification work

Introduce meaningful tests for the new preprocessing layer:

- Format routing: HTML, Markdown, plain text, mixed/unknown payloads, and misleading URL suffixes.
- Structural fixtures: multiple articles, product sections, nested lists, code, complex tables, relative links, and Unicode text.
- Metadata: JSON-LD before script removal; invalid JSON handled without losing otherwise valid content.
- Content loss: headers/footers containing useful material, tiny misleading semantic containers, and useful content outside `main`.
- Source limitations: script shells and error pages remain flagged rather than fabricated or repaired by fetching.
- Provenance: identical payload at different URLs, multiple snapshots per URL, duplicate citation rows, conflicting labels, and missing prompts.
- Isolation: network-disabled execution, no source script execution, and escaped/sanitized report output.
- Operations: timeout/error isolation, cache invalidation, resume equivalence, and repeat-run determinism.
- Independence: changing prompts or citation labels does not change extraction or selection results for the same snapshot.

## Sequencing and effort

Milestone 1 precedes adapter tuning. The comparison viewer can be built alongside the adapters once the contract is stable. Corpus execution follows the evaluation gate; analysis migration follows a validated corpus run.

Planning estimate: 3–5 engineering days, plus approximately half to one day of focused human review. Actual duration depends on failures found in non-article pages, complex tables, and multilingual examples. Measure throughput during the benchmark before estimating the full corpus run.

If trial time is shorter, finish Milestones 1–3 on the evaluation set and deliver a measured comparison. A bounded, reviewed result is preferable to presenting an unvalidated full-corpus conversion as high fidelity.

## Decisions to settle from evidence

- Which candidate or selection policy works best for each supported page type?
- When should a document be marked for review rather than automatically selected?
- Which Markdown structures require an HTML/structured fallback?
- How should analysis summarize multiple valid snapshots without overweighting a URL?
- Which earlier citation associations survive extractor changes?

These decisions use snapshot evidence and development annotations. They do not require live fetching, browser rendering, or a web index.
