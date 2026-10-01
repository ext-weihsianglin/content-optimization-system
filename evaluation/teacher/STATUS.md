# Teacher-supervision pilot checkpoint

Phase 1 offline preparation is complete. The user approved GPT-5 at medium
reasoning for the 12-case smoke, with a $10 bounded budget. Returned snapshot:
`gpt-5-2025-08-07`. Teacher judgments are development evidence awaiting human
review. Phases 2–4 have not started.

Smoke outcome: 12 cases processed; requirements/title 12 valid each, body 11 valid /
1 unavailable. 42 attempts: 35 valid, 6 rejected, 1 timeout subsequently recovered.
Conservative cost ledger: $1.9832 including the unknown-call reservation. Inspect
[HTML smoke judgments](../../analysis/teacher-gpt5-smoke-v1.html) and
[findings and review priorities](../../analysis/teacher-gpt5-smoke-v1.md).

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
- Verification: 133 tests and 12 subtests passed after installing locked Python and
  Node dependencies locally from caches. Independent curation and packet replay is
  byte-identical. Local documentation links and whitespace checks passed.

Inspect [HTML preparation report](../../analysis/teacher-curation-v1.html) and
[machine-readable summary](../../analysis/teacher-curation-v1.json).
Source packets and curation/edit ledgers are ignored under
`data/encoder_scorer/teacher-v1/`. Code and commands:
[encoder_scorer README](../../encoder_scorer/README.md).

The provider adapter saves exact requests, visible responses, input token counts,
usage, timings, validation errors, and conservative cost estimates. Full source-bearing
traces remain ignored under `data/encoder_scorer/teacher-v1/gpt5-smoke-v3/traces/`.
Earlier `gpt5-smoke` and `gpt5-smoke-v2` directories retain execution lineage and
code snapshots. Valid calls were reused, with parent manifest/trace hashes recorded.
One ambiguous title timeout retained its full cost reservation and was recovered
with an explicitly enabled bounded retry. No external source fetching occurred.

Three model passes run per case: query requirements, body components, and title/body
consistency. Evidence support is a deterministic abstention for all cases because
no separate evidence pack was supplied. It is not a teacher factual-support judgment.
No independent model comparison or human adjudication was run.

Next: review the actual smoke judgments and invalid attempts. Refine ambiguous-query
requirements for static pages, resolve partial-view and exact-quote failures, curate
separate evidence packs, and review controlled edit pairs. Set numerical reliability
and manipulation gates before expanding annotation or training ModernBERT. Any
additional teacher choice remains subject to discussion with the user.
