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
    status = sub.add_parser("cache-status")
    status.add_argument("--cache-root")
    backup = sub.add_parser("cache-backup")
    backup.add_argument("--cache-root", required=True)
    backup.add_argument("--output", required=True)
    reuse = sub.add_parser("reuse-inputs")
    reuse.add_argument("--run", required=True)
    reuse.add_argument("--output", required=True)
    reuse.add_argument("--config")
    scale = sub.add_parser("scale")
    scale.add_argument("--run", required=True)
    scale.add_argument("--output", required=True)
    scale.add_argument("--voyage-tokenizer", required=True)
    scale.add_argument("--tokenizer-revision")
    scale.add_argument("--cache-root")
    for name in ("embed", "align", "project", "apply", "review", "evaluate", "report", "analyze"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run", required=True)
        if name not in {"review", "report"}:
            cmd.add_argument("--model", default="openai-large")
        if name == "embed":
            cmd.add_argument("--cache-root", help="Shared SQLite/shard store; default is the main checkout data directory")
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
        elif args.command == "cache-status":
            from .cache import cache_status, default_cache_root
            result = cache_status(args.cache_root or default_cache_root('.'))
        elif args.command == "cache-backup":
            from .cache import backup_cache
            result = backup_cache(args.cache_root, args.output)
        elif args.command == "reuse-inputs":
            from .inputs import reuse_inputs
            result = reuse_inputs(args.run, args.output, load_config(args.config))
            result = {k:result[k] for k in ("units", "records", "scope")}
        elif args.command == "scale":
            from .scale import measure
            result = measure(args.run, args.output, voyage_tokenizer=args.voyage_tokenizer,
                             tokenizer_revision=args.tokenizer_revision, cache_root=args.cache_root)
        elif args.command == "embed":
            from .runner import embed
            result = embed(args.run, args.model, resume=args.resume, retry_failed=args.retry_failed, max_requests=args.max_requests, cache_root=args.cache_root)
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
