# Raw-to-embedding data lineage

The persistent project volume is
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system`.
Extraction and embedding exports are independent versioned runs. Consume the
complete saved markdownify corpus; never reparse HTML to reproduce embeddings.

## The chain

| Stage | Durable artifact | Join / verification |
| --- | --- | --- |
| Original input | `raw/citations_part_00*.parquet` | File SHA-256 and zero-based source row; payload SHA-256 |
| Prepared structured document | `processed/markdownify-corpus-v1-complete/documents/<snapshot_id>.json.gz` | Snapshot ID = hash of payload hash + URL; compressed file checksum and extraction content checksum |
| Ordered structure | Document `blocks` and `chunks` | Block IDs, source locators, ordered chunk partition and extraction run identity |
| Embedding inputs | `representations/runs/markdownify-openai-v1/units.parquet` | Unit ID, serialized text hash, query/document role, block IDs, source chunk IDs and ranges |
| Original vector | `representations/shared-store/embeddings/<model identity>/<shard>.npy` | Semantic request key → shard path, zero-based row and SHA-256 in SQLite |
| Portable run matrix | Run `vectors/<config_id>/vectors.npy` and index | Unit ID → zero-based exported matrix row; exported file checksum |
| Field projection | Run `projections/<projection_id>/pca.npz` and `pca.parquet` | Saved training-only fit; unit ID → coordinates; fit/vector hashes |

`associations.parquet` connects the query unit to every original record and its
snapshot. Duplicate row references remain separate. A query vector can be shared
by several records. Derived page/outline/title units preserve member IDs and
byte weights; their vector is the normalized byte-weighted mean of normalized
members, with no direct API request. Missing views remain explicit.

The `blocks-v3-markdownify` input recipe uses saved `inline_markdown` for new
`dom-blocks-v3` blocks, preserving inline code, deletion markers and hard breaks.
Code blocks retain exact text whitespace. Tables serialize structured cell text,
headers and spans as JSON, rather than treating the convenience table Markdown
as authoritative. H1/title fields are textual labels; outline/page/sections retain
structural context. Images are source metadata/inline text only; no image vectors
are computed. Original structured documents retain richer inline relationships
than a textual embedding input can encode.

New unit identities version the recipe. Original vector reuse is still keyed by
exact text, query/document role and semantic model identity. Therefore unchanged
queries, titles and paths can reuse paid vectors across extraction versions;
changed page/section inputs create new requests. Old vectors, original preprocessing
outputs, fits and reports remain separate.

## Split provenance

The markdownify export contains original rows but no scorer splits. Preparation
joins the previous completed retention embedding run by raw file hash/source row,
then verifies URL, payload hash, query, hostname and label before carrying its
split and exclusions forward. The reference association checksum is recorded.
Training fits omit mixed-split source units and exact held-out content. The old
benchmark split is reused; this is not a fresh independent holdout or a relevance
evaluation. Independent field PCA bases cannot support cross-field cosine.

## Published tracker

`lineage/index.html` on the persistent project volume is the full searchable tracker
for the latest completed run. `lineage/registry.json` records versioned run pointers.
Each run keeps its own `lineage/manifest.json`, `records.parquet`, `units.parquet`,
and `tracker.html`. The record table resolves raw/document associations; the unit
table resolves every embedding request, shard row, exported row, pool member and
projection field. The manifest names exact join keys and checksums.

Git contains the bounded tracker sample and compact summary at
`analysis/data-lineage-markdownify-openai.html` and `.json`. Full source data,
vectors, documents and unit-level lineage remain outside Git. Publication verifies
raw sources, prepared artifact/document checksums, input/run checksums, and every
referenced original vector shard. Mechanical integrity does not establish human
semantic correctness or citation uplift.

## Reproduction

```sh
uv run --offline python -m representations prepare \
  --input data/processed/markdownify-corpus-v1-complete \
  --raw-root data/raw \
  --split-reference data/representations/runs/retention-full-v1 \
  --config data/representations/retention-full-config.json \
  --output data/representations/runs/<new-versioned-run>

uv run --offline python -m representations embed \
  --run data/representations/runs/<new-versioned-run> --model openai-large --resume

uv run --offline python -m representations finish-corpus \
  --run data/representations/runs/<new-versioned-run> --model openai-large \
  --summary-output analysis/<new-versioned-summary>.json \
  --lineage-output analysis/<new-versioned-tracker>.html
```

Preparation verifies existing outputs without extraction. Inference reuses durable
cached vectors. `finish-corpus` makes seven separate 32D training fits, exports the
feature bundle, and publishes evidence/lineage without API calls. Resume inference
against its frozen prepared inputs; never change an active run's configuration.
