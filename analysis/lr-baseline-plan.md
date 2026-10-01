# Logistic Regression Baseline Plan

Draft for review · Version 1 · October 1, 2026

## Objective

Build a simple, interpretable estimator of `P(is_cited_high = 1 | user_prompt, page_content_and_metadata)` using handcrafted features and L2-regularized logistic regression. Start with roughly 25–35 features and a reproducible 80/10/10 train/validation/test split.

Set `is_cited_high = 1` for `citation_category == "top"` and `0` for `"bottom"`. The model computes `sigmoid(intercept + weights @ features)`.

The probability describes membership in the sampled, within-host top-performing class. Both classes were already cited, and the dataset deliberately balances top and bottom pages. This score is not an absolute real-world probability of receiving a citation, nor evidence that an edit causes citation uplift.

## Dataset and unit of prediction

The audit reports 9,700 rows across 970 hostnames, with five top and five bottom rows per hostname. Available fields are `prompt`, `citation_category`, `href`, `hostname`, and `html_content`. Cleaned content must be extracted from the supplied HTML.

Use each prompt and its associated page snapshot as one example. Preserve the original row’s HTML and source provenance. Reuse extraction helpers in `scripts/analyze_content.py` where appropriate.

The existing `analysis/content_features.parquet` collapses repeated pages, selects a snapshot, and averages query coverage across a page’s prompts. It cannot directly serve as the row-level modeling table: recompute alignment against each individual prompt and its actual snapshot.

## Split strategy

Recommended default: assign entire hostnames to splits with a fixed random seed, initially 42. This tests generalization to unseen hosts and keeps a hostname’s URLs and templates within one split.

| Split | Hostnames | Rows before cleanup | Role |
| --- | ---: | ---: | --- |
| Train | 776 | 7,760 | Fit preprocessing and model parameters |
| Validation | 97 | 970 | Select regularization and compare variants |
| Test | 97 | 970 | Evaluate the frozen experiment once |

Persist the split manifest. Apply fixed cleanup rules and report resulting counts and class balance; final row ratios will be approximate. Audit identical HTML across hosts before fitting. If duplicates cross splits, resolve them with a documented grouping or exclusion policy before training rather than leaving leakage unaddressed.

A random row split would measure performance on additional pages from mostly familiar sites. Keep the hostname split as the primary experiment unless the intended deployment requires that alternative.

## Cleanup and quality policy

- Remove exact duplicate records.
- Exclude blank prompts from the primary query-conditioned experiment.
- Quarantine URLs carrying conflicting labels for this first baseline. Document that this can discard genuine query-dependent differences.
- Preserve stable source identifiers, HTML hashes, exclusion reasons, and split membership.
- Retain scrape-quality indicators and evaluate both the full eligible population and a predefined clean-content subset.

Use the existing sensitivity analysis as the starting definition for the clean subset: recognized HTML, no failure or sparse-body flags, and at least 100 extracted words. State explicitly whether a quality rule operates on individual snapshots or all snapshots of a URL; the existing analysis uses conservative URL-level exclusions.

## Handcrafted features

Extract features solely from the prompt, supplied HTML, and URL metadata available at inference time. The following is a candidate pool; freeze the initial feature list before tuning.

| Family | Candidate features |
| --- | --- |
| Prompt–page alignment | Query-token coverage in title, H1, all headings, body, first 200 body words, and URL path |
| Prompt properties | Token count; question, comparison, and “how to” indicators |
| Content size | Word count, title length, heading count, paragraph count |
| Structure | Heading density, list-item density, table presence, H1 presence |
| HTML metadata | Main/article container presence, JSON-LD presence, Article schema |
| URL metadata | Path depth; homepage, editorial, product, and documentation path indicators |
| Extraction quality | Empty-title flag, sparse-text flag, failure-page flag, boilerplate-removal fraction |

Apply `log1p` to skewed counts, keep ratios bounded, and represent missing values explicitly. Define tokenization and empty-query behavior consistently in training and inference. Existing lexical coverage uses a small English stopword list; multilingual inputs need separate interpretation.

Exclude hostname identity, raw URL identity, prompt frequency, label-derived aggregates, and collection-level metadata such as snapshot counts. Path-based indicators are heuristics, not verified page types.

## Fitting and model selection

Use a scikit-learn pipeline: handcrafted features → median imputation with missing indicators → standard scaling → L2 logistic regression.

Fit imputation, scaling, and model parameters on training data only. Start without class weighting because the supplied dataset is balanced; report any imbalance introduced by cleanup.

Select `C` from `{0.01, 0.1, 1, 10}` using validation log loss. Keep the search small and deterministic. Inspect calibration before considering a separate calibration model. For the first experiment, retain the selected model fitted on the training split so validation and test roles remain straightforward.

## Evaluation

| Measure | Purpose |
| --- | --- |
| Log loss | Primary selection metric; penalizes confidently incorrect probabilities |
| Brier score | Squared error of predicted probabilities |
| ROC-AUC | Overall discrimination |
| Accuracy and confusion matrix at 0.5 | Simple classification summary |
| Calibration plot | Predicted probability versus observed top-class frequency |
| Mean within-host AUC | Ranking top above bottom within held-out hosts with both labels |

Compare a constant training-prevalence predictor, a page-only LR, and a prompt-plus-page LR. The comparison measures the predictive contribution of prompt information and alignment features. Report full-population and clean-subset results with sample and host counts.

Inspect standardized coefficients and per-example contributions to the log odds. Correlated features can distribute weights across several predictors; coefficients are predictive associations, not editing prescriptions.

## Evaluation limitations

The existing exploratory analysis already examined the full dataset. A new test split can remain untouched during fitting and tuning, but it is a retrospective holdout informed by prior exploration.

Labels are relative within host, prompts differ across most top/bottom comparisons, and scrape quality can be predictive. Good held-out discrimination does not establish query-specific editing effectiveness or calibration under a different production sampling process.

## Proposed deliverables

- Reproducible split and exclusion manifests with dataset provenance.
- Row-level feature table and documented feature definitions.
- Saved preprocessing/model pipeline and an inference entry point accepting prompt, HTML, and URL metadata.
- Validation selection results, final test metrics, baseline comparisons, and calibration plot.
- Coefficient report and a few inspectable example predictions.
- README commands and targeted checks for split disjointness, feature consistency, and model save/load behavior.

## Decisions for the next iteration

1. Confirm hostname-disjoint evaluation as the primary deployment scenario.
2. Finalize snapshot-level versus URL-level quality exclusions and cross-host duplicate handling.
3. Freeze the initial feature list and the clean-subset definition.
4. Agree on the inference interface and report format before implementation.

This document is a proposed plan. Model implementation and training have not started.

## Repository references

- [Project brief](../project-brief.md)
- [Dataset and analysis summary](../README.md)
- [Existing HTML analysis report](brief-report.html)
- [Content extraction implementation](../scripts/analyze_content.py)
- [Sensitivity analysis implementation](../scripts/analyze_sensitivity.py)
