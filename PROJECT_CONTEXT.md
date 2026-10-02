# Content optimization project memory

Checkpoint: 2026-10-01. This is repository-local session memory. Start here, then
read the linked specs and reports as needed; verify live Git state before acting.

## Goal and user priorities

Profound work trial: analyze page/content factors associated with answer-engine
citations and build a lightweight query-specific content generation/refinement
workflow. Original task: `project-brief.md`. Deliver useful, inspectable work quickly;
do not overinvest in model tuning. The user wants HTML reports and sample outputs
they can eyeball, reproducible quantifiable evaluation, and important docs/reports
checked into delivery PRs. Always use `uv` for Python.

## Repository and delivery checkpoint

- Local repo: `/Users/ext-weihsiang.lin/Documents/profound/content-optimization-system`.
- Remote: `https://github.com/ext-weihsianglin/content-optimization-system.git`.
- PR #1: `https://github.com/ext-weihsianglin/content-optimization-system/pull/1`.
- GitHub verified PR #1 **merged** at `2026-10-01T19:06:15Z`, merge commit
  `eb99b7c19c37b8a29369ec23ffc4847ebcd19ada`.
- Implementation commit: `dec31d269b96bf20cb6f42271efa76b116fd7b67`.
- Local branches may differ from merged main; inspect `git status` and branch state
  rather than assuming the checkout has followed a remote merge.
- `.worktrees/` contains unrelated parallel work; leave it alone. Repository startup
  instructions are in `AGENTS.md`; this file holds the detailed project context.

## Current architecture decision

**Retention first, then downstream relevance decisions.** Use `conservative_dom`
for HTML; `markdown_text` for native Markdown/plain text. Preserve raw snapshots
and original metadata/JSON-LD separately. Keep ordered typed blocks with headings,
parent-linked lists, code whitespace, links, table cells/spans/header roles, source
locators and honest mapping-confidence labels. Markdown/text are convenience views.

The downstream contract is `spec/downstream-document.md`; implementation is
`preprocessing/downstream.py`. It exports documents, heading outlines, and chunks
with a soft 6,000-character target (NOT a token budget). Tables, code and complete
nested-list trees stay atomic; oversized chunks are flagged, never truncated.
Every selected block appears exactly once, in order, in the chunk partition.
Quality warnings remain attached; flagged content is retained as `needs_review`.
Missing preferred output never silently substitutes another parser. Reader-LM is
not the default. Readability/Trafilatura remain optional clean views; the superseded
precision-oriented selector is retained as `select_precision_candidate`.

The user hypothesizes that frontier models benefit from broad content retention.
Treat retention-first as our design objective, NOT evidence that we replicate a
particular proprietary frontier API's undocumented ingestion pipeline. Conservative
DOM still removes some navigation/boilerplate; only the stored raw payload preserves
the original snapshot in full. Source content is untrusted data, not instructions.

## Dataset and original analysis

- Five `data/raw/citations_part_00*.parquet` files: 9,700 rows, 970 hosts, exactly
  five top/five bottom rows per host; 9,527 distinct URLs.
- Actual columns: `prompt`, `citation_category`, `href`, `hostname`, `html_content`.
  Despite the brief, no separate cleaned-Markdown column is provided.
- 91 blank prompts; 28 excess exact duplicate rows; 14 URLs have conflicting labels.
- Labels are relative within hostname; both classes have been cited. No citation
  counts, exposure, engine identifiers or observation times: no causal/uplift claims.
- Broad content associations are confounded. Strict same-query sensitivity has only
  29 matched host/query groups across 27 hosts; do not turn length/headings into
  universal editing targets. Original v1 analysis remains unchanged.
- ZIP is in Downloads; exact location/hash: `analysis/provenance.json`.
- Original report: `analysis/brief-report.html`; eyeballing CSV:
  `/Users/ext-weihsiang.lin/Documents/profound/content-optimization-system/analysis/citation-sample-500.csv`.

## Completed extraction evidence

Frozen evaluation: 100 distinct hosts, 60 development / 40 held-out, no hostname or
identical-payload overlap. Source formats: 88 HTML, 8 Markdown, 4 plain text.
Source-only AI reviewers selected 338 required and 127 unwanted anchors before
candidate scoring; 82 sources are content-evaluable. References are sparse AI-assisted
annotations, NOT human gold or exhaustive coverage.

Retention = required anchors surviving extraction / eligible required anchors.
Leakage = unwanted anchors surviving / eligible unwanted anchors; NOT the fraction
of generated text that is boilerplate. Higher retention and lower leakage are better.

Held-out HTML scores: 32 evaluable pages, 129 required anchors, 50 unwanted anchors.

| Method | Required retention | Unwanted leakage |
| --- | ---: | ---: |
| Frozen BeautifulSoup baseline | 121/129 (93.8%) | 30/50 (60%) |
| Trafilatura | 100/129 (77.5%) | 11/50 (22%) |
| Readability + Turndown | 111/129 (86%) | 11/50 (22%) |
| Conservative DOM | 126/129 (97.7%) | 46/50 (92%) |

Native held-out results are separate: 3 Markdown pages, 13/13 required and 2/2
unwanted anchors retained. No held-out plain-text quality estimate. Synthetic
structure checks are separate from real-page accuracy. No human gate is certified.

- All five methods have 500 explicit outcomes; no exceptions/timeouts, six empty
  outputs. Resume is byte-identical; independent rerun matches excluding timing.
- Frozen artifacts: `evaluation/extraction/{manifest,annotations,freeze,verification}.json`.
- Source cache: `data/evaluation/`; complete run: `data/processed/eval-v2/`.
- Reports: `analysis/extraction-evaluation.html` and `.json`, development companions,
  `analysis/extraction-fixtures.json`; metric rubric: `evaluation/extraction/rubric.md`.

## Retention export checkpoint

`data/processed/retention-v1/`: 100 documents, 28,539 blocks, 2,383 chunks, 17 oversized
chunks. Statuses: 87 selected, 8 need review, 5 source-insufficient. Selected methods:
87 conservative DOM, 8 native, 5 none. Artifacts: `documents.jsonl/.parquet`,
`chunks.jsonl/.parquet`, `manifest.json`; committed summary:
`analysis/retention-export.json`. This is the evaluation set only, NOT a 9,700-row
corpus rollout. Last validation: **94 tests passed, 12 subtests passed**.

## Traditional ML scorer handoff (v2 through v4)

PR #2 completed the full-corpus retention integration under `trad_ml_scorer/`.
9,700 rows reference 9,551 exact payload-plus-URL snapshots; the 149 difference
is shared references, not missing data or a split artifact. Eligible v2/v4 rows:
7,540 train, 945 validation, 947 test with frozen hostname assignments.

The v3/v4 follow-up preserves both iterations. V3 adds lexical relevance and
composition features; balanced importance still allowed duplicate-heading score
inflation. V4 suppresses repeated and unsupported headings in a scoring view,
without modifying parser documents. It has 86 features and C=.01. Four training
host-grouped folds choose regularization; validation AUC chooses among candidates
passing coefficient, permutation, and three post-parser manipulation gates.

Validation AUC: v2 0.66070, v4 0.67206. Reused-test AUC: v2 0.67689, v4 0.67904;
paired difference +0.00215, 95% host-bootstrap interval [-0.01517, +0.01775].
The gain is small and statistically uncertain, not independent confirmation.
V4 top coefficient share is 5.83%, top positive permutation share 10.51%.
Duplicate-heading mean score inflation fell from 0.113 to 0.013 (p95 .224 to .031).
These checks do not certify arbitrary manipulation resistance or causal uplift.

Read `trad_ml_scorer/v3/STATUS.md` for the historical iteration and
`trad_ml_scorer/v4/report.md` / `report.html` for final metrics, visual importance,
sensitivity, all feature explanations and next-round ideas. V2 remains default;
select v4 with `--model data/trad_ml_scorer/v4/model.joblib`. Full test suite:
114 tests / 12 subtests; training-only refit verification and raw inference parity
on six development snapshots passed. Do not retune against the inspected test.

**Reuse prepared data rather than redoing preparation.** Shared ignored caches in
the main repository's `data/` contain `lr/` and `trad_ml_scorer/{v2,v3,v4}/`, with
SHA-256 copy inventories. New local worktrees may link them if destinations are
absent; a separate machine needs an artifact transfer. Models and raw/prepared data
are not committed. All LR code, manifests, report outputs and predictions belong
under `trad_ml_scorer/`; original analysis and frozen v1/v2 are preserved.

## Reader-LM experiment and stop decision

No hosted Jina API access. Downloaded `jinaai/reader-lm-0.5b` at pinned revision
`46cb69fff9d100f9c3c2a135d59f365fb99a0121`; local Apple M4 Pro / 24GB, MLX BF16.
Separate `.venv-reader` (Python 3.12); setup in `preprocessing/READER-LM.md`.
Weights: `data/models/reader-lm-0.5b`; CC-BY-NC-4.0, resolve commercial licensing
before production. This model is NOT the hosted Jina Reader service.

Initial local-server run: 64K prompt / 2K output, stopped at 35 outcomes (23 HTML,
12 unsupported). Only 10 completed pages were evaluable, all table-stratum pages;
required retention 10/41 versus Readability 36/41 on the same subset. Repetition,
script copying and output caps made further unchanged execution wasteful. Nonempty
`ok` outputs are not quality successes. Partial ledger must not be ranked as full eval.

Three-page follow-up: direct MLX streaming, up to 96K input + 32K output, prefill 2048,
repetition stopping, 180-second per-page budget. All three full inputs fit:
- DigitalOcean: 2/4 required anchors; repetition stop, 1,616 tokens, 21.7 seconds.
- Visit Phoenix: 0/4; time stop, 9,678 tokens, 180 seconds.
- Wisernotify: 2/4; normal completion, 3,670 tokens, 52.5 seconds.

Expanded budgets did not rescue this configuration. These are purposive development
diagnostics, not a general verdict on Jina or an isolated model/backend comparison.
Both server and benchmark were stopped; no further inference is scheduled. **Do not
restart without user direction.** Reports: `analysis/reader-lm-review.html`,
`analysis/reader-lm-pilot.html`, `analysis/reader-lm-progress.html` and JSON companions.

## Fast restart and remaining work

1. Read Git status and verify branch/main state; preserve unrelated worktrees.
2. Read `spec/downstream-document.md`, `README.md`, and this checkpoint before
   revisiting settled parser choices. Use the existing local export for a fast demo.
3. Integrate structured chunks into the query-specific downstream workflow, carrying
   source/block/chunk IDs through relevance selection and generated suggestions.
4. Full-corpus scorer migration and versioned feature/sensitivity analysis are complete.
   Remaining work includes fresh-host confirmation, human reference review, broader
   manipulation checks, model-specific token budgeting and factual grounding checks.
   A prospective citation experiment remains separate.

Useful commands (repo root):

```sh
.tools/uv sync --dev
npm ci --prefix preprocessing/node
.tools/uv run --offline python -m pytest -q
.tools/uv run --offline python -m preprocessing.prepare_eval --materialize
.tools/uv run --offline python -m preprocessing run --split all --output data/processed/replay
.tools/uv run --offline python -m preprocessing.benchmark --results data/processed/replay/results.jsonl
.tools/uv run --offline python -m preprocessing.downstream --run data/processed/replay --output data/processed/retention-replay
```

Materialization needs the original raw parquet files and verifies hashes; it does
not resample. Use new output directories instead of overwriting frozen artifacts.
JSONL must be read by file iteration, not `str.splitlines()` (embedded Unicode line
separators caused a real parsing bug). Large generated reports use escaped previews;
their truncation does not affect full-output anchor scoring.

## V5 sparse-feature follow-up after merged PR #5

Review branch `feat/lr-evidence-v5-v6` captures the v5 and v6 iterations. See
`trad_ml_scorer/v5/report.md` / `.html` and `v5/STATUS.md`. Added 28 candidate
features; development rules selected 10 answer-sentence features (96 total).
Validation AUC .67435; reused-test .68088 vs v4 .67904; difference interval
[-.00253,+.00604] crosses zero. Numerical/evidence cues failed CV non-regression,
and structured table/step additions did not improve validation. No post-test tuning.

119 tests / 12 subtests pass; unchanged population/v4 columns, training-only refit
and 20 raw/public inference parity checks passed. Shared ignored v5 cache avoids
repeating prep. V2 remains the CLI default. Importance is not concentrated, but raw
title replacement causes ~23-point probability inflation; arbitrary metadata and
unverified assertion edits remain unsafe as model-driven optimization targets.

The user has another session scoping per-field embeddings and projections. Leave
that work to it. Integrate later via exact snapshot/field/prompt identity, encoding
fingerprints and fold-local fitting of learned projections (see v5/plan.md), with
explicit benchmark/test exposure. No embeddings were generated in this iteration.

## V6 controlled low-cost experiments

The user approved all three follow-up ideas: body-supported title/URL matching,
long-prose recovery, and conservative lexical normalization. Each was tested alone,
plus combined, against selected v5 (25 C/variant configurations; same host folds).
See `trad_ml_scorer/v6/report.html`, `report.md`, `plan.md` and `STATUS.md`.

Retain v5: all new variants slightly reduced grouped CV AUC despite small validation
gains, failing the predeclared rule. No new test evaluation. Corroboration cuts title
mean inflation .230 -> .142 and URL .066 -> .018, but query-repetition p95 grows
.066 -> .112 (combined .131). Balanced importance does not establish robustness.
123 tests / 12 subtests pass, training-only refit and source/cache parity verified.

Prepared v6 caches are shared and SHA-verified under the main repository's ignored
`data/trad_ml_scorer/v6`. Reuse v5 for inference; v6 bundles are experiment artifacts.
No embedding work was duplicated. Continue with per-field embeddings when the
other session supplies provenance and fold-local projection/benchmark details.

## Fixed-prompt interpretation follow-up

The user wants editing-oriented importance with the prompt fixed. See
`trad_ml_scorer/interpretation/fixed_prompt/report.html` and `.md`. This is a
companion analysis of retained v5, not v7 or a new fit. Prompt-only terms cancel
in paired log-odds differences but still affect baseline probabilities. URL stays
fixed too; document and prompt×document effects are shown separately from context.

The report analyzes coherent, body-word-preserving edits on 40 validation HTML
snapshots, reparses all features, and verifies exact additive logit attribution
including missing indicators. Pure prompt/URL contributions are zero. Serialization
controls had zero score drift. Title←H1 mean score delta -.93 pp (26 applicable),
relevant-paragraph-first +.11 pp (21), paragraph split +.02 pp (4). No demonstrated
citation uplift; intervals for first two span zero, third sample too small.

Validation contains only one mixed-label same-prompt/same-host group, so do not
claim reliable empirical conditional ranking importance. The filtered global
permutation plot is explicitly still across-query predictive importance. Prefer
real fixed-query edit contrasts, paired distributions and joint-family reasoning;
require grounded review and prospective evaluation before optimizing citations.


## Corrected feature dependency audit

The original fixed_prompt companion mixed dependency with editability. Its frozen
JSON/plots remain as provenance, but its five-category taxonomy is superseded by
`trad_ml_scorer/interpretation/dependency_audit/report.html` (and `.md`). The explicit
registry `feature_dependencies.json` audits every retention-based v2–v6 candidate:
142 total = 4 prompt + 41 doc + 97 promptXdoc; selected v5 = 4 + 41 + 51 (96).
`path_homepage` is doc, as are source/parser flags and question_heading_fraction.
`path_query_*` and normalized_path_* are promptXdoc, but fixed during HTML-only
edits. Supported path variants also use body support and may vary under HTML edits.
Query-selected section lengths and relevant-sentence evidence fractions are joint.
Missing indicators inherit their parent dependency. Unknown names fail explicitly.

The corrected plots use three dependency panels with separate URL/diagnostic
annotations. Model, coefficients, edit outcomes and frozen v1–v6 results unchanged;
no fitting, corpus preparation, or test evaluation rerun. All 130 tests and 12
subtests pass, including extractor inventory, prompt invariance of doc features,
document invariance of prompt features, and fixed-context attribution checks.
