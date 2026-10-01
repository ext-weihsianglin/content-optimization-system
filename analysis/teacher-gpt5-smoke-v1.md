# GPT-5 teacher smoke review

The approved 12-case smoke is complete. This collects teacher supervision; no
ModernBERT parameters have been trained. Review the [HTML judgments and evidence](teacher-gpt5-smoke-v1.html)
and [machine-readable labels/provenance](teacher-gpt5-smoke-v1.json).

## Execution and validity

- Requested model: GPT-5, medium reasoning. All returned identities:
  `gpt-5-2025-08-07`. No second teacher was used.
- 12 training cases: 8 full retained bodies / 4 partial views. No test documents used.
- 42 generation attempts: 35 mechanically valid, 6 invalid, and 1 transport timeout.
  Requirements: 12 valid; body: 11 valid / 1 unavailable; title: 12 valid.
- Six rejected attempts: 2 output-limit failures, 2 partial-view missing-answer
  judgments, and 2 non-exact evidence quotations. Four stages recovered through
  one repair. The GPT-4o body stage failed both attempts and supplies no training label.
- One title timeout recovered through one explicit retry. Its response/usage is
  unknown, and its full reservation remains in the cost ledger.
- Returned calls: 337,586 input / 148,634 output tokens, including billed reasoning.
  Estimated returned-call cost: $1.9083; unknown-call reservation: $0.0749;
  total conservative ledger: **$1.9832**, below the $10 cap. This is not an invoice.
  Standard uncached rates use the [official GPT-5 model card](https://developers.openai.com/api/docs/models/gpt-5).
- Evidence support: 12 deterministic unassessable outputs because no separate
  evidence pack exists. These are not paid teacher grounding judgments.
- Human-reviewed cases: 0. No independent agreement or semantic correctness claim.

Intent scores among 11 valid body labels: three 0s, four 1s, two 2s, one 3,
and one unassessable. Section usefulness: four 0s, three 1s, four 2s.
Title consistency: eight 3s and four not-applicable outputs for absent titles.
These purposive pilot distributions are not performance metrics.

## Review priorities and findings

1. **Answering versus mentioning.** The Montreal washer-fluid product page received
   intent 0 / section 0 despite title consistency 3: it supplied no Montreal shops
   or observed stock. The bot-protection vendor page likewise received intent 0 for
   a query seeking the best CDNs. Check whether these requirements fairly reflect
   the queries rather than over-demanding comparison content.
2. **Requirements must fit static pages.** For the bare query “GPT-4o,” the teacher
   requested clarifying questions. Its first body pass marked those missing on a
   partial view; repair switched to unassessable but introduced a non-exact quote.
   Both outputs remain rejected. Revise ambiguous-query guidance before expanding;
   do not silently rewrite these labels or the frozen rubric.
3. **Coverage and quality need explicit treatment.** Partial views twice prompted
   unjustified global missing-answer judgments. A payments interstitial received
   intent/section 0 rather than an extraction-quality abstention. Review the policy
   for unavailable page content versus a genuinely poor answer. A manual about a
   Zoom router received unassessable intent for the Cox firewall query.
4. **Title consistency alone is too weak.** Every supplied title scored 3, including
   “Just a moment...” matching a loading screen. This component measures promises
   fulfilled, not usefulness or truth. Review misleading-title controls and inspect
   whether the teacher overcredits headings as evidence of substantive coverage.
5. **Factual support remains untested.** Exact quotes establish traceability only;
   they do not verify claims, freshness, or independent factual support. Curate
   separately identified evidence packs before using this component as a reward.

Next: human-review requirements, scores, abstentions, and rejected attempts; freeze a
revised rubric/packet version if needed; annotate blinded edit controls and curate
support packs. Set numerical reliability/manipulation gates before bulk supervision
or ModernBERT training. Any additional teacher-model choice remains with the user.

## Local artifacts and lineage

Complete source-bearing traces are ignored under
`data/encoder_scorer/teacher-v1/gpt5-smoke-v3/traces/`. Each trace records the exact
request, visible response, token count, usage, timing, validation and cost estimate.
`labels.json`, `manifest.json`, and `summary.json` sit beside that directory.
HTML trace links resolve locally; they cannot resolve in a GitHub checkout without
an artifact transfer. Source packets remain at
`data/encoder_scorer/teacher-v1/smoke-packets/packets.jsonl`.

The initial three calls were reused after a configuration serialization fix in v2.
V3 reused five valid calls and carried the timeout forward after adding bounded
transport recovery and two-case concurrency. Parent manifest/trace hashes and the
original v1/v2 run directories/code snapshots retain provenance. Original offline
curation reports and LR caches are unchanged.

Validation: 133 tests / 12 subtests passed. All 12 review cases and all 42 local trace
links were checked; report JSON parsed and API credentials were absent from delivery
artifacts. Mechanical validity remains separate from human review.
