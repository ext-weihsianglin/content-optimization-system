# Project context for future sessions

Read `PROJECT_CONTEXT.md` at the start of a new task in this repository. It records
the current decisions, completed evidence, artifact locations, and remaining work.
Recheck Git and runtime state rather than assuming the saved checkpoint is current.

## Working conventions

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
