"""Fit and freeze retention LR; evaluate separately on the explicitly reused benchmark."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import warnings

import joblib
import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning

from trad_ml_scorer.diagnostics import write_diagnostics
from trad_ml_scorer.lr_evaluation import metrics, host_bootstrap
from trad_ml_scorer.lr_features import FEATURE_NAMES as V1_NAMES, FEATURE_VERSION as V1_VERSION
from trad_ml_scorer.retention_features import FEATURE_NAMES, FEATURE_VERSION, WHOLE_NAMES, FAMILIES
from trad_ml_scorer.train_lr import pipeline


def fit_variant(x, y, hosts, splits, names, eligible):
    train = (splits == "train") & eligible
    val = (splits == "validation") & eligible
    candidates, models = [], []
    for c in (.01, .1, 1., 10.):
        model = pipeline(c).fit(x[train], y[train])
        row = {"C": c, "validation": metrics(y[val], model.predict_proba(x[val])[:, 1], hosts[val])}
        candidates.append(row)
        models.append(model)
    index = min(range(len(candidates)), key=lambda i: candidates[i]["validation"]["log_loss"])
    return models[index], candidates[index], candidates


def train(data_dir, output, data, manifest):
    if (output / "selection.json").exists() or (data_dir / "model.joblib").exists():
        raise FileExistsError("Frozen v2 experiment already exists")
    warnings.filterwarnings("error", category=ConvergenceWarning)
    x, y, hosts, splits = (data[k] for k in ("X", "y", "hosts", "splits"))
    common = data["common"]
    configurations = {
        "retention_whole": (WHOLE_NAMES, np.ones(len(y), dtype=bool), x[:, [FEATURE_NAMES.index(f) for f in WHOLE_NAMES]], FEATURE_VERSION),
        "retention_sections": (FEATURE_NAMES, np.ones(len(y), dtype=bool), x, FEATURE_VERSION),
        "v1_common": (V1_NAMES, common, data["X_v1"], V1_VERSION),
        "retention_whole_common": (WHOLE_NAMES, common, x[:, [FEATURE_NAMES.index(f) for f in WHOLE_NAMES]], FEATURE_VERSION),
        "retention_sections_common": (FEATURE_NAMES, common, x, FEATURE_VERSION),
    }
    registry = {}
    for name, (names, eligible, matrix, version) in configurations.items():
        model, selected, candidates = fit_variant(matrix, y, hosts, splits, names, eligible)
        row = {"variant": name, **selected, "candidates": candidates, "feature_names": names, "train_rows": int(((splits == "train") & eligible).sum()), "validation_rows": int(((splits == "validation") & eligible).sum())}
        bundle = {"pipeline": model, "feature_names": names, "feature_version": version, "selection": row,
                  "dataset_sha256": manifest["features_sha256"], "parser_policy": "retention-first-v1" if version == FEATURE_VERSION else "v1-main-content",
                  "parser_hashes": manifest["code_hashes"] if version == FEATURE_VERSION else {},
                  "train_prevalence": float(y[(splits == "train") & eligible].mean()),
                  "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__}}
        model_file = data_dir / f"{name}.joblib"
        joblib.dump(bundle, model_file)
        validation_matrix = matrix[(splits == "validation") & eligible]
        np.testing.assert_array_equal(model.predict_proba(validation_matrix), joblib.load(model_file)["pipeline"].predict_proba(validation_matrix))
        row["model_sha256"] = hashlib.sha256(model_file.read_bytes()).hexdigest()
        registry[name] = row
        print(f'{name}: C={selected["C"]} validation AUC={selected["validation"]["roc_auc"]:.4f}, loss={selected["validation"]["log_loss"]:.5f}', flush=True)
    selected_name = min(("retention_whole", "retention_sections"), key=lambda name: registry[name]["validation"]["log_loss"])
    # Byte-for-byte copy of the validation winner; no train+validation refit.
    (data_dir / "model.joblib").write_bytes((data_dir / f"{selected_name}.joblib").read_bytes())
    selection = {"selected_name": selected_name, "selected": registry[selected_name], "models": registry,
                 "selection_rule": "Choose C and whole vs section variant by validation log loss on v2 eligible population; common-population models are diagnostics only",
                 "test_status": manifest["test_status"], "dataset_sha256": manifest["features_sha256"],
                 "v1_frozen_model_sha256": hashlib.sha256(Path("data/lr/model.joblib").read_bytes()).hexdigest() if Path("data/lr/model.joblib").exists() else None}
    (output / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    (output / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "host_splits.json").write_text((data_dir / "host_splits.json").read_text())
    chosen = joblib.load(data_dir / "model.joblib")
    names = chosen["feature_names"]
    matrix = x[:, [FEATURE_NAMES.index(f) for f in names]]
    write_diagnostics(chosen["pipeline"], matrix[splits == "train"], y[splits == "train"], matrix[splits == "validation"], y[splits == "validation"], names, registry[selected_name]["C"], FAMILIES, output)


def evaluate(data_dir, output, data, manifest):
    if (output / "test_metrics.json").exists():
        raise FileExistsError("Reused benchmark already evaluated; do not retune on it")
    selection = json.loads((output / "selection.json").read_text())
    x, y, hosts, splits = (data[k] for k in ("X", "y", "hosts", "splits"))
    result = {"benchmark_status": manifest["test_status"], "selected_name": selection["selected_name"], "models": {}}
    predictions = []
    for name, entry in selection["models"].items():
        path = data_dir / f"{name}.joblib"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["model_sha256"]
        bundle = joblib.load(path)
        assert bundle["dataset_sha256"] == manifest["features_sha256"]
        eligible = data["common"] if name.endswith("_common") else np.ones(len(y), dtype=bool)
        mask = (splits == "test") & eligible
        matrix = data["X_v1"] if name == "v1_common" else x[:, [FEATURE_NAMES.index(f) for f in bundle["feature_names"]]]
        probability = bundle["pipeline"].predict_proba(matrix[mask])[:, 1]
        entry_metrics = {"all": metrics(y[mask], probability, hosts[mask]), "clean": metrics(y[mask][data["clean"][mask]], probability[data["clean"][mask]], hosts[mask][data["clean"][mask]])}
        if name == selection["selected_name"]:
            entry_metrics["host_bootstrap_95_percent"] = host_bootstrap(y[mask], probability, hosts[mask])
        result["models"][name] = entry_metrics
        for i, p in zip(np.flatnonzero(mask), probability):
            predictions.append({"variant": name, "record_id": str(data["ids"][i]), "hostname": str(hosts[i]), "is_cited_high": int(y[i]), "probability": float(p), "clean": bool(data["clean"][i])})
    train_mask, test_mask = splits == "train", splits == "test"
    result["constant"] = metrics(y[test_mask], np.full(test_mask.sum(), y[train_mask].mean()), hosts[test_mask])
    with (output / "test_predictions.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(predictions[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(predictions)
    (output / "test_metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/trad_ml_scorer/v2"))
    parser.add_argument("--output-dir", type=Path, default=Path("trad_ml_scorer/v2"))
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    assert manifest["feature_names"] == FEATURE_NAMES
    assert hashlib.sha256((args.data_dir / "features.npz").read_bytes()).hexdigest() == manifest["features_sha256"]
    with np.load(args.data_dir / "features.npz") as data:
        if args.evaluate:
            evaluate(args.data_dir, args.output_dir, data, manifest)
        else:
            train(args.data_dir, args.output_dir, data, manifest)


if __name__ == "__main__":
    main()
