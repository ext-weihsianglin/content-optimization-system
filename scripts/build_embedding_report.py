"""Build the standalone explorer from saved projections without API calls."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from representations.report import build_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", default="analysis/embedding-explorer.html")
    args = parser.parse_args()
    print(build_report(args.run, args.output))
