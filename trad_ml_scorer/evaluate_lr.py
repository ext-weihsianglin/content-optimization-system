"""One-shot held-out evaluation and visual report for a frozen LR model."""

import argparse
import base64
import csv
import hashlib
import html
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trad-ml-matplotlib")
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.metrics import RocCurveDisplay

from trad_ml_scorer.lr_evaluation import host_bootstrap, metrics
from trad_ml_scorer.lr_features import FEATURE_NAMES
from trad_ml_scorer.train_lr import save_plot


def build_report(output, selection, manifest, result):
    selected = result["models"]["selected"]
    m = selected["all"]
    ci = selected["host_bootstrap_95_percent"]["roc_auc"]
    lines = ["# Logistic Regression — Held-out Results", "", 
        f"Selected by validation log loss: **{selection['selected']['variant']}**, C={selection['selected']['C']}. The saved model is fitted on train only.", "",
        f"Test ROC-AUC: **{m['roc_auc']:.4f}** (95% host-bootstrap interval {ci['low']:.4f}–{ci['high']:.4f}); {m['rows']} rows across {m['hosts']} held-out hosts.", "",
        "## Split and leakage checks", "",
        "Seed 42; hostname-disjoint 80/10/10 split frozen before fitting. Exact duplicates, blank prompts, conflicting-label URLs, and HTML or nonempty normalized text shared across hosts are excluded. Clean-subset filtering is per snapshot.", "",
        "| Split | Rows | Hosts | Top labels | Clean rows |", "| --- | ---: | ---: | ---: | ---: |"]
    for split, counts in manifest["splits"].items():
        lines.append(f"| {split} | {counts['rows']} | {counts['hosts']} | {counts['positive']} | {counts['clean_rows']} |")
    lines += ["", "Zero cross-split overlap is required for hostname, URL, HTML hash, nonempty normalized extracted-text hash, and exact record hash. Preprocessing is fit on train only; C and feature variant are selected on validation only. Test results did not drive model changes.", "",
        f"Cross-split normalized prompt overlap (not an exclusion; this is an unseen-host evaluation): `{json.dumps(manifest['leakage_audit']['prompt_hash'])}`.", "",
        "## Held-out test metrics", "", "| Model / population | ROC-AUC | Log loss | Brier | Accuracy @ 0.5 | Within-host AUC |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, entry in result["models"].items():
        for population in ("all", "clean"):
            row = entry[population]
            if row["rows"]:
                lines.append(f"| {name} / {population} (n={row['rows']}) | {row['roc_auc']:.4f} | {row['log_loss']:.4f} | {row['brier_score']:.4f} | {row['accuracy_at_0_5']:.4f} | {row['mean_within_host_auc']:.4f} |")
    lines += ["", "The page-only and prompt-plus-page variants each use their validation-selected C. The selected row repeats the winning variant. The constant baseline uses training prevalence. Test comparisons are descriptive; they do not trigger reselection.", "", 
        "## Readiness", "",
        "The baseline demonstrates modest held-out discrimination above the constant and page-only baselines. Deployment acceptance criteria have not been specified. Unit tests and frozen-artifact verification cover split isolation, train-only preprocessing, serialization, and raw-snapshot inference consistency; see verification.json for the artifact checks.", "",
        "## Interpretation and limits", "",
        "The score predicts the sampled within-host top label among already-cited pages. It is not an absolute citation probability or a causal estimate of editing uplift. Calibration plots concern this balanced sample.", "",
        "Existing repository exploration examined the full dataset before this experiment. This is a retrospective holdout; it cannot be claimed to be untouched by all prior feature-design knowledge. Exact duplication checks do not prove absence of near duplicates, shared organizations, or related templates across different hosts.", "",
        "Coefficient bars show effects per training standard deviation after preprocessing. Permutation error bars are shuffle standard deviations, not confidence intervals. Correlated predictors can hide or redistribute importance. Ablations and response curves use validation data only and did not trigger a second search; one-feature perturbations can create unrealistic combinations and are not intervention estimates.", "", 
        "## Visual analysis", ""]
    notes = Path(__file__).with_name("lr_report_notes.md").read_text()
    glossary, next_round = notes.split("## Interesting and promising features for the next round", 1)
    # Place the glossary before charts and keep proposed next-round work last.
    lines[-2:] = glossary.strip().splitlines() + ["", "## Visual analysis", ""]
    descriptions = {
        "test_diagnostics": "Held-out ROC, calibration, and confusion matrix",
        "coefficients": "Final fitted model: full standardized coefficient breakdown",
        "permutation_importance": "Validation permutation feature sensitivity",
        "family_ablation": "Validation sensitivity to removing feature families",
        "sensitivity_curves": "Validation probability response to individual features",
    }
    for name, title in descriptions.items():
        lines += [f"### {title}", "", f"![{title}]({name}.png)", ""]
    lines += ["## Artifacts", "", "- `selection.json`: all validation candidates and frozen selection.", "- `test_metrics.json`: complete test metrics and host-bootstrap intervals.", "- `test_predictions.csv`: held-out record IDs, labels, predictions, and clean flags.", "- `dataset_manifest.json` and `host_splits.json`: provenance, cleanup counts, split assignments, and overlap audits.", "- `coefficients.json` and `sensitivity.json`: underlying chart values.", "- `verification.json`: frozen-artifact and raw-inference checks.", "- `example_predictions.json`: six train/validation examples with feature contributions.", "- `feature_definitions.md`: all 35 raw features and fitted transformations.", "- PNG and SVG versions of every chart.", "- Local model: `data/lr/model.joblib`; row-level data and exclusion manifest: `data/lr/` (ignored by Git).", "",
        "Only load joblib artifacts from trusted sources. The saved model requires the accompanying feature code and locked Python dependencies.", ""]
    lines += ["## Interesting and promising features for the next round", *next_round.splitlines()]
    (output / "report.md").write_text("\n".join(lines))
    # Standalone HTML embeds raster charts and escapes all text; Markdown remains portable.
    blocks = []
    table = []
    def flush_table():
        if table:
            header = "".join("<th>" + html.escape(c.strip()) + "</th>" for c in table[0].strip("|").split("|"))
            body = "".join("<tr>" + "".join("<td>" + html.escape(c.strip()) + "</td>" for c in r.strip("|").split("|")) + "</tr>" for r in table[2:])
            blocks.append('<div class="table"><table><thead><tr>' + header + "</tr></thead><tbody>" + body + "</tbody></table></div>")
            table.clear()
    for line in lines:
        if line.startswith("|"):
            table.append(line)
            continue
        flush_table()
        if not line:
            continue
        if line.startswith("!["):
            name = line.split("](")[1][:-1]
            encoded = base64.b64encode((output / name).read_bytes()).decode()
            blocks.append(f'<img alt="{html.escape(line[2:].split("]")[0])}" src="data:image/png;base64,{encoded}">')
        elif line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            blocks.append(f"<h{level}>" + html.escape(line[level:].strip()) + f"</h{level}>")
        else:
            blocks.append("<p>" + html.escape(line).replace("**", "").replace("`", "") + "</p>")
    flush_table()
    style = 'body{margin:0;background:#edf2f7;color:#213249;font:16px/1.65 system-ui,sans-serif}main{max-width:1120px;margin:32px auto;background:white;padding:40px 48px;border-radius:16px}h1{font-size:34px;color:#123b58}h2{margin-top:40px;border-top:1px solid #dce5ee;padding-top:24px}h3{margin-top:32px}img{width:100%;height:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;text-align:left;border-bottom:1px solid #dae3ed}th{background:#e9f1f8}.table{overflow:auto}p{overflow-wrap:anywhere}@media(max-width:700px){main{margin:0;padding:20px;border-radius:0}h1{font-size:27px}}'
    (output / "report.html").write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LR held-out results</title><style>' + style + '</style></head><body><main>' + "".join(blocks) + '</main></body></html>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/lr"))
    parser.add_argument("--output-dir", type=Path, default=Path("trad_ml_scorer/v1"))
    parser.add_argument("--report-only", action="store_true", help="Rebuild HTML/Markdown from saved results without reevaluation")
    args = parser.parse_args()
    output = args.output_dir
    if args.report_only:
        build_report(output, json.loads((output / "selection.json").read_text()),
                     json.loads((output / "dataset_manifest.json").read_text()),
                     json.loads((output / "test_metrics.json").read_text()))
        return
    if (output / "test_metrics.json").exists():
        raise FileExistsError("Test evaluation already exists; retain the frozen result")
    selection = json.loads((output / "selection.json").read_text())
    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    assert hashlib.sha256((args.data_dir / "model.joblib").read_bytes()).hexdigest() == selection["model_sha256"]
    assert hashlib.sha256((args.data_dir / "features.npz").read_bytes()).hexdigest() == manifest["features_sha256"]
    data = np.load(args.data_dir / "features.npz")
    mask = data["splits"] == "test"
    x, y, hosts, clean = data["X"][mask], data["y"][mask], data["hosts"][mask], data["clean"][mask]
    probabilities = {}
    for name, filename in (("selected", "model.joblib"), ("page_only", "page_only.joblib"), ("prompt_plus_page", "prompt_plus_page.joblib")):
        bundle = joblib.load(args.data_dir / filename)
        assert bundle["dataset_sha256"] == manifest["features_sha256"]
        columns = [FEATURE_NAMES.index(f) for f in bundle["feature_names"]]
        probabilities[name] = bundle["pipeline"].predict_proba(x[:, columns])[:, 1]
    probabilities["constant"] = np.full(len(y), bundle["train_prevalence"])
    result = {"model_sha256": selection["model_sha256"], "threshold": .5, "models": {}}
    for name, p in probabilities.items():
        result["models"][name] = {"all": metrics(y, p, hosts), "clean": metrics(y[clean], p[clean], hosts[clean])}
    result["models"]["selected"]["host_bootstrap_95_percent"] = host_bootstrap(y, probabilities["selected"], hosts)
    with (output / "test_predictions.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(["record_id", "hostname", "is_cited_high", "clean", *probabilities])
        for i, record_id in enumerate(data["ids"][mask]):
            writer.writerow([record_id, hosts[i], y[i], int(clean[i]), *[p[i] for p in probabilities.values()]])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    for name in ("selected", "page_only", "constant"):
        RocCurveDisplay.from_predictions(y, probabilities[name], name=name, ax=axes[0])
    axes[0].plot([0, 1], [0, 1], "--", color="#888888")
    axes[0].set_title("Held-out ROC")
    observed, predicted = calibration_curve(y, probabilities["selected"], n_bins=8, strategy="quantile")
    axes[1].plot(predicted, observed, "o-", color="#16836b")
    axes[1].plot([0, 1], [0, 1], "--", color="#888888")
    axes[1].set(xlabel="Mean predicted probability", ylabel="Observed top-label fraction", title="Test calibration (8 quantile bins)", xlim=(0, 1), ylim=(0, 1))
    matrix = np.array(result["models"]["selected"]["all"]["confusion_matrix"])
    axes[2].imshow(matrix, cmap="Blues")
    for (i, j), count in np.ndenumerate(matrix):
        axes[2].text(j, i, str(count), ha="center", va="center", color="white" if count > matrix.max() * .6 else "black", fontsize=16)
    axes[2].set(xticks=[0, 1], yticks=[0, 1], xticklabels=["bottom", "top"], yticklabels=["bottom", "top"], xlabel="Predicted", ylabel="Actual", title="Test confusion matrix (threshold 0.5)")
    fig.tight_layout()
    save_plot(fig, output, "test_diagnostics")
    (output / "test_metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    build_report(output, selection, manifest, result)
    print(json.dumps(result["models"]["selected"], indent=2))


if __name__ == "__main__":
    main()
