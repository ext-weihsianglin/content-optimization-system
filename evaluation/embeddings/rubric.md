# Query–section relevance review

Generate a run-specific manifest with `uv run python -m representations review`. The generated JSON includes exact query/unit IDs, candidate pools, source URLs, and hostname/content-group-separated development/held-out assignments. It excludes citation labels. Candidate pools stay within their split.

Inspect the exact embedding input in `units.parquet` and contributing source blocks in the upstream `blocks.parquet`. Grade every candidate:

| Grade | Meaning |
| --- | --- |
| 0 | Unrelated to the query |
| 1 | Shares the topic but does not support an answer |
| 2 | Provides partial source-supported answer material |
| 3 | Provides direct, useful source-supported answer material |

Judge supplied content, not external knowledge or the page's citation category. Record missing facts, ambiguous questions, broken extraction, and language limitations in `note`. A cited page need not answer its associated query in the saved snapshot. Cases with no relevant candidates are legitimate; Recall@5 remains undefined for them and the denominator is reported.

Only edit `grade` and `note`; other edits invalidate the fixed manifest identity. Ensure relevance grades are integers 0–3, with no unreviewed candidates. Annotations must be identified as human-reviewed or otherwise disclose reviewer provenance; generated manifests are not ground truth.

Use development judgments to inspect chunking, query instructions, and slice coverage. Freeze that configuration before examining held-out scores. If development changes require different units or candidate pools, generate a new manifest and explicitly retire the old evaluation identity. Do not retune on held-out results and call them untouched.

The initial sampler is deterministic and group-separated but not a guarantee of representative language/page-purpose coverage. Inspect and supplement the manifest before freezing a final experiment. Record final sampling changes and review denominators. Approximately 120 cases are a planning target; each case can contain many chunks and review effort must be measured.

Evaluate the same judged pools for every candidate model. Report nDCG@5, sampled-pool Recall@5, unavailable-vector cases, independent group counts, and bootstrap intervals. Corpus recall and citation uplift cannot be inferred from these scores. A tie or an insufficient sample is a valid result; do not choose by favorable top/bottom separation.
