# GPT-5 smoke on the markdownify corpus

All 12 rebuilt smoke cases processed using GPT-5 at medium reasoning. Every returned
model identity was `gpt-5-2025-08-07`. The source is the saved shared markdownify
corpus, using recipe `teacher-blocks-markdownify-v2`; no earlier teacher labels or
calls were reused. Same draft rubric as the historical run; no silent rubric repair.

Review [HTML judgments and source evidence](teacher-markdownify-gpt5-smoke-v1.html)
and [complete labels/provenance](teacher-markdownify-gpt5-smoke-v1.json).

## Execution

- 48 generation attempts: 33 mechanically valid / 15 invalid, no transport failures.
- Requirements: 12/12 valid. Body: 9/12 valid. Title: 12/12 valid.
- Nine stages recovered through one repair. Three body stages exhausted both attempts
  and remain unlabeled: video automation, GPT-4o, visual project planning.
- Rejected attempts: 10 exact-quote/block-reference failures, 4 partial-view missing
  judgments, 1 requirements output-limit failure. These are attempt counts, not
  semantic accuracy estimates. First-pass body validity was 3/12; after repair 9/12.
- API usage: 481,264 input / 185,720 output tokens, including billed reasoning.
  Conservative standard uncached cost estimate: **$2.45878**, below $10.
  All attempts returned usage; no unknown-call cost reservation remains. Not an invoice.
- Six body views are partial. Scores concern supplied views; unavailable stages
  are masked rather than converted to zero or filled from rejected attempts.
- Evidence support: deterministic unassessable for all 12 because no separate
  evidence packs exist. This is not a GPT-5 grounding assessment.
- No human review, independent teacher comparison, student training or bulk expansion.

## Actual validated scores

Scores are ordinal 0–3. FAILED means no valid label after the bounded repair.
`not_applicable` means no title was supplied.

| Query | Intent | Sections | Title consistency |
| --- | --- | --- | --- |
| Does Cox have firewall built in? | 0 | 0 | not_applicable |
| Shops with windshield washer fluid in stock in Montreal? | 1 | 1 | 3 |
| How to automate video creation from daily blog content? | FAILED | FAILED | 3 |
| Kubernetes cluster autoscaling solutions support spot instances | 3 | 3 | 3 |
| GPT-4o | FAILED | FAILED | 3 |
| How to present KPIs clearly for executives? | 2 | 2 | not_applicable |
| AI swapping dance | 1 | 1 | 3 |
| Top platforms for visual project planning | FAILED | FAILED | not_applicable |
| Smart answers to interview questions | 1 | 1 | not_applicable |
| what's the best phishing simulation tool for my security team | 0 | 0 | 3 |
| best content delivery networks for bot management | 0 | 1 | 3 |
| How to choose tools that cut costs in embedded payments? | 0 | 0 | 3 |

## Review findings and next gate

1. Exact evidence is the main mechanical failure. The video tutorial's repaired
   body label still assigned “We’re setting up **two scenarios** in Make:” to
   `b000083`, whose actual source text is “Overview of the Automated Workflow”.
   Proposed intent/section scores were both 3, but neither becomes a training label.
   The visual-planning repair also combined text that was not an exact span in its
   assigned block. Some first attempts removed Markdown punctuation from quotes.
   Before rerunning failures, improve repair diagnostics with the offending JSON
   location, block ID and exact source text; don't relax validation or silently
   replace evidence with guessed spans.
2. Static-page requirements still need revision. GPT-4o requirements inferred as
   essential: “Acknowledge the ambiguity and invite the user to specify the desired
   aspect (e.g., overview, features, access, comparison).” Both body attempts
   violated the partial-view missing-answer guard. Requirements should describe
   information a page should contain, rather than assistant interaction behavior.
3. Title consistency again has no negative examples: all eight supplied titles
   score 3, including the matching loading-screen title. It measures promise
   alignment, not query usefulness or truth. Review misleading-title/edit controls
   before using it as a positive reward by itself.
4. Component scores distinguish usefulness: Kubernetes spot-capacity content scored
   intent/sections 3/3; the washer-fluid product page scored 1/1 with no Montreal
   inventory answer. The payments interstitial scored 0/0 with title consistency 3.
   Review source-quality abstention versus genuine answer failure and whether
   inferred requirements are proportionate to each query.

Do not expand to the 120-case pilot or full corpus yet. Human-review requirements,
quotes, scores and failures; freeze a revised rubric/packet version if needed;
rerun failed cases with traceable diagnostics; then test blinded edits and separately
curated support packs before certifying reliability gates. Same-query comparisons
with the earlier run also reflect newly derived requirements and model variation,
not an isolated causal effect of Markdown formatting.

## Durable artifacts

Persistent run:
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/encoder-scorer/teacher-markdownify-v2-ready/gpt5-smoke-v1/`.
Contains `manifest.json`, `summary.json`, `labels.json`, `smoke-review.json`, all 48
`traces/`, archived matching `code/`, `rubric.md`, and `source-packets-manifest.json`.
Full source-bearing traces remain outside Git. HTML trace links work locally and
require artifact transfer on another machine. Original packages/reports remain intact.

Verification: all 12 report cases, all 48 local trace links, archived code hashes,
Markdown-aware provider inputs/quality flags and absence of API credentials checked.
Implementation tests previously passed: 238 tests / 12 subtests; this run changes
only evidence/reports and checkpoints.
