# Traditional ML scorer

The default scorer is **v2**, backed by the retention-first parser in `preprocessing/`. All LR-specific Python modules, report templates, plans, and results live here. Run commands from the repository root with `python -m trad_ml_scorer.<module>` so imports resolve consistently.

## Layout

- `retention_features.py`: document-contract features and retention inference.
- `prepare_retention.py`: full-corpus parsing, exact snapshot joins, preserved hostname assignments, eligibility and overlap audit.
- `retention_experiment.py`: validation-only model selection and separate reused-benchmark evaluation.
- `predict_lr.py`: default v2 inference; accepts an explicitly supplied v1 model.
- `verify_retention.py`: artifact, split, preprocessing, and raw-document-feature parity checks.
- `build_retention_report.py`, `diagnostics.py`: portable visual reports and validation sensitivity analysis.
- `v2/`: current report, metrics, plots, provenance, and example predictions.
- `v1/`: preserved historical results from the original main-content extractor.
- `lr_features.py`, `prepare_lr_data.py`, `train_lr.py`, `evaluate_lr.py`, `verify_lr.py`: legacy v1 reproduction.
- `plan.md`, `plan.html`: original approved v1 plan.

The original analysis helpers remain in `scripts/`; v2 shares only their lexical tokenization/coverage and fixed URL-pattern utilities. Page content and metadata always come from the retention document. The retained text is not run through v1 cleaning afterward.

## Run v2

```sh
uv sync --locked
uv run python -m trad_ml_scorer.prepare_retention --input-dir data/raw --workers 4
uv run python -m trad_ml_scorer.retention_experiment --output-dir data/trad_ml_scorer/v2/report
uv run python -m trad_ml_scorer.retention_experiment --evaluate --output-dir data/trad_ml_scorer/v2/report
uv run python -m trad_ml_scorer.verify_retention --input-dir data/raw --output-dir data/trad_ml_scorer/v2/report
uv run python -m trad_ml_scorer.build_retention_report --output-dir data/trad_ml_scorer/v2/report
```

The supplied worktree run uses `--input-dir ../../data/raw`. Preparation requires the v1 feature/split artifacts in `data/lr/` for exact common-population comparisons. In a fresh checkout, generate those first with `uv run python -m trad_ml_scorer.prepare_lr_data --input-dir data/raw`; use the committed `v1/host_splits.json` to verify the seed-42 hostname assignment. For v1 model reproduction, run `train_lr --output-dir data/lr/report` then `evaluate_lr --output-dir data/lr/report`. `verify_retention` additionally checks any local v1 model supplied at the start of v2 fitting against its recorded hash. The reproduction commands above write reports under ignored data directories to preserve the committed historical reports; open `data/trad_ml_scorer/v2/report/report.html` afterward.

Intermediate artifacts and trained models are ignored under `data/trad_ml_scorer/v2/`: compressed per-snapshot documents, record/exclusion JSONL, feature arrays, models, and fingerprints. Full source payloads remain in the original Parquet files. Each document records a hashed Parquet-row reference, rather than assuming an evaluation-only text file exists. Multiple prompt/label records can reference one exact document. No label or query enters parsing.

Preparation is resumable with `--resume` only when its source/code fingerprints match. It refuses to replace a completed dataset; fitting and evaluation similarly guard frozen outputs. Use explicit new directories for a new experiment. Each snapshot has a 120-second parser timeout; failures are recorded and never silently replaced by a different parser.

## Score a page

```sh
uv run python -m trad_ml_scorer.predict_lr \
  --prompt "How to choose running shoes" \
  --html-file /path/to/page.html \
  --url https://example.com/shoes
```

The default model is `data/trad_ml_scorer/v2/model.joblib`. Pass `--model data/lr/model.joblib` explicitly for v1. Load only trusted joblib files. V2 verifies parser/feature fingerprints and returns the retention selection status alongside the probability. Missing usable content produces an abstention, not a fallback score.

## Evaluation contract

V1 host assignments remain fixed. All imputation, scaling, and fitting use training rows; the small regularization grid and whole-document versus section-feature choice use validation loss. The primary winner is selected from the v2 population. Separate v1/v2 common-population models are refit and tuned on exactly the same common development rows to distinguish representation changes from eligibility changes.

The test hosts were already evaluated for v1. V2 results are a **reused historical benchmark**, not a fresh independent test; new hosts or new data are needed for independent confirmation. The common-population comparison changes both parser representation and some feature definitions, so it is not a pure causal parser ablation. Quality-based subset definitions also differ between versions and are documented.

## Checks

```sh
uv run python -m pytest tests/test_lr.py tests/test_retention_scorer.py -q
uv run python -m pytest -q
```

The repository-wide suite additionally requires the existing Node preprocessing dependencies (`npm ci --prefix preprocessing/node --ignore-scripts`). Tests cover source identity, structured feature counts, native Markdown, no fallback on unusable content, train-only transformations, and model serialization.
