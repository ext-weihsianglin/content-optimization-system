# Project context for future sessions

Read `PROJECT_CONTEXT.md` at the start of a new task in this repository. It records
the current decisions, completed evidence, artifact locations, and remaining work.
Recheck Git and runtime state rather than assuming the saved checkpoint is current.

## Persistent data and checkpoints

The golden local data volume is
`/Users/ext-weihsiang.lin/Documents/profound/data`. Store this project's persistent
data under `content-optimization-system/` in that volume, shared across sessions:

- `raw/`: original snapshot inputs; preserve their bytes and verify source hashes.
- `processed/`: versioned extraction exports, caches, and resumable run checkpoints.
- The completed markdownify corpus is at
  `/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/markdownify-corpus-v1-complete/`;
  start with its `manifest.json` and `run_identity.json`.

Look in this volume before downloading data or rerunning extraction. A worktree's
ignored `data/` may be a symlink to the shared project directory; verify its target.
For a new worktree, use absolute shared paths or create that symlink only when the
local `data/` path is absent. Never replace an existing directory or symlink blindly.
Use unique versioned run directories to avoid concurrent writers. Do not overwrite
completed exports or frozen results; resume unfinished runs only after checking
their code, input, dependency, and configuration identity. Record durable artifact
paths and validation status in `PROJECT_CONTEXT.md`; keep reports/docs in Git, and
raw data, full exports, caches, environments, and model weights outside Git.

## Working conventions

- Persistent shared project data lives at
  `/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system`.
  Look there before preparing or downloading data. Keep versioned exports and
  immutable completed runs; verify an existing `data` symlink before using it.
  The complete markdownify export is `processed/markdownify-corpus-v1-complete`.
  Its extraction identity is recorded in `manifest.json` and `run_identity.json`.
  Do not overwrite old corpus/vector runs or resume them with changed input recipes.
- Local Voyage MLX was explicitly stopped by the user. Preserve its cache and
  do not resume without direction. Current downstream work uses OpenAI embeddings.

- Always use `uv` for Python environments, dependencies, tests, and scripts.
  Use `.tools/uv` when `uv` is not on PATH.
- Favor fast, bounded experiments and inspect actual outputs before expensive runs.
  Do not restart the deferred Reader-LM benchmark without an explicit request.
- Preprocessing is offline and snapshot-only: no browser rendering, live webpage
  fetching, remote extraction API, or dynamic web index.
- Current default is retention-first conservative DOM for HTML and native parsing
  for Markdown/text. Preserve structure, raw-source traceability, metadata, and
  quality flags. Do not silently replace flagged content with a cleaner extractor.
- Keep frozen evaluation references/results and original analysis intact. Version
  changes to extraction or scoring; distinguish development from held-out evidence.
- Anchor metrics are AI-assisted, not human gold, exhaustive precision/recall,
  causal citation uplift, or verified frontier-model ingestion simulation.
- Keep raw datasets, model weights, environments, caches, and unrelated `.worktrees/`
  out of commits. Do not modify other worktrees without explicit direction.
- Include important reports and docs in requested delivery PRs. State partial-run
  limitations and remaining rollout gates clearly.
