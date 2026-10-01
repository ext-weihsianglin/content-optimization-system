"""Validation-only coefficient, permutation, ablation, and response diagnostics."""

import json
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import log_loss
from trad_ml_scorer.train_lr import pipeline, save_plot, plot_response_curves


def write_diagnostics(model, xt, y_train, xv, y_val, names, c, families, output):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    transformed_names = model[0].get_feature_names_out(names).tolist()
    coefficients = model[-1].coef_[0]
    coeff_rows = [{"feature": name, "coefficient": float(weight), "odds_ratio_per_training_sd": float(np.exp(weight))} for name, weight in zip(transformed_names, coefficients)]
    coeff_rows.sort(key=lambda r: abs(r["coefficient"]), reverse=True)
    (output / "coefficients.json").write_text(json.dumps({"intercept": float(model[-1].intercept_[0]), "features": coeff_rows}, indent=2) + "\n")
    ordered = list(reversed(coeff_rows))
    fig, ax = plt.subplots(figsize=(10, max(7, len(ordered) * .24)))
    ax.barh([r["feature"] for r in ordered], [r["coefficient"] for r in ordered], color=["#16836b" if r["coefficient"] >= 0 else "#b94c5d" for r in ordered])
    ax.axvline(0, color="#45546b", linewidth=.8)
    ax.set(xlabel="Change in log odds per training standard deviation", title="Final LR: standardized coefficients (including missing indicators)")
    save_plot(fig, output, "coefficients")
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
    save_plot(fig, output, "permutation_importance")
    ablations = []
    for family, members in families.items():
        kept = [i for i, name in enumerate(names) if name not in members]
        if len(kept) == len(names):
            continue
        ablated = pipeline(c)
        ablated.fit(xt[:, kept], y_train)
        loss = log_loss(y_val, ablated.predict_proba(xv[:, kept])[:, 1])
        ablations.append({"family": family, "validation_log_loss": float(loss), "delta": float(loss - base_loss)})
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.barh([r["family"] for r in ablations], [r["delta"] for r in ablations], color="#7559ad")
    ax.axvline(0, color="#45546b", linewidth=.8)
    ax.set(xlabel="Validation log-loss change when family is removed and LR refitted", title="Feature-family ablation (same C; diagnostic only)")
    save_plot(fig, output, "family_ablation")
    sensitivity = plot_response_curves(model, xt, xv, names, permutation, output)
    (output / "sensitivity.json").write_text(json.dumps({"permutation": permutation, "family_ablation": ablations, "partial_dependence": sensitivity,
        "note": "Validation-only diagnostics, not used for further selection. Shuffle SD is not a confidence interval. Correlation may mask importance; one-feature perturbations can create implausible combinations. Not causal."}, indent=2) + "\n")
