"""Adapters for frozen evaluation parquets and shared retention-first documents."""

import hashlib
import gzip
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


def load_upstream(root, raw_root=None, limit=None, *, split_reference=None):
    root = Path(root)
    if (root / "records.jsonl").is_file():
        return load_retention(root, limit, raw_root=raw_root, split_reference=split_reference)
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


def load_retention(root, limit=None, *, raw_root=None, split_reference=None):
    """Consume PR #2's saved full-corpus documents, without parsing HTML again."""
    manifest = read_json(root / "manifest.json")
    markdownify = manifest.get("pipeline_version") == "retention-markdownify-corpus-v1"
    if not markdownify and manifest.get("parser_policy") != "retention-first-v1":
        raise ValueError("Unsupported retention parser policy")
    if markdownify and manifest.get("status") != "complete":
        raise ValueError("Require completed markdownify corpus")
    verified_artifacts = {}
    document_index = {}
    if markdownify:
        for artifact in manifest['artifacts']:
            if file_hash(root / artifact['path']) != artifact['sha256']:
                raise ValueError('Markdownify corpus artifact checksum mismatch')
            verified_artifacts[artifact['path']] = artifact['sha256']
        with (root / 'documents.jsonl').open() as stream:
            document_index = unique([json.loads(line) for line in stream if line.strip()], lambda r:r['snapshot_id'], 'document index')
    if limit is not None and limit < 1:
        raise ValueError("Limit must be positive")
    with (root / "records.jsonl").open() as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    if len(records) != manifest["raw_rows"] or len({r["snapshot_id"] for r in records}) != manifest["unique_snapshots"]:
        raise ValueError("Retention manifest accounting mismatch")
    chosen = set(sorted({r["snapshot_id"] for r in records})[:limit]) if limit else {r["snapshot_id"] for r in records}
    hashes = {**verified_artifacts, **{name: file_hash(root / name) for name in ("manifest.json", "records.jsonl")}}
    splits = None
    if split_reference is not None:
        reference = Path(split_reference)
        from .storage import load_run
        previous = load_run(reference)
        splits = unique(read_rows(reference / 'associations.parquet'), lambda r:(r['source_file_hash'],r['source_row']), 'split reference')
        split_provenance = {'path':str(reference.resolve()), 'associations_sha256':previous['artifacts']['associations.parquet']}
    sources = manifest["source_files"]
    seen, selected = set(), []
    for source in records:
        row = dict(source)
        if sources.get(Path(row["source_file"]).name) != row["source_file_hash"]:
            raise ValueError("Record raw-file provenance differs from manifest")
        identity = digest([row["source_file_hash"], row["source_row"]])
        if identity in seen or row["source_row"] < 0:
            raise ValueError("Duplicate or invalid original row identity")
        seen.add(identity)
        if row["snapshot_id"] not in chosen:
            continue
        if not isinstance(row["prompt"], str):
            raise ValueError("Original prompts must be strings")
        row.update(record_id=identity, source_record_id=source["row_id"] if markdownify else source["record_id"],
                   payload_hash=source["payload_hash"] if markdownify else source["html_sha256"],
                   citation_category=source['citation_category'] if markdownify else ("top" if source["is_cited_high"] else "bottom"),
                   upstream_exclusions=source.get("exclusions", []))
        if splits is not None:
            previous = splits.get((row['source_file_hash'],row['source_row']))
            if previous is None or any(previous[key] != row[key] for key in ('payload_hash','href','prompt','hostname','citation_category')):
                raise ValueError('Split reference does not match original source row')
            row.update(split=previous['split'], upstream_exclusions=previous.get('upstream_exclusions', []))
        selected.append(row)

    if raw_root is not None:
        for name, expected in sources.items():
            path = Path(raw_root) / name
            if file_hash(path) != expected:
                raise ValueError('Raw source checksum differs from corpus')
            originals = pq.read_table(path).to_pylist()
            for row in selected:
                if Path(row['source_file']).name != name:
                    continue
                index = row['source_row']
                if index < 0 or index >= len(originals):
                    raise ValueError('Invalid raw row index')
                original = originals[index]
                if any(original[key] != row[key] for key in ('href','hostname','prompt','citation_category')) or hashlib.sha256(original['html_content'].encode()).hexdigest() != row['payload_hash']:
                    raise ValueError('Prepared record differs from original raw row')
            del originals

    def documents():
        for sid in sorted(chosen):
            path = root / "documents" / f"{sid}.json.gz"
            hashes[str(path.relative_to(root))] = file_hash(path)
            if markdownify and hashes[str(path.relative_to(root))] != document_index[sid]['sha256']:
                raise ValueError('Markdownify document file checksum mismatch')
            with gzip.open(path, "rt") as stream:
                doc = json.load(stream)
            if markdownify:
                extraction = doc.get('extraction', {})
                unhashed = {**doc, 'extraction':{key:value for key,value in extraction.items() if key != 'content_hash'}}
                if extraction.get('run_identity') != manifest['run_identity'] or digest(unhashed) != extraction.get('content_hash'):
                    raise ValueError('Markdownify document content identity mismatch')
            if doc.get("schema_version") != "downstream-document-v1" or doc["snapshot_id"] != sid or doc["selection"]["policy"] != "retention-first-v1":
                raise ValueError("Invalid saved downstream document")
            source = doc["source"]
            if digest([source["payload_hash"], source["href"]]) != sid:
                raise ValueError("Saved snapshot identity mismatch")
            blocks = doc["blocks"]
            ids, orders = set(), set()
            for block in blocks:
                if block["block_id"] in ids or block["order"] in orders or (block.get("parent_id") and block["parent_id"] not in ids):
                    raise ValueError("Invalid saved block tree")
                ids.add(block["block_id"])
                orders.add(block["order"])
            if [b["order"] for b in blocks] != sorted(orders):
                raise ValueError("Saved blocks must be in source order")
            chunks = doc["chunks"]
            if doc["chunk_ids"] != [c["chunk_id"] for c in chunks] or len(set(doc["chunk_ids"])) != len(chunks):
                raise ValueError("Saved chunk identity mismatch")
            if [bid for c in chunks for bid in c["block_ids"]] != [b["block_id"] for b in blocks]:
                raise ValueError("Source chunks must partition saved blocks in order")
            for chunk in chunks:
                if chunk["snapshot_id"] != sid or chunk["method"] != doc["selection"]["method"] or any(h["block_id"] not in ids for h in chunk["heading_path"]):
                    raise ValueError("Invalid source chunk lineage")
            eid = digest([sid, hashes[str(path.relative_to(root))]])
            yield {"snapshot": {**source, "snapshot_id": sid}, "selection": doc["selection"],
                   "inventory": doc["source_metadata"], "blocks": blocks, "chunks": chunks,
                   "extraction_id": eid if doc["selection"].get("method") else None,
                   "retention_first": True}

    return documents(), selected, {"format": "downstream-document-v1", "hashes": hashes,
                                  "raw_verified": raw_root is not None,
                                  "split_reference": split_provenance if splits is not None else None,
                                  "manifest": manifest, "source_records": len(records),
                                  "source_snapshots": manifest["unique_snapshots"], "limit": limit}
