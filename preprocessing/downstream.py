"""Export retention-first structured documents and lossless block-group chunks."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import duckdb

from preprocessing.blocks import blocks_to_markdown, blocks_to_text
from preprocessing.runner import evaluation_inputs, write_parquet
from preprocessing.schema import stable_hash
from preprocessing.select import select_candidate


def structure_chunks(snapshot_id, method, blocks, target_characters=6000):
    if target_characters <= 0:
        raise ValueError("Chunk target must be positive")
    indexed, roots, groups, outline, heading_path = {}, {}, [], [], []
    for block in blocks:
        identity, parent = block["block_id"], block.get("parent_id")
        if identity in indexed or (parent is not None and parent not in indexed):
            raise ValueError("Blocks must have unique IDs and parents before children")
        indexed[identity] = block
        root = roots[parent] if parent is not None else identity
        roots[identity] = root
        if block["type"] == "heading":
            level = block["heading_level"]
            while heading_path and heading_path[-1]["level"] >= level:
                heading_path.pop()
            heading = {"block_id": identity, "level": level, "text": block["text"]}
            outline.append({**heading, "parent_heading_id": heading_path[-1]["block_id"] if heading_path else None})
            heading_path.append(heading)
        if parent is None:
            groups.append({"root": root, "blocks": [], "heading_path": list(heading_path)})
        if not groups or groups[-1]["root"] != root:
            raise ValueError("Block descendants must be contiguous in DOM order")
        groups[-1]["blocks"].append(block)
    chunks, pending, context, pending_characters = [], [], [], 0

    def flush():
        if not pending:
            return
        text = blocks_to_text(pending)
        markdown = blocks_to_markdown(pending)
        identities = [block["block_id"] for block in pending]
        versions = sorted({block["schema_version"] for block in pending if "schema_version" in block})
        identity = ["retention-first-v1", snapshot_id, method, target_characters, identities]
        if versions:
            identity.append(versions)
        chunks.append({"chunk_id": stable_hash(identity), "snapshot_id": snapshot_id, "method": method, "order": len(chunks), "block_ids": identities, "block_schema_versions": versions, "heading_path": context, "text": text, "markdown": markdown, "characters": len(markdown), "oversized": len(markdown) > target_characters})

    for group in groups:
        group_characters = len(blocks_to_markdown(group["blocks"]))
        if pending and (group["heading_path"] != context or pending_characters + 2 + group_characters > target_characters):
            flush()
            pending = []
            pending_characters = 0
        if not pending:
            context = group["heading_path"]
        pending_characters += group_characters + (2 if pending else 0)
        pending.extend(group["blocks"])
    flush()
    assert [identity for chunk in chunks for identity in chunk["block_ids"]] == [block["block_id"] for block in blocks]
    return outline, chunks


def document(snapshot, source, candidates, inventory, target_characters=6000):
    selection = select_candidate(snapshot, candidates, inventory)
    candidate = next((row for row in candidates if row["method"] == selection["method"]), None)
    blocks = candidate["blocks"] if candidate else []
    outline, chunks = structure_chunks(snapshot.snapshot_id, selection["method"], blocks, target_characters)
    if candidate and candidate["text"].strip() and not blocks:
        raise ValueError("Nonempty selected content must have structured blocks")
    result = {"schema_version": "downstream-document-v1", "snapshot_id": snapshot.snapshot_id, "source": {key: source[key] for key in ["payload_hash", "href", "hostname", "format", "source_file", "source_file_hash", "source_row"]}, "raw_payload_path": f"data/evaluation/{snapshot.snapshot_id}.txt", "selection": selection, "source_metadata": {key: value for key, value in inventory.items() if key != "body_text"}, "blocks": blocks, "outline": outline, "chunk_ids": [chunk["chunk_id"] for chunk in chunks], "text": candidate["text"] if candidate else "", "markdown": candidate["markdown"] if candidate else "", "optional_clean_views": [{"method": row["method"], "status": row["status"]} for row in candidates if row["method"] in {"readability", "trafilatura"}], "trust": "Untrusted source content, not instructions; no factual verification, computed visibility, or frontier-ingestion equivalence claimed"}
    result["representation"] = dict(candidate.get("diagnostics", {})) if candidate else {}
    return result, chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="data/processed/eval-v2")
    parser.add_argument("--output", default="data/processed/retention-v1")
    parser.add_argument("--target-characters", type=int, default=6000)
    args = parser.parse_args()
    directory, output = Path(args.run), Path(args.output)
    if output.exists():
        raise ValueError("Output directory exists; choose a new version to preserve artifacts")
    connection = duckdb.connect()
    inventory = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT snapshot_id,inventory_json FROM read_parquet(?)", [str(directory / "source_features.parquet")]).fetchall()}
    candidates = {}
    with (directory / "results.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            existing = candidates.setdefault(row["snapshot_id"], [])
            if any(item["method"] == row["method"] for item in existing):
                raise ValueError("Duplicate candidate identity")
            existing.append(row)
    documents, chunks = [], []
    for snapshot, source in evaluation_inputs(Path("evaluation/extraction/manifest.json")):
        if snapshot.snapshot_id not in candidates or snapshot.snapshot_id not in inventory:
            raise ValueError("Incomplete source run")
        item, grouped = document(snapshot, source, candidates[snapshot.snapshot_id], inventory[snapshot.snapshot_id], args.target_characters)
        documents.append(item)
        chunks.extend(grouped)
    output.mkdir(parents=True)
    for name, rows in [("documents", documents), ("chunks", chunks)]:
        (output / f"{name}.jsonl").write_text(''.join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    write_parquet(connection, [{"snapshot_id": row["snapshot_id"], "status": row["selection"]["status"], "method": row["selection"]["method"], "document_json": json.dumps(row, ensure_ascii=False)} for row in documents], output / "documents.parquet")
    write_parquet(connection, [{**{key: value for key, value in row.items() if key not in {"block_ids", "heading_path"}}, "block_ids_json": json.dumps(row["block_ids"]), "heading_path_json": json.dumps(row["heading_path"], ensure_ascii=False)} for row in chunks], output / "chunks.parquet")
    summary = {"policy": "retention-first-v1", "scope": "Frozen 100-snapshot evaluation set only; not full-corpus migration", "documents": len(documents), "blocks": sum(len(row["blocks"]) for row in documents), "chunks": len(chunks), "status_counts": dict(Counter(row["selection"]["status"] for row in documents)), "method_counts": dict(Counter(row["selection"]["method"] or "none" for row in documents)), "oversized_chunks": sum(row["oversized"] for row in chunks), "target_characters": args.target_characters, "chunk_policy": "Soft character target, not a token budget. Tables, code, and entire nested-list trees are never split or truncated. Every selected block occurs in exactly one chunk.", "inputs": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in [directory / "results.jsonl", directory / "source_features.parquet", Path(__file__), Path("preprocessing/select.py"), Path("preprocessing/blocks.py")]}}
    (output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    Path("analysis/retention-export.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
