# Markdownify GPT-5 smoke: source-selection harness

[Plain-language HTML](teacher-markdownify-gpt5-selection-smoke-v1-eli5.html) ·
[detailed HTML](teacher-markdownify-gpt5-selection-smoke-v1.html) ·
[complete results](teacher-markdownify-gpt5-selection-smoke-v1.json) ·
[original frozen smoke](teacher-markdownify-gpt5-smoke-v1.md).

All 12 cases passed requirements, body and title on their first attempt: **36 valid
calls, zero rejected calls, zero repair or transport retries**. Returned model:
`gpt-5-2025-08-07`, requested GPT-5 at medium reasoning. Estimated standard uncached
cost **$1.50422125**, including all calls; 318,921 input and 110,557
output tokens. All calls returned usage. This is an estimate, not a billing invoice.
The original run had 9/12 accepted body stages, 48 calls and $2.45878 estimated cost.

## Changed contract

`teacher-selection-v1` wraps the canonical `teacher-label-v1` output contract.
The model selects enum-constrained source block IDs and fills required frozen
requirement slots. Backend code copies complete selected blocks into exact
`{block_id, quote}` evidence. Model-transcribed substrings are no longer requested.
Raw provider selections and assembled labels both remain in the local traces.
Candidate and support-pack choices stay distinct. Schema preflight rejects
oversized contracts; conflicting duplicate JSON keys reject before parsing loses
information. No guessed IDs, relocated evidence, Markdown normalization or
permissive fallback is used.

Partial views exclude globally `missing` requirement and `unfulfilled` title states
at generation time; canonical local evidence/score/section checks remain active.
The query-only runtime instruction evaluates static pages rather than requiring
conversational follow-up. The requirements output cap increased from 2,400 to 4,000
tokens after the original run's output-cap failure. The model, reasoning effort,
$10 spend ceiling, 12 case IDs, source packets, saved rubric and six partial views
are unchanged. No prior labels/calls were reused.

This changes instructions, output limits and evidence granularity together. The
comparison measures integration validity and operational cost, **not improved
teacher accuracy** or an isolated causal effect of one harness change. Selecting
a valid but irrelevant block still passes source-copy checks.

## Scores for review

Each score column is intent / section usefulness / title consistency (0–3).
Unassessable and not-applicable are distinct from failed validation or a zero score.

| Query | Original run | Selection rerun |
| --- | --- | --- |
| Does Cox have firewall built in?  | 0 / 0 / not_applicable | unassessable / 0 / not_applicable |
| Shops with windshield washer fluid in stock in Montreal? | 1 / 1 / 3 | unassessable / 1 / 3 |
| How to automate video creation from daily blog content? | failed / failed / 3 | 3 / 3 / 3 |
| Kubernetes cluster autoscaling solutions support spot instances | 3 / 3 / 3 | 3 / 2 / 3 |
| GPT-4o | failed / failed / 3 | 3 / 3 / 3 |
| How to present KPIs clearly for executives? | 2 / 2 / not_applicable | 2 / 3 / not_applicable |
| AI swapping dance | 1 / 1 / 3 | 1 / 2 / 3 |
| Top platforms for visual project planning | failed / failed / not_applicable | 2 / 1 / not_applicable |
| Smart answers to interview questions | 1 / 1 / not_applicable | 0 / 2 / not_applicable |
| what's the best phishing simulation tool for my security team | 0 / 0 / 3 | 1 / 1 / 3 |
| best content delivery networks for bot management | 0 / 1 / 3 | 0 / 0 / 3 |
| How to choose tools that cut costs in embedded payments? | 0 / 0 / 3 | 0 / 0 / 3 |

The three original failures (video automation, GPT-4o and visual planning) now have
accepted body labels. Cox and Montreal washer-fluid intent assessments abstain as
unassessable on their partial views. All eight supplied titles again score 3,
including the loading screen: title consistency remains a weak standalone quality
reward. The GPT-4o checklist no longer requires an invitation to a conversation.
These observations need human semantic review, not automatic promotion.

## Verification and provenance

- **252 tests and 12 subtests passed.** Tests cover unknown/empty evidence IDs,
  missing/extra requirement slots, exact Markdown/whitespace copying, distinct
  support choices, partial-state constraints, duplicate keys, schema limits,
  resume and raw-versus-assembled trace preservation.
- All 36 labels revalidated locally; every evidence quote equals its selected
  source block in the actual provider input. Every first-pass request hash replays
  with the current implementation. Exact executed inference code/rubric snapshots
  are archived and match the run manifest; later reporting updates and a stricter
  single-enum string-size preflight guard do not change these 36 request payloads.
- Twelve accepted ELI5 case cards and all 38 local links verified. Automated visual
  browser inspection was not performed; file URLs were previously blocked by policy.
- [Historical reference replay](teacher-selection-reference-regression-v1.json)
  converts eight rejected body outputs to ID-only choices without changing their
  IDs/states. Seven then pass mechanical validation with whole-block copying;
  one remains rejected for a globally missing partial-view claim. This offline
  replay is not a teacher rerun or evidence that those selected blocks are relevant.

Persistent run:
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/encoder-scorer/teacher-markdownify-v2-ready/gpt5-smoke-selection-v1/`.
It contains manifest, labels, summary, 36 source-bearing traces, exact executed
`code/`, `rubric.md`, source-packet manifest and copied `smoke-review.json`.
Full source packages and raw traces remain outside Git. Original run/report
artifacts are preserved. Source of truth remains the completed offline Markdownify
corpus; no extraction or live fetching was performed.

No independent teacher, human review, student training, LR benchmark, demo
integration, pilot expansion or corpus-scale annotation was performed. Factual
support still abstains deterministically because no separate evidence pack exists.
Next: review selected evidence and scores, especially partial-view abstentions,
query checklists and title negative controls, then evaluate controlled edits before
expanding beyond this smoke.

The strict-schema limits were checked against
[official OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
This implementation follows the
[demo-webapp harness review](teacher-harness-demo-webapp-review.md).
