"""Select LR exclusively on validation loss; freeze the model before test evaluation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import warnings

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trad-ml-matplotlib")
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from lr_evaluation import metrics
from lr_features import FAMILIES, FEATURE_NAMES, FEATURE_VERSION, PAGE


def pipeline(c):
    return make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                         StandardScaler(), LogisticRegression(C=c, solver="lbfgs", max_iter=3000, random_state=42))


def save_plot(fig, output, name):
    fig.savefig(output / f"{name}.png", dpi=170, bbox_inches="tight")
    fig.savefig(output / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def response_grid(values):
    unique = np.unique(values[np.isfinite(values)])
    if len(unique) <= 2:
        return unique
    return np.unique(np.quantile(values[np.isfinite(values)], np.linspace(.05, .95, 19)))


def plot_response_curves(model, xt, xv, names, permutation, output):
    sensitivity = []
    top = [r["feature"] for r in permutation if np.unique(xt[:, names.index(r["feature"])][np.isfinite(xt[:, names.index(r["feature"])])]).size > 1][:6]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7.5))
    for ax, name in zip(axes.flat, top):
        j = names.index(name)
        finite = xt[np.isfinite(xt[:, j]), j]
        grid = response_grid(finite)
        probabilities = []
        for value in grid:
            changed = xv.copy()
            changed[:, j] = value
            probabilities.append(float(model.predict_proba(changed)[:, 1].mean()))
        ax.plot(grid, probabilities, color="#16836b", marker="o", markersize=3)
        ax.set(title=name, ylabel="Mean predicted P(top)", xlabel="Feature value (log1p where named)")
        sensitivity.append({"feature": name, "grid": grid.tolist(), "mean_probability": probabilities})
    for ax in list(axes.flat)[len(top):]:
        ax.set_visible(False)
    fig.suptitle("One-feature sensitivity on validation rows; training quantile grid; binary features use 0 and 1")
    fig.tight_layout()
    save_plot(fig, output, "sensitivity_curves")
    return sensitivity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/lr"))
    parser.add_argument("--output-dir", type=Path, default=Path("trad_ml_scorer"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.data_dir / "model.joblib"
    if model_path.exists() or (args.output_dir / "test_metrics.json").exists():
        raise FileExistsError("Frozen experiment exists; choose a new experiment directory")
    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    assert manifest["feature_names"] == FEATURE_NAMES
    assert hashlib.sha256((args.data_dir / "features.npz").read_bytes()).hexdigest() == manifest["features_sha256"]
    data = np.load(args.data_dir / "features.npz")
    train, val = data["splits"] == "train", data["splits"] == "validation"
    # Test labels and feature rows are never indexed during fitting or selection.
    x_train, y_train, x_val, y_val = data["X"][train], data["y"][train], data["X"][val], data["y"][val]
    host_val = data["hosts"][val]
    warnings.filterwarnings("error", category=ConvergenceWarning)
    candidates, fitted = [], {}
    variants = {"page_only": PAGE, "prompt_plus_page": FEATURE_NAMES}
    prevalence = float(y_train.mean())
    for variant, names in variants.items():
        indices = [FEATURE_NAMES.index(name) for name in names]
        for c in (.01, .1, 1., 10.):
            model = pipeline(c)
            model.fit(x_train[:, indices], y_train)
            p = model.predict_proba(x_val[:, indices])[:, 1]
            row = {"variant": variant, "C": c, "validation": metrics(y_val, p, host_val)}
            candidates.append(row)
            fitted[(variant, c)] = model
            print(f'{variant} C={c}: validation log loss={row["validation"]["log_loss"]:.6f}', flush=True)
    selected = min(candidates, key=lambda row: row["validation"]["log_loss"])
    names = variants[selected["variant"]]
    indices = [FEATURE_NAMES.index(name) for name in names]
    model = fitted[(selected["variant"], selected["C"])]
    xt, xv = x_train[:, indices], x_val[:, indices]
    bundle = {"pipeline": model, "feature_names": names, "feature_version": FEATURE_VERSION,
              "selection": selected, "train_prevalence": prevalence,
              "dataset_sha256": manifest["features_sha256"],
              "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__}}
    joblib.dump(bundle, model_path)
    restored = joblib.load(model_path)
    np.testing.assert_array_equal(model.predict_proba(xv), restored["pipeline"].predict_proba(xv))
    best_per_variant = {v: min([r for r in candidates if r["variant"] == v], key=lambda r: r["validation"]["log_loss"]) for v in variants}
    for variant, row in best_per_variant.items():
        joblib.dump({**bundle, "pipeline": fitted[(variant, row["C"])], "feature_names": variants[variant], "selection": row}, args.data_dir / f"{variant}.joblib")
    baseline = metrics(y_val, np.full(len(y_val), prevalence), host_val)
    report = {"selected": selected, "candidates": candidates, "best_per_variant": best_per_variant,
              "constant_validation": baseline, "selection_metric": "validation log loss",
              "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(), "versions": bundle["versions"]}
    (args.output_dir / "selection.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output_dir / "host_splits.json").write_text((args.data_dir / "host_splits.json").read_text())
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    transformed_names = model[0].get_feature_names_out(names).tolist()
    coefficients = model[-1].coef_[0]
    coeff_rows = [{"feature": name, "coefficient": float(weight), "odds_ratio_per_training_sd": float(np.exp(weight))} for name, weight in zip(transformed_names, coefficients)]
    coeff_rows.sort(key=lambda r: abs(r["coefficient"]), reverse=True)
    (args.output_dir / "coefficients.json").write_text(json.dumps({"intercept": float(model[-1].intercept_[0]), "features": coeff_rows}, indent=2) + "\n")
    ordered = list(reversed(coeff_rows))
    fig, ax = plt.subplots(figsize=(10, max(7, len(ordered) * .24)))
    ax.barh([r["feature"] for r in ordered], [r["coefficient"] for r in ordered], color=["#16836b" if r["coefficient"] >= 0 else "#b94c5d" for r in ordered])
    ax.axvline(0, color="#45546b", linewidth=.8)
    ax.set(xlabel="Change in log odds per training standard deviation", title="Final LR: standardized coefficients (including missing indicators)")
    save_plot(fig, args.output_dir, "coefficients")
    rng = np.random.default_rng(42)
    base_loss = log_loss(y_val, model.predict_proba(xv)[:, 1])
    permutation = []
    # Interpretation uses validation only, leaving the test evaluation untouched.
    for name in names:
        j = names.index(name)
        deltas = []
        for _ in range(30):
            changed = xv.copy()
            changed[:, j] = changed[rng.permutation(len(changed)), j]
            deltas.append(log_loss(y_val, model.predict_proba(changed)[:, 1]) - base_loss)
        permutation.append({"feature": name, "mean_log_loss_increase": float(np.mean(deltas)), "shuffle_sd": float(np.std(deltas))})
    permutation.sort(key=lambda r: r["mean_log_loss_increase"], reverse=True)
    fig, ax = plt.subplots(figsize=(10, max(7, len(names) * .24)))
    rows = list(reversed(permutation))
    ax.barh([r["feature"] for r in rows], [r["mean_log_loss_increase"] for r in rows], xerr=[r["shuffle_sd"] for r in rows], color="#327bb0", capsize=2)
    ax.axvline(0, color="#45546b", linewidth=.8)
    ax.set(xlabel="Validation log-loss increase after shuffle (mean ± shuffle SD)", title="Feature sensitivity: 30 validation permutations")
    save_plot(fig, args.output_dir, "permutation_importance")
    ablations = []
    for family, members in FAMILIES.items():
        kept = [i for i, name in enumerate(names) if name not in members]
        if len(kept) == len(names):
            continue
        ablated = pipeline(selected["C"])
        ablated.fit(xt[:, kept], y_train)
        loss = log_loss(y_val, ablated.predict_proba(xv[:, kept])[:, 1])
        ablations.append({"family": family, "validation_log_loss": float(loss), "delta": float(loss - base_loss)})
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.barh([r["family"] for r in ablations], [r["delta"] for r in ablations], color="#7559ad")
    ax.axvline(0, color="#45546b", linewidth=.8)
    ax.set(xlabel="Validation log-loss change when family is removed and LR refitted", title="Feature-family ablation (same C; diagnostic only)")
    save_plot(fig, args.output_dir, "family_ablation")
    sensitivity = plot_response_curves(model, xt, xv, names, permutation, args.output_dir)
    (args.output_dir / "sensitivity.json").write_text(json.dumps({"permutation": permutation, "family_ablation": ablations, "partial_dependence": sensitivity,
        "note": "Validation-only diagnostics, not used for further selection. Shuffle SD is not a confidence interval. Correlation may mask importance; one-feature perturbations can create implausible combinations. Not causal."}, indent=2) + "\n")
    print(json.dumps({"selected": selected, "model": str(model_path)}, indent=2))


if __name__ == "__main__":
    main()
