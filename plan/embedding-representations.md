# Embedding representations implementation plan

Status: Core CLI implemented and offline integration tests passing; reviewed comparison and corpus execution pending

Date: 2026-10-01

Specification: [../spec/embedding-representations.md](../spec/embedding-representations.md)

Discussion: [../analysis/embedding-plan-discussion.html](../analysis/embedding-plan-discussion.html)

## Outcome and sequencing

Build a representation pipeline on the parsed structural output from [PR #1](https://github.com/ext-weihsianglin/content-optimization-system/pull/1). Deliver six textual view families, a reviewed hosted-model comparison, a resumable corpus embedding run, query alignment, PCA features, and an interactive UMAP explorer. Include URL-path features requested in the user's feedback. OpenAI Text Embedding 3 Large is the initial hosted baseline; compare Voyage and optionally hosted Qwen when credentials/review evidence are available. No local GPU inference is required. Defer learned fusion and image execution.

Work on schema adapters, fixtures, and the runner can begin before upstream corpus artifacts exist. The full run depends on a validated preprocessing manifest and selected extraction outputs. Do not bypass that dependency by independently reparsing HTML.

## Milestone 1 — Contracts, textual units, and evaluation manifest

Tasks:

- Establish upstream compatibility checks and snapshot/extraction/record joins.
- Define logical unit, request, vector configuration, association, and status schemas.
- Serialize query, title/H1, outline, sections, full page, and URL path separately.
- Add versioned URL normalization and structure-aware chunking, including long-page pooling identity and missing views.
- Inspect exact input texts with source block contributors in a dry-run report.
- Create a deterministic evaluation manifest targeting approximately 120 query–snapshot cases: 60 development and 60 held-out, separated by hostname and audited for duplicate content. Review workload and coverage may justify a documented adjustment before freezing.
- Establish graded query–section relevance annotations, candidate-pool construction, model comparison metrics, tie policy, and human review instructions. Hide citation labels during relevance review.

Deliverables:

- `representations/contracts.py`, `representations/config.py`, `representations/upstream.py`.
- `representations/inputs.py`, `representations/chunking.py`, `representations/url_path.py`.
- Structural/input fixtures and `evaluation/embeddings/manifest.json`, `rubric.md`.
- An inspectable dry-run input report with exclusions and provenance.

Exit gate: All example units resolve to exact selected extractions and source blocks. Six view families and missing cases are inspectable. No API calls are needed to validate deterministic input generation.

## Milestone 2 — Provider preflight and resumable embedding runner

Tasks:

- Add minimal `uv`-managed dependencies for arrays/parquet, HTTP/provider access, projections, and meaningful tests; lock versions.
- Implement OpenAI and Voyage direct adapters and a pinned OpenRouter adapter for hosted Qwen. Inspect actual endpoint capability before execution.
- Verify roles/instructions, conservative byte ceilings, dimensions, batch limits, provider pinning, and truncation controls. Do not label bytes as token counts.
- Freeze identical chunk texts fitting both candidates, with explicit instruction overhead.
- Implement request-level content-addressed caching while preserving logical provenance.
- Add bounded batching/concurrency, transient retries, authentication/configuration stop behavior, failure ledger, and atomic resume checkpoints.
- Validate vector dimensions, finite values, norms, response indices, and usage accounting.

Deliverables:

- `representations/providers/`, `representations/cache.py`, `representations/runner.py`.
- `representations/__main__.py` and planned `prepare` / `embed` commands.
- Capability report and manifest format; offline fake-provider tests.

Exit gate: A small real-service smoke test confirms configured semantics. Offline tests prove out-of-order response handling, failure isolation, invalid-vector rejection, resume equivalence, and cache invalidation. No credentials are recorded.

## Milestone 3 — Reviewed model comparison and configuration freeze

Tasks:

- Embed identical development units with OpenAI Text Embedding 3 Large (3,072 dimensions), Voyage 4 Large (2,048 dimensions), and optionally hosted Qwen3 Embedding 8B (4,096 dimensions).
- Build identical judged section pools including relevant and unrelated candidates; inspect failures and missing source answers.
- Annotate graded relevance and compare nDCG@5, sampled-pool Recall@5, coverage, and uncertainty.
- Tune chunk size/query instructions only using development evidence; version each change.
- Freeze serializers, inputs, model configuration, metrics, and tie policy; evaluate the untouched holdout.
- Select a corpus model based on relevance evidence, not citation-label separation. If evidence is insufficient, report that explicitly and retain the predeclared default rather than claiming superiority.

Deliverables:

- `representations/evaluation.py` and reviewed annotations.
- `analysis/embedding-model-comparison.json` and a compact HTML comparison.
- Frozen representation configuration and rationale.

Exit gate: Model selection is reviewable with exact inputs, judged-pool denominators, slice coverage, failures, and limitations. Do not reuse a tuned-on holdout as untouched evidence.

## Milestone 4 — Corpus run and semantic alignment

Tasks:

- Process selected distinct snapshots, preserving multiple snapshots and all original record associations.
- Embed deduplicated compatible requests while retaining all logical unit provenance.
- Build direct/pooled page vectors and compute alignment in the original normalized model space.
- Add query–path similarity and nullable missing-view statuses alongside title, H1, outline, page, and section features.
- Store top matching unit/block IDs and section-count diagnostics.
- Reconcile inputs, units, requests, vectors, associations, exclusions, and failures.
- Perform an interrupted/resumed run check and summarize coverage by language/page type/extraction status; inspect label breakdowns only after the representation configuration is frozen.

Deliverables:

- `representations/alignment.py`; pooled vectors use explicit UTF-8-byte weights in the first implementation.
- Versioned corpus artifacts under `data/representations/<run_id>/`.
- A compact coverage/provenance report and reproduction instructions.

Exit gate: Every original citation record is accounted for; every intended embedding unit has a terminal status; joins and checksums reconcile; no silent truncation or duplicate work appears on resume.

## Milestone 5 — PCA, downstream comparisons, and UMAP explorer

Tasks:

- Implement per-model/per-view PCA fit/save/apply with recorded fit IDs, centering, normalization, and variance diagnostics.
- Compare 32/64/128 components where supported using training/development evidence.
- Evaluate structure-only, path-only, alignment-only, and combined regularized baselines with hostname-held-out folds.
- Audit cross-fold duplicate payloads/text and keep connected duplicate groups together or document exclusions. Fit all learned transforms and imputers within training folds.
- Specify repeated-page/snapshot weighting and conflicting-label handling; report host-level uncertainty and same-query/extractor-quality sensitivity where sample sizes permit.
- Precompute separate page/query/path UMAP maps and original-space nearest neighbors. Record seed/configuration and neighborhood diagnostics.
- Build an offline explorer with model/view selection, filters, point detail, source excerpts, and query-to-page navigation via original-space matches.
- Escape all source text, keep source assets unloaded, and label all-corpus maps as exploratory.

Deliverables:

- `representations/projection.py` and `representations/analysis.py`.
- `scripts/build_embedding_report.py`, versioned machine-readable evaluation summaries.
- `analysis/embedding-explorer.html` and README reproduction instructions.

Exit gate: Held-out transforms have verifiable training provenance. The explorer exposes source-backed evidence and exclusions. Incremental value, null results, and confounding are reported accurately; no uplift claim follows from predictive separation.

## Proposed command surface

These interfaces are implemented; additional review/evaluation/analysis commands are documented in the README:

```sh
uv run python -m representations prepare \
  --input data/processed/<preprocessing_run_id> \
  --output data/representations/<run_id> \
  --config representations/config.json

uv run python -m representations embed \
  --run data/representations/<run_id> --resume

uv run python -m representations align \
  --run data/representations/<run_id>

uv run python -m representations project \
  --run data/representations/<run_id> \
  --fit-manifest evaluation/embeddings/<fit_manifest>.json

uv run python scripts/build_embedding_report.py \
  --run data/representations/<run_id>
```

Use `.tools/uv` if `uv` is unavailable on PATH. Evaluation runs use explicit model configurations and split manifests; exploratory projections use separately labeled fit manifests. Do not commit corpus vectors, API keys, or raw corpus exports.

## Verification requirements

- Upstream schema mismatch, missing selected extraction, broken joins, multiple snapshots, repeated records, and label conflicts.
- Heading ancestry, preamble sections, nested lists, Unicode, tables with spans, code whitespace, oversized blocks/pages, and unavailable views.
- URL paths: root, trailing/repeated slash, hyphen/underscore, UTF-8 escaping, encoded slash, literal plus, query/fragment removal, opaque IDs, unsupported schemes, and malformed encoding.
- Independence: citation-label changes do not alter embedding inputs; changing a query changes its alignment association but not page vectors.
- Providers: out-of-order/missing/duplicate indices, dimension mismatch, nonfinite/zero vectors, throttling, transient failures, and fatal credentials/configuration errors.
- Cache: model/provider/instruction/dimension/serializer/normalizer changes invalidate incompatible entries; identical texts reuse requests while associations remain intact.
- Resume: interrupted writes cannot be treated as complete; completed requests and association counts reconcile after restart.
- Alignment: known-vector fixtures verify similarities, missing-value handling, and top-section identities.
- Projections: fit-ID isolation, compatible view/model application, saved-transform reproducibility, and original-space neighbor use.
- Explorer: source escaping, unavailable states, narrow-screen layout, keyboard-operable filters and selection, no source asset fetching or script execution.

## Dependencies, risks, and deferred work

Corpus execution requires validated upstream artifacts, configured credentials, endpoint capabilities, and reviewed relevance annotations. Measure units/tokens and service throughput after preparation; approximately 9K pages can produce substantially more section requests.

The evaluation review and upstream extraction readiness may dominate elapsed time. Do not prescribe a confident duration before the dry run and review workload are known. If time is constrained, finish the contracts, runner, and reviewed model comparison as the first useful deliverable; do not present an unreviewed full-corpus run as validated.

URL-path similarity can reflect taxonomy or page purpose. Long-page pooling may lose local distinctions, and more sections increase the chance of a high maximum match. Record these sensitivities rather than treating them as universal content-editing rules.

Reserve modality/asset/product references now. Product-image acquisition, historical provenance, image model comparison, and visual projection/fusion require a subsequent specification. No image execution or learned fusion is part of these milestones.

## PR #2 shared-corpus integration

Completed the saved `downstream-document-v1` adapter: consume shared compressed documents and records without rerunning parsing; preserve original source chunks, quality flags, duplicate-row provenance, exclusions, and scorer splits. Full-corpus input serialization and a bounded hosted OpenAI alignment/PCA/UMAP smoke validate integration. Full-corpus API execution, human relevance/model comparison, and visual embeddings remain separate next steps. Existing grouped ablation analysis is exploratory cross-validation; it does not reproduce the scorer's frozen train/validation/test experiment.

## Shared storage and whole-corpus sizing

Implemented stable semantic cache identities, shared SQLite/shards, immutable batch publication, writer exclusion with cached readers, legacy migration, orphan recovery, portable backups and disk-backed run exports. Default model scope is now OpenAI API and locally pinned Voyage nano/MLX. Full-corpus sizing uses model tokenizers; local nano throughput is measured separately from corpus-scale estimates. Only the new inference job contributes new API usage; changing projections or runner batch settings reuses vectors.

## OpenAI corpus postprocessing checkpoint

Completed full-corpus alignment plus seven separate 32D training-only field fits
and transformed coordinates. Document title and H1 now have independent subview
fits. Source split/exclusion/duplicate provenance accompanies each fit. Original
vectors are lazily loaded, and large fits use seeded randomized SVD. Named package
references and the compact corpus summary are available; 32D is a baseline, not
a validated optimum. MLX continues independently.
