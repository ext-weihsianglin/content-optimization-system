"""Validate source-only references and publish per-candidate benchmark reports."""

import argparse
import hashlib
import json
from pathlib import Path

from preprocessing.evaluate import evaluate, normalize_anchor
from preprocessing.report import render_report
from preprocessing.schema import stable_hash


ROOT = Path(__file__).resolve().parents[1]


def validate_provenance(manifest, annotations, results, run_manifest, freeze):
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if stable_hash(manifest_body) != manifest["manifest_hash"]:
        raise ValueError("Evaluation manifest hash mismatch")
    if not (manifest["manifest_hash"] == annotations["manifest_hash"] == run_manifest["input_manifest_hash"] == freeze["manifest_hash"]):
        raise ValueError("Evaluation inputs differ from the frozen benchmark")
    if annotations["reference_hash"] != freeze["reference_hash"]:
        raise ValueError("References differ from the pre-heldout freeze")
    if run_manifest["configuration"] != freeze["configuration"] or run_manifest["source_fingerprints"] != freeze["extraction_fingerprints"]:
        raise ValueError("Extraction differs from the pre-heldout freeze")
    identity = stable_hash({"config": run_manifest["configuration"], "code": run_manifest["source_fingerprints"]})
    if run_manifest["run_identity"] != identity or any(row["run_identity"] != identity for row in results):
        raise ValueError("Mixed or invalid extraction run identities")
    if hashlib.sha256((ROOT / "preprocessing/evaluate.py").read_bytes()).hexdigest() != freeze["evaluation_sha256"]:
        raise ValueError("Scoring differs from the pre-heldout freeze")


def merge_references():
    manifest = json.loads((ROOT / "evaluation/extraction/manifest.json").read_text())
    indexed = {row["snapshot_id"]: row for row in manifest["snapshots"]}
    documents = []
    source_hashes = {}
    for batch in range(1, 5):
        path = ROOT / f"evaluation/extraction/annotations-batch-{batch}.json"
        source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        documents.extend(json.loads(path.read_text())["documents"])
    assert len(documents) == len({row["snapshot_id"] for row in documents}) == len(indexed)
    errors = []
    for document in documents:
        source = json.loads((ROOT / "data/evaluation" / f"{document['snapshot_id']}.source.json").read_text())
        blocks = [normalize_anchor(block["text"]) for block in source["blocks"]]
        for field in ("required", "unwanted"):
            for anchor in document[field]:
                normalized = normalize_anchor(anchor["text"])
                if not normalized or not any(normalized in block for block in blocks):
                    errors.append({"snapshot_id": document["snapshot_id"], "field": field, "anchor": anchor["text"]})
        if document["evaluable"] and not document["required"]:
            errors.append({"snapshot_id": document["snapshot_id"], "error": "evaluable source has no required anchors"})
    if errors:
        raise ValueError(json.dumps(errors, indent=2, ensure_ascii=False))
    merged = {"annotation_type": "ai_source_only", "methodology": "Four independent AI reviewers inspected saved source DOM/text blocks with neither extraction outputs nor citation prompts/labels supplied. They selected useful content and unwanted boilerplate anchors. Bounded source previews were supplemented with full source block files. All anchors were validated against exact saved source blocks. This is NOT human gold, exhaustive content annotation, or whole-document precision/recall.", "human_review": "not_performed", "manifest_hash": manifest["manifest_hash"], "batch_hashes": source_hashes, "documents": sorted(documents, key=lambda row: row["snapshot_id"])}
    merged["reference_hash"] = stable_hash(merged)
    destination = ROOT / "evaluation/extraction/annotations.json"
    if destination.exists() and json.loads(destination.read_text()) != merged:
        raise ValueError("Frozen references differ; create and disclose a revised benchmark instead of silently replacing them")
    destination.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"references": len(documents), "evaluable": sum(row["evaluable"] for row in documents), "required_anchors": sum(len(row["required"]) for row in documents), "unwanted_anchors": sum(len(row["unwanted"]) for row in documents), "reference_hash": merged["reference_hash"]}, indent=2))
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-references", action="store_true")
    parser.add_argument("--results", default="data/processed/eval-v1/results.jsonl")
    parser.add_argument("--output", default="analysis/extraction-evaluation")
    parser.add_argument("--development-only", action="store_true")
    args = parser.parse_args()
    if args.freeze_references:
        merge_references()
        return
    manifest = json.loads((ROOT / "evaluation/extraction/manifest.json").read_text())
    annotations = json.loads((ROOT / "evaluation/extraction/annotations.json").read_text())
    expected_hash = annotations.pop("reference_hash")
    assert stable_hash(annotations) == expected_hash
    annotations["reference_hash"] = expected_hash
    with Path(args.results).open() as stream:
        results = [json.loads(line) for line in stream if line.strip()]
    run_manifest = json.loads(Path(args.results).with_name("manifest.json").read_text())
    if not args.development_only:
        freeze = json.loads((ROOT / "evaluation/extraction/freeze.json").read_text())
        validate_provenance(manifest, annotations, results, run_manifest, freeze)
    if not args.development_only:
        assert len(results) == 5 * len(manifest["snapshots"]), "All candidates must have an explicit outcome for every snapshot"
    metrics = evaluate(manifest, annotations, results)
    metrics["provenance"] = {"manifest_hash": manifest["manifest_hash"], "reference_hash": expected_hash, "results_sha256": hashlib.sha256(Path(args.results).read_bytes()).hexdigest(), "evaluation_source_sha256": hashlib.sha256((ROOT / "preprocessing/evaluate.py").read_bytes()).hexdigest(), "development_only": args.development_only, "run_manifest": json.loads(Path(args.results).with_name("manifest.json").read_text())}
    if args.development_only:
        metrics["groups"] = [group for group in metrics["groups"] if group["split"] == "dev"]
        metrics["per_document"] = [row for row in metrics["per_document"] if row["split"] == "dev"]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    fixtures = json.loads((ROOT / "analysis/extraction-fixtures.json").read_text())
    report = render_report(metrics, manifest, annotations, results, fixture_metrics=fixtures)
    output.with_suffix(".html").write_text(report)
    for group in metrics["groups"]:
        if group["stratum"] is None and ((group["subset"] == "html" and group["method"] != "markdown_text") or (group["subset"] == "native_non_html" and group["method"] in {"baseline", "markdown_text"})):
            print(json.dumps({key: group[key] for key in ["split", "subset", "method", "supported_documents", "retention", "leakage", "output_failures", "latency_ms"]}))
    print(output.with_suffix(".html").resolve())


if __name__ == "__main__":
    main()
