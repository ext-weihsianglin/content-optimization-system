# Embedding representations specification

Status: Core pipeline implemented; reviewed model selection and full-corpus execution pending

Date: 2026-10-01

Implementation plan: [../plan/embedding-representations.md](../plan/embedding-representations.md)

Discussion page: [../analysis/embedding-plan-discussion.html](../analysis/embedding-plan-discussion.html)

Upstream contract: [Snapshot preprocessing PR #1](https://github.com/ext-weihsianglin/content-optimization-system/pull/1)

## Objective and selected direction

Extend the parsed structural record with traceable textual embeddings and query-conditioned features for exploratory citation analysis. Preserve original vectors and add PCA representations and an interactive UMAP map. Compare hosted embedding models on a reviewed sample before choosing the corpus model. Subsequent user steering adds OpenAI because local GPU capacity is limited; local embedding inference is not required.

The user's October 1 feedback selects citation-analysis features, a two-model sample comparison, query/title/outline/section/page views, alignment features, PCA, and UMAP. It additionally requests URL-path embeddings, such as `journal / running-shoes` from `https://stride.example/journal/running-shoes`. Learned text–structure fusion is deferred. Product-image embeddings are a subsequent stage, with extension points defined here.

Embeddings measure semantic relationships, not factual correctness, answer completeness, or causal citation uplift. Top/bottom labels are relative within a hostname and are not query–passage relevance annotations.

## Scope and boundaries

In scope:

- Consume versioned offline preprocessing artifacts without re-extracting HTML.
- Produce deterministic embedding inputs for six view families.
- Compare OpenAI Text Embedding 3 Large, Voyage 4 Large, and optionally hosted Qwen3 Embedding 8B using the same input units and evaluation protocol.
- Batch external embedding requests with caching, retries, resume, explicit failure handling, and source traceability.
- Derive query alignment, PCA features, and an interactive semantic map.
- Evaluate incremental predictive value over structural features and sensitivity to extraction quality.

Out of scope:

- Changing extractor selection, reparsing HTML, live page fetching, or repairing missing source content.
- Fetching product images, visual embedding execution, OCR, generated captions, or screenshot reconstruction.
- Learned multimodal fusion, neural projection training, content generation, and production serving/vector databases.
- Claims of citation uplift or an embedding model being universally best.

The representation runner may contact the configured embedding service. The upstream preprocessing command remains offline. Python setup and execution use `uv`; secrets come from environment variables and are excluded from artifacts and logs.

## Upstream inputs and identity

Integration checkpoint after PR #2: the adapter consumes its shared `data/trad_ml_scorer/v2` cache (`records.jsonl`, manifest, and compressed `downstream-document-v1` documents). It validates document identities, block trees, ordered source-chunk partitions, and raw-file provenance without reading/parsing HTML again. Both `selected` and retained `needs_review` content are projected; quality flags stay visible. Title comes from source metadata; H1/outline/body come from retained blocks; sections follow saved chunks with heading ancestry. `source_chunk_ids` survive further byte-budget splitting and alignment. Original scorer record IDs, exclusions, and hostname split assignments remain provenance; original file-hash/row identities distinguish exact duplicate rows. The older `eval-v2` adapter and historical smoke remain supported. Serializer `blocks-v2` invalidates earlier caches for the new representation contract.

Read `records.parquet`, `snapshots.parquet`, `source_features.parquet`, `extractions.parquet`, `blocks.parquet`, `selection.parquet`, and `manifest.json` under `data/processed/<run_id>/`.

Use an adapter at the boundary to resolve the upstream schema's exact column names. Validate its schema version, hashes, IDs, joins, selected candidate identity, ordered blocks, and cardinalities. Reject incompatible schemas before API work. Do not invent an upstream column contract beyond PR #1.

- Citation records retain original prompts, labels, hostnames, URLs, and snapshot associations.
- Snapshots preserve payload digest and exact URL context; different snapshots for a URL remain distinct.
- Selected extraction identity includes adapter/configuration/serialization versions.
- Only `selected` outputs enter the default run. Other statuses remain accounted for with exclusion reasons; optional sensitivity runs must explicitly name alternative candidates.
- Labels and prompts do not enter page-content serializers. URLs enter only the separate URL-path view. Hostnames remain grouping/provenance fields, never semantic inputs.

Separate logical units from embedding requests. A logical unit identifies its snapshot/extraction/view/block contributors; identical exact text under identical model configuration may reuse one cached vector without collapsing provenance or citation associations. Query units may similarly reuse requests while preserving each original record association.

## Textual view contract

| View family | Input | Required distinctions |
| --- | --- | --- |
| Query | Original nonblank prompt | Preserve original text; blank/whitespace-only prompts are unavailable, not embedded placeholders |
| Title | Source document title and visible H1 | Separate subviews; retain all visible H1s with stable block IDs; missing fields remain missing |
| Outline | Ordered heading levels and texts | Preserve hierarchy, duplicate headings, and source order |
| Section | Heading ancestry plus ordered source blocks | Retain contributing block IDs, ancestry, and chunk positions |
| Page | Faithful serialization of selected content | Preserve source content; explicit long-input policy |
| URL path | Normalized path segments | Separate from content and metadata embeddings |

Source metadata not present in visible body text must not be inserted into body/page inputs. Existing image alt text may remain source content; do not create image descriptions. Stable serializer templates and whitespace rules are versioned. Preserve code whitespace and nested lists. Serialize tables with explicit header/cell relationships and span handling rather than flattening them into misleading GFM. Unsupported structures receive diagnostics.

### Section splitting and long inputs

Create sections from heading hierarchy, including a preamble for content before the first heading. The first implementation uses a conservative 4,096-byte UTF-8 chunk ceiling, no overlap, and heading ancestry repeated as context. Preserve block contributors and record ranges within the normalized serialization. These are derived-text ranges, not invented source offsets. Whitespace boundaries are preferred when splitting oversized serialized inputs; exact source text is retained across chunks.

Byte ceilings are labeled as bytes, not token counts, and leave headroom below the shortest candidate context, including instructions. They avoid downloading model/tokenizer weights. Endpoint preflight must still verify the provider's actual behavior. Freeze common chunks before model comparison; chunk size is an initial experiment configuration, not a claim of an optimal retrieval size.

Full-page inputs up to 7,000 bytes are embedded directly. For oversized pages, persist embeddings of all ordered page chunks and produce a separately marked, content-byte-weighted pooled page vector, followed by L2 normalization. Do not combine section vectors that repeat heading ancestry as if they were an unbiased full page. Label direct versus pooled page representations and report their sensitivity. Apply explicit chunking to oversized outlines/titles/paths as well; unsupported cases may abstain. Never silently truncate.

### URL-path normalization

Parse the exact source URL locally. For `https://stride.example/journal/running-shoes`, derive `journal / running shoes`, while retaining both the raw path and segment list.

1. Require a parseable absolute HTTP(S) URL with hostname; mark malformed/unsupported URLs unavailable.
2. Remove authority, query string, and fragment from the embedding input.
3. Split the raw path on literal `/` before percent-decoding each segment. Preserve encoded slash characters inside their original segment; do not reinterpret them as hierarchy.
4. Decode percent-encoded UTF-8 once; flag invalid escapes/encoding instead of silently substituting characters. A `+` in a path is literal, not form-encoded space.
5. Replace hyphens/underscores with spaces, collapse whitespace, retain Unicode and segment order, and join nonempty segments with ` / `.
6. Preserve numeric/opaque segments and file extensions initially; annotate them for sensitivity analysis rather than guessing what to remove.

Root-only paths have no semantic input. Keep query–path similarity missing rather than assigning zero. Store the normalizer version, raw path, normalized text, and diagnostics. Embed the path in document mode independently of page content. Evaluate path features both alone and as an addition to content/structure; they may encode page purpose or topic confounding.

## Model and provider contract

Initial candidates, verified during planning on October 1, 2026:

| Model | Initial configuration | Input roles |
| --- | --- | --- |
| OpenAI Text Embedding 3 Large | 3,072 dimensions, float output; documented 8,192-token context | Same model/interface for query and document; no invented role parameter |
| Voyage 4 Large | 2,048 dimensions, float output; documented 32,000-token context | Query for prompts; document for textual page views |
| Qwen3 Embedding 8B | 4,096 dimensions, float output; documented 32K context | Versioned retrieval instruction for queries; documented document format |

These are hosted candidates, not a quality ranking or a local GPU requirement. OpenAI is the initial execution baseline because a configured API key is available; selection still requires reviewed relevance evidence. Price is not the selection criterion. A provider adapter exposes input limits, batch limits, dimension support, query/document formatting, and any truncation controls. Pin the provider route when using OpenRouter; unsupported role/dimension/instruction behavior cannot be silently ignored.

Persist model ID, provider/endpoint identity, revision when exposed, requested/actual dimension, input role, exact instruction/template version, normalization, and creation time. Different model spaces never share cosine computations, PCA models, or UMAP coordinates. Reusing a model name across provider revisions requires an explicit cache policy; do not assume the serving weights are immutable.

Disable truncation where supported and validate lengths beforehand. Validate response indexing/cardinality, finite numeric values, expected dimension, and nonzero norm. Store float32 original vectors and derive L2-normalized vectors for cosine operations. Reject invalid vectors without pretending that missing results are zeros.

## Query-conditioned features

Compute similarities in the original normalized embedding space using matching model/configuration roles. Retain:

- Query–document-title and query–H1 similarities separately.
- Query–outline, query–page, and query–URL-path similarity.
- Maximum section similarity and top-three section mean, using the available count when fewer than three exist.
- Section similarity quantiles, section/chunk counts, and the best section/chunk IDs with contributing blocks.

Report that maximum similarity is affected by page/chunk count. Do not apply uncalibrated thresholds to call a section “covered.” Missing views receive nullable values plus status/reason fields. A vector or feature is not a label score.

Derive alignment per record–snapshot–extraction association, allowing cache reuse for repeated prompts. Do not automatically resolve conflicting labels or select the longest snapshot. Downstream weighting and exclusion policy must be explicit so repeated rows/snapshots do not overweight pages or hosts.

## Projection and semantic map

### PCA

Provide fit/save/apply for each model and view family. Start with candidate dimensions 32, 64, and 128 where sample rank permits. Choose dimensions on development/training data and record explained variance, centering, normalization, seed, training IDs, and dependency versions. Do not whiten by default. Page and path projections stay separate.

For predictive evaluation, fit PCA and all learned preprocessing inside training folds and transform held-out units. Do not calculate query–document cosine using independently fitted PCA spaces. Original embeddings remain available for later projections.

### UMAP explorer

Deliver an offline HTML explorer with selectable model/view, label/hostname/quality filters, and point selection showing exact URL, prompt associations, extraction status, textual input, and supporting blocks. Precompute neighbors in the original embedding space; screen distance alone is not semantic evidence. Escape source-derived content and do not load source assets or execute source HTML.

Create separate maps for page, query, and URL-path views initially. Query-to-page navigation uses stored original-space matches instead of placing separately fitted query/document maps into a fictitious shared coordinate system. Fix seeds/configurations and record neighborhood-preservation diagnostics. An all-corpus exploratory map is explicitly labeled as such and must not be reused as a held-out predictive feature.

## Artifacts, caching, and operations

Write under the ignored `data/representations/<run_id>/` tree:

| Artifact | Contents |
| --- | --- |
| `units.parquet` | Logical unit ID, view/subview, exact text/hash, provenance, contributors, status, token counts |
| `associations.parquet` | Citation record, prompt unit, snapshot/extraction and view-unit references |
| `vectors/<model_config_id>/` | Float32 arrays with explicit request/unit index and checksums |
| `alignment.parquet` | Model/configuration and association-keyed nullable features, reasons, supporting unit IDs |
| `projections/` | PCA fit artifacts, fit IDs, transforms, UMAP coordinates/configuration, diagnostics |
| `failures.parquet` | Stage, unit/request identity, reason, attempts, retryability; no credentials |
| `manifest.json` | Upstream hashes, schema/configuration/version identity, coverage, exclusions, dimensions, usage, timings |

Embedding cache keys include exact input hash, model/provider configuration, role/instruction, dimensions/output type, and serializer/normalizer identity. Projection caches include vector artifact hashes and projection fit/configuration identity. Keep deterministic content separate from timestamps and timings.

Use bounded batch sizes, concurrency, token budgets, timeouts, exponential backoff for transient failures, and atomic writes/checkpoints. Authentication/configuration failures stop the job clearly; malformed inputs isolate per unit. Every intended unit ends in success, explicit missing/excluded, or failed status. Resume must not duplicate associations or redo completed compatible requests. API responses may vary across service revisions; resumability is not a promise of bitwise vendor reproducibility.

## Evaluation and acceptance

Freeze a hostname-separated development/held-out relevance manifest before tuning. Sample diverse languages, page purposes, lengths, extraction statuses, and relevant/unrelated query–section pairs. Review relevance independently of top/bottom labels. Citation-associated pages may still lack an answer in the stored snapshot.

Compare models using identical units and judged candidate pools, ranking graded relevance within the pool. Report nDCG@5 and Recall@5 against annotated relevant units in that pool, denominators, uncertainty, and language/page-type breakdowns. State that sampled-pool recall does not establish whole-corpus recall. Use development data for chunk/instruction tuning; freeze configuration before holdout. Choose the winner by relevance evidence; predeclare a tie policy instead of selecting by favorable top/bottom separation.

Evaluate structure-only, path-only, alignment-only, and combined regularized predictive baselines with hostname-held-out splits. Audit shared payload/text hashes across splits; keep connected duplicate groups together or explicitly exclude cross-split duplicates. Report ROC-AUC, PR-AUC, within-host ranking, and host-level uncertainty, with explicit snapshot/page weighting and label-conflict handling. Predictive value and causal editing benefit remain distinct.

Acceptance gates:

- All source citation records are accounted for; selected/excluded/failed units and associations reconcile.
- Inputs are deterministic for a fixed upstream extraction/configuration and remain unchanged when only citation labels change.
- URL paths satisfy the normalization examples and edge-case fixtures.
- All successful vectors are finite, nonzero, correctly indexed, and dimension-compatible; no silent truncation.
- Resume equivalence, cache invalidation, provider errors, and missing views are verified.
- Reviewed model comparison and the frozen corpus configuration are recorded, including ties or inadequate evidence.
- PCA fit provenance proves held-out data did not enter predictive transforms; maps are clearly exploratory.
- The explorer displays source-backed details and reports coverage/limitations without claiming citation uplift.

No predictive improvement threshold is asserted in advance. A null or negative result is a valid outcome and must be reported.

## Visual extension contract

Reserve `modality`, `asset_id`, `product_entity_id`, and optional asset hash/provenance references in logical units. No image bytes or vectors are required in this stage. Missing images remain missing, not zero vectors. Later asset acquisition needs a separate policy because upstream records contain image references, not necessarily historical image binaries. A current image fetched later must not be presented as proven historical snapshot content.

Image vectors may join by verified snapshot/product identity. Only a documented shared-space multimodal model allows direct text/image comparison. A separate visual model requires separate projections and a later fusion strategy; equal dimensions do not imply compatible coordinates.

## References

- [OpenRouter shortlist and its evaluation limitations](https://openrouter.ai/blog/insights/best-embedding-models-2026/)
- [Voyage embedding models, roles, and limits](https://docs.voyageai.com/docs/embeddings)
- [Qwen3 Embedding 8B model card and input instructions](https://huggingface.co/Qwen/Qwen3-Embedding-8B)
- [Official OpenAI embedding guide](https://developers.openai.com/api/docs/guides/embeddings)

Check chosen endpoint capabilities before corpus execution. The model comparison determines fitness for this dataset.

## Shared persistence and current execution scope

See [embedding-storage.md](embedding-storage.md) for immutable sharded vectors, SQLite lookup/job coordination, stable semantic identity, legacy migration, recovery and backup. The current user-directed scope is OpenAI API plus local Voyage nano on MLX; Voyage large is deferred because local weights are not published, and Qwen-8B is deferred. Original-space vectors remain available for repeated projection and evaluation without new inference.
