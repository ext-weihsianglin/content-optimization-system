"""CLI; preparing and reviewing inputs never calls an embedding service."""

import argparse
import json
import sys

from .config import load_config
from .providers import ProviderError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--input", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--config")
    prepare.add_argument("--raw-root")
    prepare.add_argument("--limit", type=int)
    for name in ("embed", "align", "project", "apply", "review", "evaluate", "report", "analyze"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run", required=True)
        if name not in {"review", "report"}:
            cmd.add_argument("--model", default="openai-large")
        if name == "embed":
            cmd.add_argument("--resume", action="store_true")
            cmd.add_argument("--retry-failed", action="store_true")
            cmd.add_argument("--max-requests", type=int)
        if name == "project":
            cmd.add_argument("--view", choices=["page", "path", "query", "outline", "title", "section"], default="page")
            cmd.add_argument("--components", type=int, default=32)
            cmd.add_argument("--fit-manifest")
            cmd.add_argument("--exploratory", action="store_true")
            cmd.add_argument("--umap", action="store_true")
        if name == "apply":
            cmd.add_argument("--projection", required=True)
        if name in {"apply", "review", "evaluate", "report", "analyze"}:
            cmd.add_argument("--output", required=True)
        if name == "review":
            cmd.add_argument("--cases", type=int, default=120)
        if name == "evaluate":
            cmd.add_argument("--annotations", required=True)
            cmd.add_argument("--split", choices=["development", "heldout"], default="heldout")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            from .inputs import prepare
            result = prepare(args.input, args.output, load_config(args.config), raw_root=args.raw_root, limit=args.limit)
            result = {k: result[k] for k in ("units", "records", "views", "statuses", "scope")}
        elif args.command == "embed":
            from .runner import embed
            result = embed(args.run, args.model, resume=args.resume, retry_failed=args.retry_failed, max_requests=args.max_requests)
        elif args.command == "align":
            from .alignment import align
            result = align(args.run, args.model)
        elif args.command == "project":
            from .projection import project
            result = project(args.run, args.model, args.view, args.components, fit_manifest=args.fit_manifest, exploratory=args.exploratory, umap=args.umap)
        elif args.command == "apply":
            from .projection import apply_pca
            apply_pca(args.run, args.model, args.projection, args.output)
            result = {"output": args.output}
        elif args.command == "review":
            from .evaluation import review_manifest
            result = review_manifest(args.run, args.output, args.cases)
        elif args.command == "evaluate":
            from .evaluation import evaluate
            result = evaluate(args.run, args.model, args.annotations, args.output, args.split)
        elif args.command == "analyze":
            from .analysis import analyze
            result = analyze(args.run, args.model, args.output)
        else:
            from .report import build_report
            result = build_report(args.run, args.output)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, KeyError, FileNotFoundError, ProviderError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
