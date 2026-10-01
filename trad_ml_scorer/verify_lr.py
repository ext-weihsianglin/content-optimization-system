"""Verify frozen artifacts and raw-HTML inference parity without refitting models."""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np

from trad_ml_scorer.lr_features import FEATURE_NAMES, extract_features, predict
from trad_ml_scorer.prepare_lr_data import leakage_audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--data-dir", type=Path, default=Path("data/lr"))
    parser.add_argument("--output-dir", type=Path, default=Path("trad_ml_scorer/v1"))
    args = parser.parse_args()
    records = [json.loads(line) for line in (args.data_dir / "records.jsonl").read_text().splitlines()]
    manifest = json.loads((args.data_dir / "manifest.json").read_text())
    selection = json.loads((args.output_dir / "selection.json").read_text())
    bundle = joblib.load(args.data_dir / "model.joblib")
    data = np.load(args.data_dir / "features.npz")
    assert leakage_audit(records) == manifest["leakage_audit"]
    assert hashlib.sha256((args.data_dir / "features.npz").read_bytes()).hexdigest() == bundle["dataset_sha256"]
    assert hashlib.sha256((args.data_dir / "model.joblib").read_bytes()).hexdigest() == selection["model_sha256"]
    assert selection["selected"] == min(selection["candidates"], key=lambda r: r["validation"]["log_loss"])
    columns = [FEATURE_NAMES.index(f) for f in bundle["feature_names"]]
    xt = data["X"][data["splits"] == "train"][:, columns]
    model = bundle["pipeline"]
    expected_medians = np.nanmedian(xt, axis=0)
    expected_medians[np.isnan(expected_medians)] = 0
    np.testing.assert_allclose(model[0].statistics_, expected_medians)
    np.testing.assert_allclose(model[1].mean_, model[0].transform(xt).mean(axis=0))
    assert int(model[1].n_samples_seen_) == len(xt)
    assert bundle["selection"] == selection["selected"]
    con = duckdb.connect()
    eligible = {r["record_id"]: r for r in records if not r["exclusions"]}
    examples = []
    for split in ("train", "validation"):
        for index in np.flatnonzero(data["splits"] == split)[:3]:
            record = eligible[data["ids"][index]]
            path = args.input_dir / record["source_file"]
            raw = con.execute("SELECT prompt, html_content, href FROM read_parquet(?, file_row_number=true) WHERE file_row_number=?", [str(path), record["source_row"]]).fetchone()
            actual = extract_features(*raw)
            np.testing.assert_allclose([actual[f] for f in FEATURE_NAMES], data["X"][index], equal_nan=True)
            predicted = predict(bundle, *raw)
            expected = model.predict_proba(data["X"][index:index + 1, columns])[0, 1]
            np.testing.assert_allclose(predicted, expected, atol=1e-12)
            transformed = model[:-1].transform(data["X"][index:index + 1, columns])[0]
            contributions = transformed * model[-1].coef_[0]
            names = model[0].get_feature_names_out(bundle["feature_names"])
            ranked = sorted(zip(names, contributions), key=lambda pair: abs(pair[1]), reverse=True)
            examples.append({"record_id": record["record_id"], "split": split, "prompt": raw[0], "url": raw[2], "is_cited_high": int(data["y"][index]), "predicted_probability": predicted,
                             "intercept": float(model[-1].intercept_[0]), "top_log_odds_contributions": [{"feature": str(name), "contribution": float(value)} for name, value in ranked[:8]]})
    (args.output_dir / "example_predictions.json").write_text(json.dumps(examples, indent=2) + "\n")
    result = {"checks": ["zero hostname/URL/HTML/nonempty-text/record overlap", "dataset and model hashes match frozen selection", "selection minimizes validation log loss", "imputer statistics match training data only", "scaler statistics and sample count match training data only", "six raw-snapshot feature and saved-model inference parity checks"], "raw_parity_examples": len(examples), "status": "passed"}
    (args.output_dir / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
