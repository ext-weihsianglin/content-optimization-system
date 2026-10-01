# Frozen frontier candidate

Completed bounded v3/v4 hill climb: 50 development configurations, richer features,
concentration gates, duplicate-heading scoring fix, explicit frozen model inference,
visual importance/sensitivity, ELI5 descriptions and reused-test evaluation.

Selected v4 all / C=.01 / 86 features. Validation AUC .67206; reused-test AUC
.67904 vs v2 .67689. Paired difference CI crosses zero: no reliable generalization
improvement established. No further model tuning followed test inspection.

See report.md/report.html, selection.json, verification.json, audit.json,
stress.json and test_metrics.json. V2 stays default; v4 is explicitly selectable.
All cache/model files are also copied and hash-verified in the main repository's
ignored data/trad_ml_scorer/v4 directory. No preparation rerun required.

This iteration is packaged for review on `feat/lr-frontier-v3-v4`. Future follow-up should use new hosts for
independent confirmation and broaden raw-HTML and URL/title robustness checks.
