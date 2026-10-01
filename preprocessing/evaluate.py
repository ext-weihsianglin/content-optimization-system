"""Frozen, source-only selected-anchor metrics; see evaluation/extraction/rubric.md."""

from collections import Counter
import math
import statistics
import unicodedata


METHODS = ("baseline", "trafilatura", "readability", "conservative_dom", "markdown_text")
STATUSES = {"ok", "empty", "unsupported_format", "error", "timeout"}
SEMANTICS_VERSION = "selected-anchors-v1"
LIMITATIONS = (
    "Ground truth is SOURCE-ONLY AI-assisted selected anchors, NOT human gold or "
    "whole-document precision/recall. Exact substring presence does not assess "
    "factual fidelity, usability, or structural relationships. Human acceptance "
    "gates are NOT ASSESSED; no threshold achievement is certified. This purposive "
    "sample does not establish population accuracy. No uncertainty interval is claimed."
)
_PUNCTUATION = str.maketrans({
    **dict.fromkeys("‘’‚‛′", "'"),
    **dict.fromkeys("“”„‟″", '"'),
    **dict.fromkeys("‐‑‒–—―−﹘﹣－", "-"),
    "…": "...",
})


def normalize_anchor(text):
    """Canonicalize typography without discarding punctuation or fuzzy matching."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().translate(_PUNCTUATION).split())


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _mean(values):
    return statistics.mean(values) if values else None


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _expected_support(method, source_format):
    return method == "baseline" or (source_format != "html" if method == "markdown_text" else source_format == "html")


def _index(records, key, label):
    indexed = {}
    for record in records:
        identity = key(record)
        if identity in indexed:
            raise ValueError(f"Duplicate {label}: {identity}")
        indexed[identity] = record
    return indexed


def _score(snapshot, annotation, result, method):
    expected = _expected_support(method, snapshot["format"])
    status = result["status"] if result else "missing"
    supported = expected and status != "unsupported_format"
    output = normalize_anchor(result.get("text", "")) if result else ""
    successful = supported and status == "ok" and bool(output)
    evaluable = annotation is not None and annotation["evaluable"]
    row = {
        "snapshot_id": snapshot["snapshot_id"], "method": method,
        "split": snapshot["split"], "stratum": snapshot["stratum"],
        "format": snapshot["format"], "hostname": snapshot["hostname"],
        "annotation_present": annotation is not None, "evaluable": evaluable,
        "expected_supported": expected, "supported": supported,
        "status": status, "result_present": result is not None,
        "output_empty": not bool(output), "output_failure": supported and not successful,
        "runtime_ms": None,
    }
    runtime = result.get("runtime_ms") if result else None
    if supported and isinstance(runtime, (int, float)) and not isinstance(runtime, bool) and math.isfinite(runtime) and runtime >= 0:
        row["runtime_ms"] = runtime
    for field, prefix in (("required", "retention"), ("unwanted", "leakage")):
        anchors = (annotation or {}).get(field, [])
        normalized = [normalize_anchor(anchor["text"]) for anchor in anchors]
        hits = [bool(anchor) and successful and anchor in output for anchor in normalized]
        denominator = sum(bool(anchor) for anchor in normalized)
        numerator = sum(hits)
        eligible = bool(evaluable and supported and denominator)
        row.update({
            f"{field}_matches": numerator, f"{field}_count": denominator,
            f"{field}_blank_excluded": len(anchors) - denominator,
            f"{field}_hits": hits, f"{prefix}_eligible": eligible,
            f"{prefix}_numerator": numerator if eligible else 0,
            f"{prefix}_denominator": denominator if eligible else 0,
            prefix: _ratio(numerator, denominator) if eligible else None,
        })
    return row


def _aggregate(rows, baselines):
    supported = [row for row in rows if row["supported"]]
    latencies = [row["runtime_ms"] for row in supported if row["runtime_ms"] is not None]
    summary = {
        "documents": len(rows),
        "annotated_documents": sum(row["annotation_present"] for row in rows),
        "missing_annotation_documents": sum(not row["annotation_present"] for row in rows),
        "content_evaluable_documents": sum(row["evaluable"] for row in rows),
        "source_non_evaluable_documents": sum(row["annotation_present"] and not row["evaluable"] for row in rows),
        "supported_documents": len(supported),
        "unsupported_documents": len(rows) - len(supported),
        "expected_supported_documents": sum(row["expected_supported"] for row in rows),
        "unexpected_unsupported_documents": sum(row["expected_supported"] and row["status"] == "unsupported_format" for row in rows),
        "support_coverage": _ratio(len(supported), len(rows)),
        "supported_content_evaluable_documents": sum(row["evaluable"] for row in supported),
        "output_failures": sum(row["output_failure"] for row in supported),
        "output_failure_rate": _ratio(sum(row["output_failure"] for row in supported), len(supported)),
        "missing_result_documents": sum(not row["result_present"] for row in supported),
        "supported_empty_output_documents": sum(row["output_empty"] for row in supported),
        "status_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        "latency_ms": {"count": len(latencies), "median": _percentile(latencies, .5), "p95": _percentile(latencies, .95)},
    }
    for field, prefix in (("required", "retention"), ("unwanted", "leakage")):
        eligible = [row for row in rows if row[f"{prefix}_eligible"]]
        numerator = sum(row[f"{prefix}_numerator"] for row in eligible)
        denominator = sum(row[f"{prefix}_denominator"] for row in eligible)
        summary[prefix] = {
            "eligible_documents": len(eligible), "numerator": numerator,
            "denominator": denominator, "micro": _ratio(numerator, denominator),
            "macro": _mean([row[prefix] for row in eligible]),
            "evaluable_zero_reference_documents": sum(row["evaluable"] and not row[f"{field}_count"] for row in rows),
            "blank_anchors_excluded": sum(row[f"{field}_blank_excluded"] for row in rows),
        }
    pairs = [(row, baselines[row["snapshot_id"]]) for row in rows
             if row["retention_eligible"] and baselines[row["snapshot_id"]]["retention_eligible"]]
    denominator = sum(row["retention_denominator"] for row, baseline in pairs)
    candidate_hits = sum(row["retention_numerator"] for row, baseline in pairs)
    baseline_hits = sum(baseline["retention_numerator"] for row, baseline in pairs)
    summary["paired_baseline_retention"] = {
        "documents": len(pairs), "anchor_denominator": denominator,
        "candidate_numerator": candidate_hits, "baseline_numerator": baseline_hits,
        "candidate_micro": _ratio(candidate_hits, denominator),
        "baseline_micro": _ratio(baseline_hits, denominator),
        "micro_delta": _ratio(candidate_hits - baseline_hits, denominator),
        "macro_delta": _mean([row["retention"] - baseline["retention"] for row, baseline in pairs]),
    }
    return summary


def evaluate(manifest, annotations, results):
    """Evaluate input dictionaries and iterable result records without any I/O.

    Missing supported results are scored as failures. Malformed or ambiguous joins
    fail loudly instead of silently changing the benchmark population.
    """
    if annotations.get("annotation_type") != "ai_source_only":
        raise ValueError("Expected annotation_type='ai_source_only'")
    snapshots = _index(manifest["snapshots"], lambda row: row["snapshot_id"], "snapshot")
    documents = _index(annotations["documents"], lambda row: row["snapshot_id"], "annotation")
    candidates = _index(results, lambda row: (row["snapshot_id"], row["method"]), "result")
    if set(documents) - set(snapshots):
        raise ValueError("Annotations reference snapshots outside the manifest")
    for snapshot in snapshots.values():
        if snapshot["split"] not in {"dev", "heldout"}:
            raise ValueError(f"Invalid split: {snapshot['split']}")
    for document in documents.values():
        if not isinstance(document["evaluable"], bool):
            raise ValueError("Annotation evaluable must be boolean")
    for (snapshot_id, method), result in candidates.items():
        if snapshot_id not in snapshots or method not in METHODS or result["status"] not in STATUSES:
            raise ValueError(f"Invalid result identity/status: {snapshot_id}, {method}")
    per_document = [
        _score(snapshot, documents.get(snapshot_id), candidates.get((snapshot_id, method)), method)
        for snapshot_id, snapshot in sorted(snapshots.items()) for method in METHODS
    ]
    baselines = {row["snapshot_id"]: row for row in per_document if row["method"] == "baseline"}
    groups = []
    for split in ("dev", "heldout"):
        split_rows = [row for row in per_document if row["split"] == split]
        for subset in ("all", "html", "native_non_html"):
            subset_rows = [row for row in split_rows if subset == "all" or (row["format"] == "html") == (subset == "html")]
            for stratum in [None, *sorted({row["stratum"] for row in subset_rows})]:
                for method in METHODS:
                    rows = [row for row in subset_rows if row["method"] == method and (stratum is None or row["stratum"] == stratum)]
                    groups.append({"split": split, "subset": subset, "stratum": stratum, "method": method, **_aggregate(rows, baselines)})
    split_counts = dict(Counter(snapshot["split"] for snapshot in snapshots.values()))
    hosts = Counter(snapshot["hostname"].strip().casefold().rstrip(".") for snapshot in snapshots.values())
    host_splits = {}
    for snapshot in snapshots.values():
        host_splits.setdefault(snapshot["hostname"].strip().casefold().rstrip("."), set()).add(snapshot["split"])
    warnings = []
    if len(snapshots) != 100 or split_counts != {"dev": 60, "heldout": 40}:
        warnings.append("Actual sample differs from the intended 100 snapshots / 60 dev / 40 heldout.")
    if any(count > 1 for count in hosts.values()):
        warnings.append("More than one snapshot per hostname; intended sampling constraint violated.")
    if any(len(splits) > 1 for splits in host_splits.values()):
        warnings.append("Hostname leakage across development and held-out splits.")
    if set(snapshots) - set(documents):
        warnings.append("Missing annotations are excluded from content metrics, not treated as perfect retention.")
    return {
        "semantics_version": SEMANTICS_VERSION, "declared_freeze_date": "2026-10-01",
        "annotation_type": "ai_source_only", "limitations": LIMITATIONS,
        "human_gates": "not_assessed", "thresholds_certified": False,
        "uncertainty_interval": None, "manifest_version": manifest.get("version"),
        "sample": {"documents": len(snapshots), "split_counts": split_counts, "unique_hostnames": len(hosts)},
        "warnings": warnings, "groups": groups, "per_document": per_document,
    }
