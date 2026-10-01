"""Controlled structural measurements, separate from real-page anchor metrics."""

import json
from pathlib import Path
import time

from preprocessing.adapters.external import ReadabilityWorker, extract_trafilatura
from preprocessing.adapters.local import extract_baseline, extract_conservative, extract_markdown_text
from preprocessing.blocks import html_to_blocks, blocks_to_text
from preprocessing.evaluate import normalize_anchor
from preprocessing.offline import network_disabled
from preprocessing.schema import Snapshot, snapshot_identity


def check_structure(blocks, expected):
    outcomes = {}
    if "heading" in expected:
        outcomes["heading"] = any(block["type"] == "heading" and normalize_anchor(expected["heading"]) == normalize_anchor(block["text"]) for block in blocks)
    if "code" in expected:
        outcomes["code_whitespace"] = any(block["type"] == "code" and expected["code"].rstrip("\n") == block["text"].rstrip("\n") for block in blocks)
    if expected.get("nested_list"):
        by_id = {block["block_id"]: block for block in blocks}
        outcomes["nested_list"] = any(block["type"] == "list" and block.get("parent_id") in by_id and by_id[block["parent_id"]]["type"] == "list_item" for block in blocks)
    if "table_cells" in expected:
        tables = [block["table"] for block in blocks if block["type"] == "table" and block.get("table")]
        for index, cell in enumerate(expected["table_cells"]):
            outcomes[f"table_cell_{index}"] = any(any(all(actual.get(key) == value for key, value in cell.items()) for actual in table["cells"]) for table in tables)
    return outcomes


def main():
    fixtures = json.loads(Path("evaluation/extraction/fixtures.json").read_text())
    methods = ["baseline", "trafilatura", "readability", "conservative_dom", "markdown_text"]
    results = []
    with network_disabled(), ReadabilityWorker() as worker:
        for case in fixtures["cases"]:
            href = f"https://offline.invalid/{case['id']}"
            payload_hash, snapshot_id = snapshot_identity(case["payload"], href)
            snapshot = Snapshot(snapshot_id, payload_hash, href, "offline.invalid", case["payload"], case["format"])
            for method in methods:
                begin = time.perf_counter()
                result = worker.extract(snapshot) if method == "readability" else {"baseline": extract_baseline, "trafilatura": extract_trafilatura, "conservative_dom": extract_conservative, "markdown_text": extract_markdown_text}[method](snapshot)
                if result.status == "ok" and result.html and not result.blocks:
                    result.blocks = html_to_blocks(result.html, href, source_html=case["payload"])
                if result.status == "ok" and result.blocks and method != "baseline":
                    result.text = blocks_to_text(result.blocks)
                supported = result.status != "unsupported_format"
                text = normalize_anchor(result.text)
                required_hits = sum(normalize_anchor(anchor) in text for anchor in case["required"])
                unwanted_hits = sum(normalize_anchor(anchor) in text for anchor in case["unwanted"])
                outcomes = check_structure(result.blocks, case["structure"]) if supported else {}
                results.append({"fixture": case["id"], "format": case["format"], "method": method, "status": result.status, "supported": supported, "required_hits": required_hits, "required_total": len(case["required"]) if supported else 0, "unwanted_hits": unwanted_hits, "unwanted_total": len(case["unwanted"]) if supported else 0, "structural_checks": outcomes, "runtime_ms": round((time.perf_counter() - begin) * 1000, 3)})
    aggregates = []
    for source_format in ["all", "html", "non_html"]:
        for method in methods:
            rows = [row for row in results if row["method"] == method and row["supported"] and (source_format == "all" or (row["format"] == "html") == (source_format == "html"))]
            aggregates.append({"subset": source_format, "method": method, "supported_cases": len(rows), "required_hits": sum(row["required_hits"] for row in rows), "required_total": sum(row["required_total"] for row in rows), "unwanted_hits": sum(row["unwanted_hits"] for row in rows), "unwanted_total": sum(row["unwanted_total"] for row in rows), "structural_passed": sum(sum(row["structural_checks"].values()) for row in rows), "structural_total": sum(len(row["structural_checks"]) for row in rows)})
    report = {"type": "synthetic_structural_fixtures", "limitations": "Eight hand-authored controlled inputs. These engineering checks are not held-out real-page structure accuracy or human-reviewed corpus quality. Fixtures were defined before their candidate outputs were inspected.", "groups": aggregates, "results": results}
    destination = Path("analysis/extraction-fixtures.json")
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(aggregates[:5], indent=2))


if __name__ == "__main__":
    main()
