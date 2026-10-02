"""Score a local HTML snapshot with the frozen model."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib

from trad_ml_scorer.lr_features import predict, FEATURE_VERSION as V1_VERSION
from trad_ml_scorer.retention_features import predict_retention, FEATURE_VERSION as V2_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("data/trad_ml_scorer/v2/model.joblib"))
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--html-file", type=Path, required=True)
    parser.add_argument("--url", default="")
    args = parser.parse_args()
    bundle = joblib.load(args.model)
    if bundle["feature_version"] == V2_VERSION:
        root = Path(__file__).resolve().parents[1]
        for filename, expected in bundle["parser_hashes"].items():
            if filename.startswith("preprocessing/") or filename.endswith("retention_features.py"):
                local_path = root / "trad_ml_scorer/retention_features.py" if filename.endswith("retention_features.py") else root / filename
                if hashlib.sha256(local_path.read_bytes()).hexdigest() != expected:
                    raise ValueError(f"Parser or feature code changed since model fitting: {filename}")
        result = predict_retention(bundle, args.prompt, args.html_file.read_text(), args.url)
    elif bundle["feature_version"] in ("lr-frontier-v4", "lr-evidence-v5"):
        from trad_ml_scorer.predict_frontier import predict_frontier
        result = predict_frontier(bundle, args.prompt, args.html_file.read_text(), args.url)
    elif bundle["feature_version"] == V1_VERSION:
        result = {"p_is_cited_high": predict(bundle, args.prompt, args.html_file.read_text(), args.url), "feature_version": V1_VERSION}
    else:
        raise ValueError("Unknown model feature version")
    result["interpretation"] = "Probability of the sampled within-host top class among already-cited pages"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
