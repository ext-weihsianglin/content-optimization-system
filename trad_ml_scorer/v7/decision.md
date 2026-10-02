# V7 adoption decision

The user chose v7 as the direction for continued scorer development after reviewing
the semantic-feature prototype. Use `semantic_context` (C=.001): ten original-space
embedding similarities plus 45 existing prompt-only/document-only context features.
This replaces v5's 51 lexical prompt–document features in the experimental scorer.

This is a product/research direction decision, not a claim that v7 outperformed v5
on validation. V7 training CV ROC-AUC is .67440 versus .66185; validation ROC-AUC is
.66443 versus .67435. The paired validation AUC difference is -.00992, with a 95%
website-bootstrap interval [-.03369,+.01348]. No new test evaluation was performed.
The predeclared plan, frozen experiment results and original report remain intact.

Reuse `data/trad_ml_scorer/v7/semantic_context.joblib` and the prepared feature cache.
A SHA-verified shared copy is available under the main repository's ignored
`data/trad_ml_scorer/v7/`. The bundle consumes precomputed named features; it does
not provide a live HTML-to-embedding scoring endpoint. The existing generic CLI
default is unchanged. Page-edit interpretation remains on hold.

The delivery PR is based on the still-open v5/v6 PR #13 so its diff contains only
v7. Merge #13 first and retarget this PR to main. The supplied embedding artifacts
come from the parallel representation work; no new provider calls are required.
