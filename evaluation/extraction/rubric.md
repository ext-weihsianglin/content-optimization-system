# Frozen selected-anchor benchmark rubric

Semantics version: `selected-anchors-v1`. Declared freeze date: 2026-10-01.
These semantics were defined from the specification, plan, schema, and input
contracts without inspecting candidate outputs. A declared date is not a source
capture timestamp or evidence of a completed review.

## Evidence and review

Ground truth is **source-only AI-assisted selected anchors**, not human gold,
whole-document precision/recall, factual verification, or a usability judgment.
The intended frozen sample has 100 snapshots, 60 development and 40 held-out,
one hostname per snapshot. Report actual counts and deviations, not assumed counts.
Sampling is purposive; results do not estimate population accuracy.

Review only saved source payloads. Do not view extractor outputs, citation labels,
or prompts when selecting anchors. Mark whether source content is evaluable.
Select source-supported required snippets spanning useful sections and numerical
facts, with `kind` and `reason`; select unwanted boilerplate with `reason`.
Use literal contiguous snippets that remain identifiable after normalization.
Record limitations and ambiguity in notes and record reviewer type honestly.
No missing text may be inferred. Freeze annotations and sampling before scoring;
revisions require a new version and disclosure. Do not tune on held-out outputs.

## Matching and denominators

Score only the candidate's plain `text` view. HTML, Markdown, metadata, and blocks
are available for inspection but are not searched to rescue an anchor miss.
Normalize both anchor and output with Unicode NFKC, casefold, canonical curly
quotes/primes to straight quotes, Unicode dash variants to hyphen, ellipsis to
three periods, and collapse Unicode whitespace. Preserve other punctuation,
diacritics, numbers, units, and word order. Require exact normalized substring
presence; never fuzzy-match, paraphrase, or remove arbitrary punctuation.
Count each declared nonblank anchor once (presence, not occurrence count).
Duplicate annotations remain explicit weighting; reviewers should avoid them.
Whitespace-only anchors are excluded and their counts reported.

Baseline supports every format; trafilatura, readability, and conservative_dom
support HTML only; markdown_text supports non-HTML only. A declared
`unsupported_format` also excludes that method/document from retention and
leakage; visibly report unsupported coverage even on normally supported formats.
Missing runs on an expected-supported format count as failures, never silently
disappear. Errors, timeouts, empty statuses, and `ok` with blank normalized text
score zero matches, even if an error record contains partial text.

Required retention denominator: evaluable, annotated, supported documents with
at least one nonblank required anchor. Micro = total matched / total required;
macro = mean document retention. Unwanted leakage uses its own eligible
denominator: evaluable, annotated, supported documents with at least one
nonblank unwanted anchor. Micro = total leaked / total unwanted; macro = mean
document leakage. Lower leakage alone does not imply better extraction: failures
have zero leakage as well as zero retention. Empty reference sets yield null,
never a perfect score. Missing annotations are distinct from non-evaluable source.

Report per-document numerators/denominators, source evaluability, support,
failures, missing results, blank-anchor exclusions, and zero-reference counts.
Output failure rate = empty/error/timeout/missing or blank-ok outputs divided
by supported documents, including non-evaluable sources. Keep these operational
counts separate from content scores. Latency includes finite nonnegative recorded
runtime_ms for supported attempts of all statuses; report its count, median,
and p95 (linear interpolation at 0.95 * (n - 1)). Missing latency is not zero.

## Comparisons and limitations

Report methods separately for dev and heldout, for all sources, the HTML-only
comparable subset, the native non-HTML subset, and each stratum within each
subset. Unsupported methods retain visible zero coverage. Do not compare the
HTML pool against the native pool as if they had a common denominator.
Paired baseline retention uses only shared eligible documents, reports shared
document and anchor counts, and both macro and micro candidate-minus-baseline
deltas. No shared documents means null deltas. No uncertainty interval is claimed
by this version; the small purposive sample limits inference.

Human gates **not assessed**: page usability without material omissions,
whole-document factual fidelity, changed numbers/units, invented text, heading
and list relationships, table header-to-cell relationships, and population
quality. Anchor retention cannot establish any of these. The proposed 90%
usability and 95% facts/sections gates in the specification are not certified by
this proxy, even when anchor scores exceed those values. This report does not
certify reproducibility, corpus accounting, or network isolation either.

## Offline report

Display declared dates exactly as supplied; do not infer capture dates. Link
sample summaries to local detail sections and display source file, row, hash,
hostname, URL, split, and stratum. Escape every source/output string; never
execute source HTML or scripts, fetch URLs, or load external report assets.
The supplied manifest contains provenance, not full source payloads: do not
claim a source preview or source/anchor validation when none was supplied.
