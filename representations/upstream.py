"""Compatibility adapter for PR #1's method/block_json evaluation schema."""

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

from .storage import digest, file_hash, read_json, read_rows

REQUIRED = ("records", "snapshots", "source_features", "extractions", "blocks", "selection")


def decoded(value):
    return json.loads(value) if isinstance(value, str) else (value or {})


def unique(rows, key, name):
    result = {}
    for row in rows:
        identity = key(row)
        if identity in result:
            raise ValueError(f"Duplicate {name} identity: {identity}")
        result[identity] = row
    return result


def load_upstream(root, raw_root=None, limit=None):
    root = Path(root)
    paths = [root / "manifest.json", *[root / f"{name}.parquet" for name in REQUIRED]]
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Required upstream artifact missing: {path.name}")
    manifest = read_json(paths[0])
    version = manifest.get("schema_version") or manifest.get("configuration", {}).get("schema_version")
    if version != "1.0.0" or manifest.get("status") != "complete":
        raise ValueError("Require a complete upstream run with schema 1.0.0")
    hashes = {path.name: file_hash(path) for path in paths}
    tables = {name: read_rows(root / f"{name}.parquet") for name in REQUIRED}
    snapshots = unique(tables["snapshots"], lambda r: r["snapshot_id"], "snapshot")
    selections = unique(tables["selection"], lambda r: r["snapshot_id"], "selection")
    extractions = unique(tables["extractions"], lambda r: (r["snapshot_id"], r["method"]), "extraction")
    inventories = unique(tables["source_features"], lambda r: r["snapshot_id"], "source inventory")
    if set(selections) != set(snapshots) or set(inventories) != set(snapshots):
        raise ValueError("Selection/source inventory must account for every snapshot")
    blocks = {}
    for row in tables["blocks"]:
        block = decoded(row["block_json"]) if "block_json" in row else row
        identity = (row["snapshot_id"], row["method"])
        if identity not in extractions:
            raise ValueError("Block references unknown extraction")
        blocks.setdefault(identity, []).append(block)
    chosen = set(sorted(snapshots)[:limit]) if limit is not None else set(snapshots)
    if limit is not None and limit < 1:
        raise ValueError("Limit must be positive")
    documents = []
    for sid in sorted(chosen):
        snap, selection = snapshots[sid], selections[sid]
        inventory_row = inventories[sid]
        inventory = decoded(inventory_row.get("inventory_json", inventory_row))
        document = {"snapshot": snap, "selection": selection, "inventory": inventory,
                    "extraction": None, "blocks": [], "extraction_id": None}
        if selection["status"] == "selected":
            identity = (sid, selection.get("method") or selection.get("selected_method"))
            extraction = extractions.get(identity)
            if extraction is None or extraction["status"] != "ok":
                raise ValueError("Selected extraction must exist and be successful")
            ordered = sorted(blocks.get(identity, []), key=lambda b: b["order"])
            seen, orders = set(), set()
            for block in ordered:
                if block["block_id"] in seen or block["order"] in orders:
                    raise ValueError("Duplicate block ID/order")
                if block.get("parent_id") and block["parent_id"] not in seen:
                    raise ValueError("Block parent must precede child")
                seen.add(block["block_id"])
                orders.add(block["order"])
            if not ordered and extraction.get("text", "").strip():
                raise ValueError("Selected content has no authoritative blocks")
            eid = digest({"snapshot_id": sid, "method": identity[1], "blocks": ordered,
                          "metadata": extraction.get("metadata"), "upstream_run": manifest.get("run_identity")})
            document.update(extraction=extraction, blocks=ordered, extraction_id=eid)
        documents.append(document)
    records = []
    ids, verified_files = set(), {}
    for source in tables["records"]:
        row = dict(source)
        if row["record_id"] in ids or row["snapshot_id"] not in snapshots:
            raise ValueError("Duplicate record ID or dangling record association")
        ids.add(row["record_id"])
        if row["snapshot_id"] not in chosen:
            continue
        if "prompt" not in row:
            if raw_root is None:
                raise ValueError("Upstream records lack prompts. Supply --raw-root to hydrate verified original rows.")
            raw_path = Path(raw_root) / Path(row["source_file"]).name
            expected = row["source_file_hash"]
            if raw_path not in verified_files:
                if file_hash(raw_path) != expected:
                    raise ValueError("Original parquet hash differs from upstream provenance")
                verified_files[raw_path] = expected
            elif verified_files[raw_path] != expected:
                raise ValueError("Conflicting raw-file provenance")
            parquet = pq.ParquetFile(raw_path)
            index = row["source_row"]
            if index < 0 or index >= parquet.metadata.num_rows:
                raise ValueError("Invalid source row")
            for group in range(parquet.num_row_groups):
                size = parquet.metadata.row_group(group).num_rows
                if index < size:
                    original = parquet.read_row_group(group, columns=["prompt", "citation_category", "href", "hostname", "html_content"]).slice(index, 1).to_pylist()[0]
                    break
                index -= size
            if hashlib.sha256(original["html_content"].encode()).hexdigest() != row["payload_hash"] or original["href"] != row["href"]:
                raise ValueError("Original row does not match snapshot provenance")
            row.update({k: original[k] for k in ("prompt", "citation_category", "hostname")})
        if not isinstance(row["prompt"], str):
            raise ValueError("Original prompts must be strings")
        snap = snapshots[row["snapshot_id"]]
        if row.get("href", snap["href"]) != snap["href"] or row.get("payload_hash", snap["payload_hash"]) != snap["payload_hash"]:
            raise ValueError("Record/snapshot URL or payload mismatch")
        records.append(row)
    return documents, records, {"hashes": hashes, "manifest": manifest,
                                "source_records": len(tables["records"]), "source_snapshots": len(snapshots),
                                "limit": limit}
