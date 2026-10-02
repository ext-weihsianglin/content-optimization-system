# V6 controlled ablations

Run the three approved ideas independently against the frozen selected v5 model
(96 features), plus one combined variant. Same eligible records, fixed hostname
assignments, no new parsing or embeddings. Do not tune from prior test readings.

1. **Body-supported metadata:** replace the nine title/URL lexical-match features
   with their products with v5 best answer-sentence coverage. Do not retain those
   nine raw match inputs in this variant. Other metadata/path-type features remain.
   This tests corroboration as a replacement, not merely redundant interactions.
2. **Long-prose recovery:** derive 10/25/50-token sliding-window coverage from
   deduplicated prose sentence segments longer than 80 tokens, which v5 skipped.
   Windows never cross blocks. Preserve existing v5 sentence features.
3. **Conservative lexical normalization:** add separate normalized query coverage
   for title/path/body/prose and numeric matches; limited English plurals,
   hyphenated-word aliases, numeric formatting and unit aliases. No learned
   vocabulary, broad stemming, unit conversion, semantic inference or embeddings.
4. **Combined:** all three changes; baseline remains an explicit contender.

Five variants × C={.001,.01,.1,1,10}; four training-host folds, seed137. Choose C
by grouped training CV ROC-AUC subject to coefficient concentration (top1<=20%,
top5<=60%). Require CV non-regression versus baseline; choose finalist by validation
AUC after positive permutation share<=45% and original post-parser gates
(mean inflation<=.03,p95<=.08).

Before selection, compare all finalists on the same 20 hash-selected validation
HTML snapshots and four raw edits used in v5. Require mean AND p95 inflation for
each edit no more than .01 absolute probability above the v5 baseline. This is a
relative non-regression gate, NOT proof of robustness: v5's title sensitivity is
already large. Report absolute effects. The corroboration ablation must be judged
on measured effects, never presumed to fix manipulation.

Freeze selection before an optional one-time reused-test evaluation. If no new
candidate beats v5 under these rules, retain v5 and do not reopen test. Report paired
fold results, validation comparison, feature/family importance, response curves,
raw/post-parser stress, all feature definitions and limitations. Keep defaults and
v1–v5 artifacts unchanged. Prepared v6 artifacts should be shareable without reruns.
