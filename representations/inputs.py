"""Selected structural blocks → deterministic textual embedding units."""

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urldefrag

from . import SCHEMA_VERSION, SERIALIZER_VERSION
from .chunking import split_text
from .contracts import ASSOCIATION_SCHEMA, UNIT_SCHEMA
from .storage import digest, file_hash, write_json, write_rows
from .upstream import decoded, load_upstream
from .url_path import normalize_path


def render_block(block, by_id):
    text = block.get("text") or ""
    kind = block["type"]
    if kind == "table" and block.get("table"):
        table = block["table"]
        cells = [{key: cell.get(key) for key in ("row", "column", "text", "is_header", "scope", "headers", "id", "rowspan", "colspan")}
                 for cell in table.get("cells", [])]
        return "Table: " + json.dumps({"caption": table.get("caption", ""), "cells": cells}, ensure_ascii=False, sort_keys=True)
    if kind == "heading":
        return "#" * (block.get("heading_level") or 1) + " " + text
    if kind == "code":
        return "Code (" + (block.get("language") or "unspecified") + "):\n" + text
    if not text:
        return ""
    depth = 0
    parent = block.get("parent_id")
    quote = False
    while parent:
        ancestor = by_id[parent]
        depth += ancestor["type"] in {"list", "list_item"}
        quote |= ancestor["type"] == "quote"
        parent = ancestor.get("parent_id")
    return ("> " if quote else "") + ("  " * max(0, depth - 1) + "- " if depth else "") + text


def serialize(blocks, by_id):
    pieces, spans, offset = [], [], 0
    for block in blocks:
        text = render_block(block, by_id)
        if not text:
            continue
        if pieces:
            offset += 2
        pieces.append(text)
        spans.append((offset, offset + len(text), block["block_id"]))
        offset += len(text)
    return "\n\n".join(pieces), spans


def make_unit(sid, eid, view, subview, text, *, block_ids=None, section_id=None,
              chunk_index=0, start=0, end=None, status="ready", reason=None, diagnostics=None,
              weight=None):
    identity = [SERIALIZER_VERSION, sid, eid, view, subview, section_id, chunk_index, text, start, end, status]
    return {"unit_id": digest(identity), "snapshot_id": sid, "extraction_id": eid,
            "view": view, "subview": subview, "text": text, "text_hash": digest(text),
            "status": status, "reason": reason, "block_ids": block_ids or [], "source_chunk_ids": [], "section_id": section_id,
            "chunk_index": chunk_index, "serialized_start": start, "serialized_end": end,
            "content_weight": weight if weight is not None else len(text.encode()),
            "role": "query" if view == "query" else "document", "modality": "text",
            "asset_id": None, "product_entity_id": None,
            "diagnostics_json": json.dumps(diagnostics or {}, ensure_ascii=False, sort_keys=True)}


def text_units(sid, eid, view, subview, text, ceiling, *, spans=(), section_id=None, prefix="", diagnostics=None):
    if not text.strip() and not prefix.strip():
        return [make_unit(sid, eid, view, subview, "", status="unavailable", reason="missing_source_view", diagnostics=diagnostics)]
    allowance = ceiling - len(prefix.encode())
    if allowance < 32:
        return [make_unit(sid, eid, view, subview, "", status="unavailable", reason="heading_context_exceeds_limit", diagnostics=diagnostics)]
    parts = list(split_text(text, allowance, boundaries=[lo for lo, _, _ in spans])) if text else [("", 0, 0)]
    units = []
    for index, (part, start, end) in enumerate(parts):
        contributors = [bid for lo, hi, bid in spans if lo < end and hi > start]
        chunk_diagnostics = {**(diagnostics or {}), "split_block_ids": [bid for lo, hi, bid in spans if lo < end and hi > start and (lo < start or hi > end)]}
        units.append(make_unit(sid, eid, view, subview, prefix + part, block_ids=contributors,
                               section_id=section_id, chunk_index=index, start=start, end=end,
                               diagnostics=chunk_diagnostics, weight=max(1, len(part.encode()))))
    if len(parts) > 1 and view != "section":
        pooled = make_unit(sid, eid, view, subview, "", status="derived", reason="byte_weighted_pool",
                           block_ids=[bid for _, _, bid in spans], diagnostics={"members": [u["unit_id"] for u in units], **(diagnostics or {})})
        for unit in units:
            unit["subview"] += ":chunk"
        units.append(pooled)
    return units


def document_units(document, config):
    sid, eid = document["snapshot"]["snapshot_id"], document["extraction_id"]
    if document["selection"]["status"] != "selected" and not (document.get("retention_first") and document["selection"]["status"] == "needs_review" and eid):
        return []
    blocks = document["blocks"]
    by_id = {b["block_id"]: b for b in blocks}
    chunk, page = config["chunk_bytes"], config["page_bytes"]
    units = []
    title = document["inventory"].get("title") or ""
    units += text_units(sid, eid, "title", "document_title", title, page)
    h1s = [b for b in blocks if b["type"] == "heading" and b.get("heading_level") == 1]
    for block in h1s:
        units += text_units(sid, eid, "title", "h1:" + block["block_id"], block["text"], page,
                            spans=[(0, len(block["text"]), block["block_id"])])
    if not h1s:
        units += text_units(sid, eid, "title", "h1", "", page)
    headings = [b for b in blocks if b["type"] == "heading"]
    outline, outline_spans = serialize(headings, by_id)
    units += text_units(sid, eid, "outline", "outline", outline, page, spans=outline_spans)
    full_text, spans = serialize(blocks, by_id)
    counts = Counter(b["type"] for b in blocks)
    structural = {"word_count": len(full_text.split()), "heading_count": counts["heading"],
                  "table_count": counts["table"], "list_count": counts["list"],
                  "code_count": counts["code"]}
    units += text_units(sid, eid, "page", "page", full_text, page, spans=spans,
                        diagnostics={"structure": structural})
    path = normalize_path(document["snapshot"]["href"])
    units += text_units(sid, eid, "path", "url_path", path["text"], page, diagnostics=path)
    if path["status"] != "ready":
        units[-1]["reason"] = path["reason"]
    if document.get("retention_first"):
        chunk_for_block = {bid: c["chunk_id"] for c in document["chunks"] for bid in c["block_ids"]}
        for source_chunk in document["chunks"]:
            chunk_blocks = [by_id[bid] for bid in source_chunk["block_ids"]]
            text, local_spans = serialize(chunk_blocks, by_id)
            ancestry = [by_id[h["block_id"]] for h in source_chunk["heading_path"]
                        if h["block_id"] not in source_chunk["block_ids"]]
            prefix = "\n".join(render_block(h, by_id) for h in ancestry)
            section_units = text_units(sid, eid, "section", "source_chunk", text, chunk,
                                       spans=local_spans, section_id=source_chunk["chunk_id"],
                                       prefix=prefix + "\n\n" if prefix else "",
                                       diagnostics={"heading_ids": [h["block_id"] for h in source_chunk["heading_path"]],
                                                    "source_oversized": source_chunk["oversized"]})
            for unit in section_units:
                unit["block_ids"] = list(dict.fromkeys([h["block_id"] for h in ancestry] + unit["block_ids"]))
                unit["source_chunk_ids"] = [source_chunk["chunk_id"]]
            units.extend(section_units)
        for unit in units:
            if not unit["source_chunk_ids"]:
                unit["source_chunk_ids"] = list(dict.fromkeys(chunk_for_block[bid] for bid in unit["block_ids"]))
            diagnostics = json.loads(unit["diagnostics_json"])
            diagnostics.update(selection_status=document["selection"]["status"],
                               quality_flags=document["selection"].get("quality_flags", []))
            unit["diagnostics_json"] = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
        return units
    stack, content, section_id = [], [], "preamble"

    def emit():
        text, local_spans = serialize(content, by_id)
        prefix = "\n".join(render_block(h, by_id) for h in stack)
        prefix = prefix + "\n\n" if prefix else ""
        if not content and not prefix:
            return
        section_units = text_units(sid, eid, "section", "section", text, chunk, spans=local_spans,
                                   section_id=section_id, prefix=prefix,
                                   diagnostics={"heading_ids": [h["block_id"] for h in stack]})
        for unit in section_units:
            unit["block_ids"] = list(dict.fromkeys([h["block_id"] for h in stack] + unit["block_ids"]))
        units.extend(section_units)

    for block in blocks:
        if block["type"] == "heading":
            emit()
            content = []
            level = block.get("heading_level") or 1
            while stack and (stack[-1].get("heading_level") or 1) >= level:
                stack.pop()
            stack.append(block)
            section_id = block["block_id"]
        else:
            content.append(block)
    emit()
    return units


def prepare(input_root, output, config, *, raw_root=None, limit=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Preparation requires an empty output directory; use a new run ID")
    documents, records, upstream = load_upstream(input_root, raw_root, limit)
    units, by_snapshot = [], {}
    for doc in documents:
        units.extend(document_units(doc, config))
        by_snapshot[doc["snapshot"]["snapshot_id"]] = {key: doc[key] for key in ("snapshot", "selection", "extraction_id")}
    queries, associations = {}, []
    for record in records:
        prompt = record["prompt"]
        qid = digest([SERIALIZER_VERSION, "query", prompt])
        if qid not in queries:
            if len(prompt.encode()) > config["page_bytes"]:
                query = make_unit(None, None, "query", "query", prompt, status="unavailable", reason="query_exceeds_common_limit")
            else:
                query = make_unit(None, None, "query", "query", prompt,
                                  status="ready" if prompt.strip() else "unavailable", reason=None if prompt.strip() else "blank_prompt")
            query["unit_id"] = qid
            queries[qid] = query
        doc = by_snapshot[record["snapshot_id"]]
        if urldefrag(record["href"].strip())[0] != urldefrag(doc["snapshot"]["href"].strip())[0]:
            raise ValueError("Record/saved-document URL mismatch")
        if record["payload_hash"] != doc["snapshot"]["payload_hash"]:
            raise ValueError("Record/saved-document payload mismatch")
        associations.append({"source_record_id": record.get("source_record_id", record["record_id"]),
                             "source_file": record.get("source_file"), "source_file_hash": record.get("source_file_hash"),
                             "source_row": record.get("source_row"), "upstream_exclusions": record.get("upstream_exclusions", []),
                             "record_id": record["record_id"], "snapshot_id": record["snapshot_id"],
                             "extraction_id": doc["extraction_id"], "query_unit_id": qid, "prompt": prompt,
                             "citation_category": record.get("citation_category"), "hostname": record["hostname"],
                             "href": doc["snapshot"]["href"], "payload_hash": record["payload_hash"],
                             "extraction_status": doc["selection"]["status"],
                             "quality_flags": doc["selection"].get("quality_flags") or [], "split": record.get("split")})
    units += list(queries.values())
    units.sort(key=lambda u: u["unit_id"])
    associations.sort(key=lambda a: a["record_id"])
    write_rows(output / "units.parquet", units, UNIT_SCHEMA)
    write_rows(output / "associations.parquet", associations, ASSOCIATION_SCHEMA)
    manifest = {"schema_version": SCHEMA_VERSION, "serializer_version": SERIALIZER_VERSION,
                "configuration": config, "upstream": upstream, "status": "prepared",
                "units": len(units), "records": len(associations),
                "statuses": dict(Counter(u["status"] for u in units)),
                "views": dict(Counter(u["view"] for u in units)),
                "scope": "limited_sample" if limit else "upstream_run", "models": {},
                "artifacts": {name: file_hash(output / name) for name in ("units.parquet", "associations.parquet")}}
    write_json(output / "manifest.json", manifest)
    return manifest


def reuse_inputs(source, output, config):
    """Fork only frozen input artifacts into a new model/execution configuration."""
    import shutil
    from .storage import read_json
    source, output = Path(source), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Input reuse requires an empty output directory")
    manifest = read_json(source / "manifest.json")
    for name in ("units.parquet", "associations.parquet"):
        if file_hash(source / name) != manifest["artifacts"][name]:
            raise ValueError("Frozen input artifact changed")
    if manifest["serializer_version"] != SERIALIZER_VERSION or any(
        config[key] != manifest["configuration"][key] for key in ("chunk_bytes", "page_bytes", "counting_policy")):
        raise ValueError("Input recipe changed; prepare a new input version")
    output.mkdir(parents=True, exist_ok=True)
    names = ("units.parquet", "associations.parquet")
    for name in names:
        shutil.copyfile(source / name, output / name)
    result = {key: manifest[key] for key in ("schema_version", "serializer_version", "upstream", "units", "records", "statuses", "views", "scope")}
    result.update(configuration=config, status="prepared", models={},
                  artifacts={name:file_hash(output / name) for name in names},
                  input_origin={"manifest_hash":file_hash(source / "manifest.json"), "path":str(source.resolve())})
    write_json(output / "manifest.json", result)
    return result
