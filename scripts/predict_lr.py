"""Score a local HTML snapshot with the frozen model."""

import argparse
import json
from pathlib import Path

import joblib

from lr_features import predict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("data/lr/model.joblib"))
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--html-file", type=Path, required=True)
    parser.add_argument("--url", default="")
    args = parser.parse_args()
    score = predict(joblib.load(args.model), args.prompt, args.html_file.read_text(), args.url)
    print(json.dumps({"p_is_cited_high": score, "interpretation": "Probability of the sampled within-host top class among already-cited pages"}, indent=2))


if __name__ == "__main__":
    main()
