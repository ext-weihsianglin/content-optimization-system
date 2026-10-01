# Shared embedding storage

Use the saved PR #2 documents and frozen input parquets. Original embeddings are
immutable shared assets; alignment, PCA, UMAP and run exports are derived artifacts.
No vector database or remote inference server is required for storage.

## Identity and reuse

A request key hashes exact input text, query/document role and semantic model
configuration: provider/endpoint or local backend, checkpoint/revision, dimensions,
instructions, provider routing, and precision. Operational batching, concurrency,
retry count, timeout, credential variable name, local model directory and memory
limits do not invalidate vectors. Serializer/normalizer versions remain input
provenance; a changed exact text creates a different embedding key. Model aliases
cannot guarantee provider-side immutability; revision namespaces express our frozen
execution choice, not an invented upstream snapshot guarantee.

The persistent project root on this machine is
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system`.
It holds raw inputs, prepared documents/features/splits/models, embedding inputs,
original vectors, projection fits/coordinates, reports, and interrupted-job caches.
Both the main checkout and this embedding worktree have a `data` symlink to it;
historical artifact paths remain valid without rewriting frozen manifests.

Default store is `<persistent project root>/representations/shared-store`.
`CONTENT_OPTIMIZATION_DATA_ROOT` overrides the project root. Otherwise Git's common
directory discovers `<main checkout parent>/data/<repository name>` when present,
falling back to `<main checkout>/data` on other machines. Override just the cache with `EMBEDDING_CACHE_ROOT` or
`embed --cache-root`. SQLite coordinates lookups, model configurations, job history,
and inference usage. Per-model filesystem locks prevent overlapping writers from
issuing duplicate requests. Fully cached readers can export during another job.
Different model namespaces may run concurrently. Keep this store on a local disk;
SQLite WAL/flock is not a distributed coordinator for shared network filesystems.

## Persistence and recovery

Each successful bounded batch is saved as a float32 `.npy` shard, with an adjacent
JSON manifest containing ordered request IDs, model configuration and SHA-256.
Files are atomically replaced/fsynced before a SQLite FULL-synchronous transaction
publishes locations and usage. Shards are immutable. Missing or corrupt shards
abort before new inference rather than silently repaying for data.

At writer startup, durable shard manifests absent from the catalog are validated
and reindexed. A crashed job is marked interrupted when its model lock is acquired
again. Existing run-local paid vectors can be imported after comparison against a
checksum-verified run export, without calling an API.

This prevents recomputation of successfully persisted results. It cannot guarantee
exactly-once billing if the API response is lost, or execution stops before the
vector and shard manifest are durable. Provider retries may incur charges.

Run exports use disk-backed matrices, JSON and typed Parquet indexes. They can be
reconstructed from frozen inputs and the shared store. `reuse-inputs` forks input
artifacts with a new frozen configuration without repeating parsing. It validates
input hashes even if a crashed derived export is incomplete. Projection fits and
coordinates remain separate, tied to vector hashes and explicit fit scope.

## Backup and sharing

`cache-backup` takes a SQLite point-in-time backup and copies only the immutable
shards referenced by it. It validates file checksums and SQLite integrity, and
writes a completion manifest. It can run while new shards are being appended.
Transfer the complete backup directory and frozen input parquets to another machine;
keep the original model/checkpoint configuration. A restored store supports reuse
without credentials for cached inputs. Backups exclude run inputs, projections,
model weights and unpublished orphan shards; preserve these separately as needed.

## Current model scope

Use hosted OpenAI `text-embedding-3-large` and local `voyageai/voyage-4-nano`.
Current execution is OpenAI only: the user stopped the MLX job on 2026-10-01.
Its 115,554 completed unique vectors remain cached; do not resume without direction.
Voyage nano uses the official checkpoint through a pinned community MLX port, with
trained role prefixes, full 2,048-dimensional float32 outputs, BF16 compute, bounded
memory, and explicit context checks before the backend's truncating tokenizer.
MLX is an optional Apple-silicon dependency. Checkpoint files are checksum-verified.
Voyage large has no published local weights and remains deferred; Qwen-8B is also
deferred. Local nano is not a substitute measurement of Voyage large.

## Completed OpenAI feature package

The full OpenAI run stores query-to-field alignment, seven independent 32-dimensional
training-fit PCA artifacts (title and H1 separate), fit manifests, and a named field
bundle at `features/openai-v1.json`. Coordinates join `units.parquet` by unit ID,
then record associations by snapshot/query IDs. All original vectors remain intact.
Training excludes upstream-ineligible/mixed-split units and exact held-out content;
all successful field units are transformed. Large fits use seeded randomized SVD.
These are reusable representations and descriptive coverage, not a validated
relevance model or optimal dimension choice.
