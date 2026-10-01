"""CLI for the frozen offline extraction benchmark."""

import argparse

from preprocessing.runner import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--manifest", default="evaluation/extraction/manifest.json")
    runner.add_argument("--output", default="data/processed/eval-v1")
    runner.add_argument("--config", default="preprocessing/config.json")
    runner.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    runner.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
