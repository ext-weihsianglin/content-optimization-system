# Teacher-supervision pilot checkpoint

Phase 1 offline preparation is complete. Teacher execution is pending the user's
model choice, as explicitly requested. No teacher selected, no model calls, no
teacher labels, and no human-reviewed judgments. Phases 2–4 have not started.

- Source: existing frozen LR v2 retention documents; no extraction rerun or source
  cache mutation. Identity checked against cached payload metadata; document hashes
  frozen at curation, without asserting independent raw-payload verification.
- Candidate pool: 868 distinct development hosts. Curated cases: 96 train and 24
  validation, all distinct hosts. No test document loaded; selection ignores labels.
- Coverage: 113 HTML / 7 Markdown; 33 needs-review; 37 tables / 10 code cases.
  This intentionally varied development sample is not a random corpus sample.
- Smoke queue: 12 training cases, 8 full-body / 4 partial-body views. Omitted block
  IDs are retained. Character budgeting is not tokenizer budgeting.
- Independent review queue: 30 cases, not yet reviewed.
- Controls: 18 blinded edit pairs across 3 full-body training parents. No preference
  labels; mutation intent is stored separately. Original-source packs test fidelity
  only. These post-parser edits do not establish raw-HTML robustness.
- Verification: 124 tests and 12 subtests passed after installing locked Python and
  Node dependencies locally from caches. Independent curation and packet replay is
  byte-identical. Local documentation links and whitespace checks passed.

Inspect [HTML preparation report](../../analysis/teacher-curation-v1.html) and
[machine-readable summary](../../analysis/teacher-curation-v1.json).
Source packets and curation/edit ledgers are ignored under
`data/encoder_scorer/teacher-v1/`. Code and commands:
[encoder_scorer README](../../encoder_scorer/README.md).

Next: discuss and record teacher-model choice with the user; then implement the
approved provider adapter, tokenizer budgeting and bounded-call usage/cost ledger.
Run the smoke annotations, inspect actual evidence and disagreements, review a
human subset, and freeze rubric reliability gates before expansion or training.
