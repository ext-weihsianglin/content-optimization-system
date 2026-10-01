"""Offline supplemental Reader-LM report; never calls an inference endpoint."""

import argparse
from collections import Counter
import hashlib
import ipaddress
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from preprocessing.evaluate import (
    LIMITATIONS, METHODS, SEMANTICS_VERSION, STATUSES, _aggregate, _index, _score,
)
from preprocessing.report import _anchor_summary, _escape, _json, _number, _percent, _preview, _table
from preprocessing.schema import stable_hash


CONTEXT = (
    "Supplemental add-on benchmark conducted AFTER the original heldout results were known. "
    "This is NOT a prospective blind selection experiment or a fresh holdout. "
    "Reader-LM uses a constrained input/output model run; truncation and output caps can affect anchor retention. "
    "The report makes no endpoint requests and loads no external assets."
)


def _validate_endpoints(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"endpoint", "base_url", "server_url", "api_base"} and item:
                parsed = urlsplit(str(item))
                host = parsed.hostname
                try:
                    local = host == "localhost" or ipaddress.ip_address(host).is_loopback
                except ValueError:
                    local = False
                if parsed.scheme not in {"http", "https"} or not local or parsed.username or parsed.password:
                    raise ValueError("Declared inference endpoint must be localhost/loopback")
            _validate_endpoints(item)
    elif isinstance(value, list):
        for item in value:
            _validate_endpoints(item)


def _resources(results):
    supported = [row for row in results if row["status"] != "unsupported_format"]
    summary = {"recorded_attempts": len(supported)}
    for field in ("input_truncated", "output_capped"):
        values = [row.get("diagnostics", {}).get(field) for row in supported]
        summary[field] = {"true": sum(value is True for value in values),
                          "false": sum(value is False for value in values),
                          "unknown": sum(not isinstance(value, bool) for value in values)}
    for field in ("source_tokens", "input_tokens", "output_tokens"):
        values = []
        for row in supported:
            diagnostics = row.get("diagnostics", {})
            value = diagnostics.get(field)
            if field == "output_tokens" and value is None:
                value = (diagnostics.get("usage") or {}).get("completion_tokens")
            values.append(value)
        valid = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and value >= 0]
        summary[field] = {"count": len(valid), "unknown": len(values) - len(valid),
                          "total": sum(valid) if valid else None, "max": max(valid, default=None)}
    summary["finish_reason_counts"] = dict(Counter(
        str(row.get("diagnostics", {}).get("finish_reason") or "unknown") for row in supported))
    return summary


def evaluate_reader(manifest, annotations, results, original_metrics, run_manifest, allow_partial=False):
    """Reuse frozen matching/aggregation, retaining missing rows in partial runs."""
    _validate_endpoints(run_manifest)
    if annotations.get("annotation_type") != "ai_source_only":
        raise ValueError("Expected source-only AI annotations")
    if original_metrics.get("semantics_version") != SEMANTICS_VERSION:
        raise ValueError("Original metrics use different scoring semantics")
    snapshots = _index(manifest["snapshots"], lambda row: row["snapshot_id"], "snapshot")
    documents = _index(annotations["documents"], lambda row: row["snapshot_id"], "annotation")
    if set(documents) != set(snapshots):
        raise ValueError("Frozen annotations must cover exactly the evaluation manifest")
    for source in snapshots.values():
        if source["split"] not in {"dev", "heldout"}:
            raise ValueError("Invalid split")
    if any(not isinstance(row["evaluable"], bool) for row in documents.values()):
        raise ValueError("Annotation evaluable must be boolean")
    candidates = _index(results, lambda row: row["snapshot_id"], "reader result")
    for identity, row in candidates.items():
        if identity not in snapshots or row["method"] != "reader_lm" or row["status"] not in STATUSES:
            raise ValueError("Invalid Reader-LM result identity/method/status")
        if snapshots[identity]["format"] != "html" and row["status"] != "unsupported_format":
            raise ValueError("Non-HTML sources require explicit unsupported_format")
        _validate_endpoints(row.get("diagnostics", {}))
        if "run_identity" in run_manifest and row.get("run_identity") != run_manifest["run_identity"]:
            raise ValueError("Mixed or missing Reader-LM run identity")
    missing = sorted(set(snapshots) - set(candidates))
    if missing and not allow_partial:
        raise ValueError(f"Incomplete Reader-LM run: {len(missing)} missing outcomes; use --allow-partial")
    original_rows = _index(original_metrics["per_document"], lambda row: (row["snapshot_id"], row["method"]), "original score")
    expected = {(identity, method) for identity in snapshots for method in METHODS}
    if set(original_rows) != expected or any(not row["result_present"] for row in original_rows.values()):
        raise ValueError("Original metrics must contain complete outcomes for all five methods")
    for (identity, method), row in original_rows.items():
        if any(row[key] != snapshots[identity][key] for key in ("split", "stratum", "format", "hostname")):
            raise ValueError("Original metrics population differs from manifest")
        for field in ("required", "unwanted"):
            reference = _score(snapshots[identity], documents[identity], None, method)
            if row[f"{field}_count"] != reference[f"{field}_count"]:
                raise ValueError("Original annotation denominators differ")
    baselines = {identity: original_rows[(identity, "baseline")] for identity in snapshots}
    scored = [_score(source, documents[identity], candidates.get(identity), "reader_lm")
              for identity, source in sorted(snapshots.items())]
    groups = []
    for split in ("dev", "heldout"):
        for subset in ("all", "html", "native_non_html"):
            subset_rows = [row for row in scored if row["split"] == split and
                           (subset == "all" or (row["format"] == "html") == (subset == "html"))]
            for stratum in [None, *sorted({row["stratum"] for row in subset_rows})]:
                rows = [row for row in subset_rows if stratum is None or row["stratum"] == stratum]
                groups.append({"split": split, "subset": subset, "stratum": stratum,
                               "method": "reader_lm", **_aggregate(rows, baselines)})
    return {
        "semantics_version": SEMANTICS_VERSION, "context": CONTEXT, "limitations": LIMITATIONS,
        "complete": not missing, "partial_comparison": bool(missing), "human_gates": "not_assessed",
        "coverage": {"expected": len(snapshots), "recorded": len(candidates), "missing": missing,
                     "status_counts": dict(Counter(row["status"] for row in scored))},
        "resources": _resources(list(candidates.values())), "run_manifest": run_manifest,
        "groups": groups, "original_groups": original_metrics["groups"], "per_document": scored,
        "original_provenance": original_metrics.get("provenance", {}),
    }


def render_reader_report(metrics, manifest, annotations, results):
    candidates = {row["snapshot_id"]: row for row in results}
    sources = {row["snapshot_id"]: row for row in manifest["snapshots"]}
    documents = {row["snapshot_id"]: row for row in annotations["documents"]}
    label = "COMPLETE outcome ledger" if metrics["complete"] else "PARTIAL RUN — NOT a full-run comparison or ranking"
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; '
        'script-src \'none\'; connect-src \'none\'; img-src \'none\'; base-uri \'none\'; form-action \'none\'">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Supplemental Reader-LM evaluation</title><style>'
        'body{font:16px system-ui;margin:2rem;color:#172431}pre{white-space:pre-wrap;overflow-wrap:anywhere;'
        'background:#f2f5f7;padding:1rem}.scroll{overflow:auto}table{border-collapse:collapse;font-size:14px}'
        'td,th{border:1px solid #ccd4da;padding:.5rem;text-align:left}summary{cursor:pointer;padding:.5rem}'
        '.notice{background:#fff3de;padding:1rem}</style></head><body>',
        '<h1>Supplemental Reader-LM evaluation</h1>', f'<h2>{label}</h2>',
        f'<p class="notice">{_escape(CONTEXT)}</p><p>{_escape(LIMITATIONS)}</p>',
        '<p>Missing HTML outcomes remain zero-retention failures under the frozen scoring rules. '
        'Missing non-HTML outcomes remain visible in the ledger. Partial runs must not be ranked against '
        'completed methods. Complete means recorded outcomes, not successful extraction.</p>',
        '<h2>Declared local model constraints</h2><pre>',
        _json({key: metrics["run_manifest"].get("configuration", {}).get(key, "not declared") for key in (
            "model", "revision", "precision", "endpoint", "max_input_tokens", "max_output_tokens",
            "input_policy", "prompt_policy", "temperature", "repetition_penalty", "timeout_seconds"
        )}), '</pre><p>Scores use canonical plain text from the runner’s Markdown-to-block conversion. '
        'Generated output is not assumed to map faithfully to raw source positions. '
        'Control-header removal and finish reasons are recorded in per-sample diagnostics. '
        'Token/resource totals cover recorded supported attempts only; unknown values are not zero.</p>',
        '<h2>Coverage and model resource diagnostics</h2><pre>',
        _json({"coverage": metrics["coverage"], "resources": metrics["resources"]}), '</pre>',
        '<details><summary>Run configuration, constraints, and provenance</summary><pre>',
        _preview({"run_manifest": metrics["run_manifest"], "provenance": metrics.get("provenance"),
                  "original_provenance": metrics["original_provenance"]}, 20_000), '</pre></details>',
        '<h2>HTML comparisons — dev / heldout</h2><p>Micro percentages use anchor denominators; '
        'macro averages eligible documents. Unwanted leakage is lower-is-better only alongside retention. '
        'Original five-method metrics are preserved; the native adapter has zero HTML coverage.</p>',
    ]
    def table(groups):
        return _table(["Split", "Subset", "Stratum", "Method", "Supported / total", "Retention", "Leakage",
                       "Failures / supported", "Latency median / p95 ms (n)", "Paired baseline micro delta (docs)"], [[
            group["split"], group["subset"], group["stratum"] or "All strata", group["method"],
            f'{group["supported_documents"]}/{group["documents"]}', _anchor_summary(group["retention"]),
            _anchor_summary(group["leakage"]), f'{group["output_failures"]}/{group["supported_documents"]}',
            f'{_number(group["latency_ms"]["median"])} / {_number(group["latency_ms"]["p95"])} ({group["latency_ms"]["count"]})',
            f'{_percent(group["paired_baseline_retention"]["micro_delta"])} ({group["paired_baseline_retention"]["documents"]})',
        ] for group in groups])
    combined = [*metrics["original_groups"], *metrics["groups"]]
    parts.append(table(sorted([group for group in combined if group["subset"] == "html" and group["stratum"] is None],
                              key=lambda group: (group["split"], group["method"]))))
    parts.extend(['<details><summary>All subsets and strata, including native non-HTML</summary>',
                  table(combined), '</details><h2>All-source outcome ledger and samples</h2>',
                  '<p>Source paths and URLs are inert provenance text. Previews are bounded; full candidates '
                  'remain in the local Reader-LM results.jsonl. All annotations and document scores are included.</p>'])
    for index, row in enumerate(metrics["per_document"]):
        identity = row["snapshot_id"]
        parts.append(f'<details id="sample-{index}"><summary>{_escape(row["split"])} / {_escape(identity)} / {_escape(row["status"])}</summary>')
        parts.append('<h3>Source provenance</h3><pre>' + _json({key: sources[identity].get(key) for key in (
            "snapshot_id", "split", "format", "stratum", "hostname", "href", "payload_hash", "source_file", "source_row"
        )}) + '</pre><h3>Source-only AI anchors</h3><pre>' + _json(documents[identity]) + '</pre>')
        parts.append('<h3>Frozen per-document scores</h3><pre>' + _json(row) + '</pre>')
        candidate = candidates.get(identity)
        if candidate:
            for field in ("text", "markdown", "diagnostics", "runtime_ms"):
                parts.append(f'<details><summary>{field}</summary><pre>'
                             + _preview(candidate.get(field), 20_000 if field == "text" else 2_000) + '</pre></details>')
        else:
            parts.append('<p>MISSING: no result supplied; not an explicit runner outcome.</p>')
        parts.append('</details>')
    return '\n'.join([*parts, '</body></html>'])


def _load(path):
    return json.loads(Path(path).read_text())


def _validate_frozen_inputs(manifest, annotations, original, run_manifest, freeze):
    for value, key in ((manifest, "manifest_hash"), (annotations, "reference_hash")):
        if stable_hash({name: item for name, item in value.items() if name != key}) != value[key]:
            raise ValueError(f"Invalid {key}")
    if not (manifest["manifest_hash"] == annotations["manifest_hash"] == freeze["manifest_hash"]
            == original["provenance"]["manifest_hash"]):
        raise ValueError("Original/frozen source populations differ")
    if not (annotations["reference_hash"] == freeze["reference_hash"] == original["provenance"]["reference_hash"]):
        raise ValueError("Original/frozen references differ")
    if run_manifest.get("manifest_hash", run_manifest.get("input_manifest_hash")) != manifest["manifest_hash"]:
        raise ValueError("Reader run uses a different evaluation manifest")
    if run_manifest.get("reference_hash") != annotations["reference_hash"]:
        raise ValueError("Reader run uses different frozen references")
    current = hashlib.sha256(Path(__file__).with_name("evaluate.py").read_bytes()).hexdigest()
    if current != freeze["evaluation_sha256"] or current != original["provenance"]["evaluation_source_sha256"]:
        raise ValueError("Frozen scoring source changed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="data/processed/reader-lm-v1/results.jsonl")
    parser.add_argument("--manifest", default="evaluation/extraction/manifest.json")
    parser.add_argument("--annotations", default="evaluation/extraction/annotations.json")
    parser.add_argument("--original-metrics", default="analysis/extraction-evaluation.json")
    parser.add_argument("--freeze", default="evaluation/extraction/freeze.json")
    parser.add_argument("--output", default="analysis/reader-lm-evaluation")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    result_path = Path(args.results)
    manifest, annotations, original = _load(args.manifest), _load(args.annotations), _load(args.original_metrics)
    run_manifest = _load(result_path.with_name("manifest.json"))
    _validate_frozen_inputs(manifest, annotations, original, run_manifest, _load(args.freeze))
    with result_path.open(encoding="utf-8") as stream:
        results = [json.loads(line) for line in stream if line.strip()]
    metrics = evaluate_reader(manifest, annotations, results, original, run_manifest, args.allow_partial)
    metrics["provenance"] = {"results_path": str(result_path), "input_sha256": {
        str(path): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (
            result_path, result_path.with_name("manifest.json"), args.manifest, args.annotations, args.original_metrics, args.freeze)
    }}
    report = render_reader_report(metrics, manifest, annotations, results)
    output = Path(args.output)
    destinations = [output.with_suffix(".json"), output.with_suffix(".html")]
    protected = {Path(path).resolve() for path in (args.results, args.manifest, args.annotations, args.original_metrics,
                 args.freeze, result_path.with_name("manifest.json"), Path(args.original_metrics).with_suffix(".html"))}
    if any(path.resolve() in protected for path in destinations):
        raise ValueError("Supplemental output must not overwrite benchmark inputs or the original report")
    output.parent.mkdir(parents=True, exist_ok=True)
    destinations[0].write_text(json.dumps(metrics, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    destinations[1].write_text(report)
    print(json.dumps({"complete": metrics["complete"], "coverage": metrics["coverage"], "report": str(destinations[1])}))


if __name__ == "__main__":
    main()
