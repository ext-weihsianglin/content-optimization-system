"""Rebind an existing development pilot to the verified saved markdownify corpus."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from encoder_scorer.curate import canonical, counts, load_case, sha256


def rebuild(reference, split_source, corpus, output):
    if output.exists():
        raise FileExistsError("Use a new curation directory")
    previous = json.loads(reference.read_text())
    source_manifest_path = corpus / "manifest.json"
    source = json.loads(source_manifest_path.read_text())
    identity_path = corpus / "run_identity.json"
    identity = json.loads(identity_path.read_text())
    if source.get("status") != "complete" or source.get("pipeline_version") != "retention-markdownify-corpus-v1":
        raise ValueError("Require completed markdownify corpus")
    if sha256(canonical(identity).encode()) != source["run_identity"]:
        raise ValueError("Extraction run identity mismatch")
    if source["source_files"] != previous["source_files"]:
        raise ValueError("Original input hashes differ")
    artifacts = {x["path"]: x for x in source["artifacts"]}
    for name in ("records.jsonl", "documents.jsonl"):
        if sha256((corpus / name).read_bytes()) != artifacts[name]["sha256"]:
            raise ValueError("Corpus index checksum mismatch: " + name)
    if sha256((split_source / "records.jsonl").read_bytes()) != previous["source_records_sha256"]:
        raise ValueError("Frozen split reference records changed")
    hosts_path = split_source / "host_splits.json"
    if sha256(hosts_path.read_bytes()) != previous["host_splits_sha256"]:
        raise ValueError("Frozen host splits changed")
    hosts = json.loads(hosts_path.read_text())
    rows = {r["record_id"]: r for r in map(json.loads, (split_source / "records.jsonl").open())}
    exported = {(r["source_file_hash"], r["source_row"]): r for r in map(json.loads, (corpus / "records.jsonl").open())}
    documents = {d["snapshot_id"]: d for d in map(json.loads, (corpus / "documents.jsonl").open())}
    selected = []
    for old in previous["cases"]:
        if old["split"] not in {"train", "validation"} or hosts.get(old["hostname"]) != old["split"]:
            raise ValueError("Development split mismatch")
        row = rows[old["record_id"]]
        new = exported[(row["source_file_hash"], row["source_row"])]
        for key in ("snapshot_id", "hostname", "prompt", "href"):
            if row[key] != new[key]:
                raise ValueError("Raw-row join mismatch: " + key)
        if row["html_sha256"] != new["payload_hash"]:
            raise ValueError("Raw payload identity mismatch")
        for key in ("snapshot_id", "hostname", "prompt", "split", "html_sha256"):
            if row[key] != old[key]:
                raise ValueError("Pilot reference mismatch: " + key)
        updated = {**row, "status": documents[new["snapshot_id"]]["status"]}
        if updated["status"] not in {"selected", "needs_review"}:
            raise ValueError("Recreated case has unavailable content; do not silently substitute")
        case, doc = load_case(updated, corpus / "documents")
        if case["document_sha256"] != documents[new["snapshot_id"]]["sha256"]:
            raise ValueError("Exported document checksum mismatch")
        if doc.get("representation", {}).get("serializer") != "markdownify-structured-v1":
            raise ValueError("Missing markdownify document representation")
        if doc.get("extraction", {}).get("run_identity") != source["run_identity"]:
            raise ValueError("Document extraction identity mismatch")
        case.update(smoke=old["smoke"], independent_review=old["independent_review"],
                    source_row_id=new["row_id"], reference_document_sha256=old["document_sha256"])
        selected.append(case)
    result = deepcopy(previous)
    result.update(version="teacher-curation-markdownify-v2", source_feature_version=source["pipeline_version"],
                  source_records_sha256=artifacts["records.jsonl"]["sha256"],
                  source_manifest_sha256=sha256(source_manifest_path.read_bytes()),
                  source_path=str(corpus.resolve()), source_run_identity=source["run_identity"],
                  source_identity_sha256=sha256(identity_path.read_bytes()),
                  source_parser_policy=source["pipeline_version"],
                  reference_curation_sha256=sha256(reference.read_bytes()),
                  split_reference_records_sha256=previous["source_records_sha256"],
                  reference_candidate_count=previous["candidate_count"], candidate_count=len(selected),
                  candidate_counts=counts(selected), selected_counts=counts(selected), cases=selected,
                  selection_policy="Preserve frozen pilot record IDs, host splits, smoke and review queues; refresh content from markdownify",
                  teacher_model="gpt-5", teacher_status="approved_model_pending_new_annotation",
                  limitations=["Fixed development pilot recreated from prior selection, not a new sample or held-out evidence",
                               "Only selected development documents loaded; raw-file/index identities verified without re-extraction",
                               "Old-source teacher labels are not transferred; no teacher calls or human review"])
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("reference", "split-source", "corpus", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    result = rebuild(args.reference, args.split_source, args.corpus, args.output)
    print(json.dumps({"cases": len(result["cases"]), "source": result["source_path"]}))


if __name__ == "__main__":
    main()
