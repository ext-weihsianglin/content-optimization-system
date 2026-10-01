"""Freeze a hostname-disjoint snapshot evaluation set before candidate execution."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
import duckdb

from preprocessing.schema import snapshot_identity, stable_hash


ROOT = Path(__file__).resolve().parents[1]
QUOTAS = [("markdown", 8, 5), ("text", 4, 2), ("source_failure", 8, 5), ("sparse", 4, 2), ("table", 12, 7), ("documentation", 8, 5), ("commerce", 8, 5), ("homepage", 8, 5), ("multilingual", 8, 5), ("editorial", 20, 12), ("other", 12, 7)]
SEED = "snapshot-eval-v1-20261001"


def enforce_payload_disjoint(snapshots):
    groups = defaultdict(list)
    for row in snapshots:
        groups[row["payload_hash"]].append(row)
    for rows in groups.values():
        if len({row["split"] for row in rows}) > 1:
            for row in rows:
                row["split"] = "dev"
    surplus = sum(row["split"] == "dev" for row in snapshots) - 60
    candidates = sorted((row for row in snapshots if len(groups[row["payload_hash"]]) == 1), key=lambda row: stable_hash([SEED, "payload-disjoint-rebalance", row["hostname"]]))
    origin, destination = ("dev", "heldout") if surplus > 0 else ("heldout", "dev")
    for row in [row for row in candidates if row["split"] == origin][:abs(surplus)]:
        row["split"] = destination
    assert sum(row["split"] == "dev" for row in snapshots) == 60


def repair_preexecution_manifest():
    if list((ROOT / "data/processed").glob("**/results.jsonl")):
        raise ValueError("Cannot revise the split after extraction execution")
    path = ROOT / "evaluation/extraction/manifest.json"
    manifest = json.loads(path.read_text())
    old_hash = manifest.pop("manifest_hash")
    enforce_payload_disjoint(manifest["snapshots"])
    manifest["split_revision"] = {"previous_manifest_hash": old_hash, "reason": "Pre-execution invariant check found four identical not-implemented payloads at different hostnames. Grouped identical payloads in development and deterministically moved two singleton hosts to heldout. No candidate results existed.", "nominal_quotas": "Per-stratum development quotas are targets; payload-group isolation takes precedence."}
    manifest["manifest_hash"] = stable_hash(manifest)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(manifest["manifest_hash"])


def query_records(connection, query):
    cursor = connection.execute(query)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def source_blocks(payload, format):
    if format != "html":
        pieces = [text.strip() for text in re.split(r"\n\s*\n", payload) if text.strip()]
        return "", [{"tag": "text", "context": "stored payload", "text": piece} for piece in pieces]
    soup = BeautifulSoup(payload, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for node in soup.select("script,style,noscript,template,svg,head"):
        node.decompose()
    blocks = []
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "td", "th", "pre"]):
        if node.find_parent(["p", "li", "td", "th", "pre"]):
            continue
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        context = " > ".join(parent.name + ("#" + parent.get("id") if parent.get("id") else "") for parent in list(node.parents)[:4] if parent.name)
        blocks.append({"tag": node.name, "context": context, "text": text})
    if not blocks:
        blocks = [{"tag": "body", "context": "entire saved payload", "text": soup.get_text(" ", strip=True)}]
    return title, blocks


def materialize(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    claimed = manifest.pop("manifest_hash")
    if stable_hash(manifest) != claimed:
        raise ValueError("Frozen manifest hash mismatch")
    connection = duckdb.connect()
    private = ROOT / "data/evaluation"
    private.mkdir(parents=True, exist_ok=True)
    for filename, expected in manifest["input_hashes"].items():
        path = ROOT / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source parquet hash mismatch: {filename}")
        entries = [entry for entry in manifest["snapshots"] if entry["source_file"] == filename]
        rows = connection.execute("SELECT file_row_number, html_content FROM read_parquet(?, file_row_number=true) WHERE file_row_number IN (SELECT unnest(?))", [str(path), [entry["source_row"] for entry in entries]]).fetchall()
        payloads = dict(rows)
        for entry in entries:
            payload = payloads[entry["source_row"]]
            if snapshot_identity(payload, entry["href"]) != (entry["payload_hash"], entry["snapshot_id"]):
                raise ValueError("Saved source differs from frozen snapshot")
            snapshot_id = entry["snapshot_id"]
            (private / f"{snapshot_id}.txt").write_text(payload)
            title, blocks = source_blocks(payload, entry["format"])
            source = {"snapshot_id": snapshot_id, "href": entry["href"], "format": entry["format"], "title": title, "blocks": blocks}
            (private / f"{snapshot_id}.source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2))
    print(f"Materialized {len(manifest['snapshots'])} frozen snapshots without resampling")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evaluation/extraction")
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args()
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    if args.materialize:
        materialize(output / "manifest.json")
        return
    if (output / "manifest.json").exists():
        raise SystemExit("Evaluation manifest already frozen; use a new output directory to define another split.")
    connection = duckdb.connect()
    connection.execute("CREATE VIEW raw AS SELECT * FROM read_parquet('data/raw/*.parquet', filename=true, file_row_number=true)")
    metadata = query_records(connection, "SELECT filename, file_row_number, href, hostname FROM raw ORDER BY filename,file_row_number")
    quality = query_records(connection, "SELECT * FROM 'analysis/quality_flags.parquet'")
    features = query_records(connection, "SELECT href,has_table,title,html_chars FROM 'analysis/content_features.parquet'")
    quality_by_url = {}
    for row in quality:
        current = quality_by_url.setdefault(row["href"], {"hints": set(), "html": False, "markdown": False, "failure": False, "sparse": False})
        current["hints"].update(row["path_hints"])
        for target, source in [("html", "html_markup"), ("markdown", "markdown_like_without_html"), ("failure", "clear_failure_union"), ("sparse", "sparse_body_candidate")]:
            current[target] |= bool(row[source])
    feature_by_url = {row["href"]: row for row in features}
    sampled_urls = {row[0] for row in connection.execute("SELECT href FROM read_csv('analysis/citation-sample-500.csv', all_varchar=true,max_line_size=20000000)").fetchall()}
    used_hosts = set()
    selected = []

    def eligible(row, stratum):
        quality_row = quality_by_url[row["href"]]
        feature = feature_by_url.get(row["href"], {})
        if stratum == "markdown":
            return quality_row["markdown"] and not quality_row["html"]
        if stratum == "text":
            return not quality_row["html"] and not quality_row["markdown"]
        if not quality_row["html"]:
            return False
        if stratum == "source_failure":
            return quality_row["failure"]
        if stratum == "sparse":
            return quality_row["sparse"] and not quality_row["failure"]
        if quality_row["failure"] or quality_row["sparse"]:
            return False
        return {"table": feature.get("has_table", False), "documentation": "support_docs" in quality_row["hints"], "commerce": "commerce" in quality_row["hints"], "homepage": "homepage" in quality_row["hints"], "multilingual": bool(re.search(r"[\u0900-\u097f\u3040-\u30ff\u4e00-\u9fff\u0600-\u06ff]|\b(?:der|und|les|pour|avec|für|para)\b", feature.get("title", ""), re.I)), "editorial": "editorial" in quality_row["hints"], "other": not quality_row["hints"]}.get(stratum, False)

    for stratum, count, development in QUOTAS:
        ranked = sorted((row for row in metadata if eligible(row, stratum)), key=lambda row: (row["href"] not in sampled_urls, stable_hash([SEED, stratum, row["filename"], row["file_row_number"]])))
        taken = []
        for row in ranked:
            if row["hostname"] in used_hosts:
                continue
            used_hosts.add(row["hostname"])
            taken.append(row)
            if len(taken) == count:
                break
        if len(taken) != count:
            raise ValueError(f"Insufficient distinct hosts for {stratum}: {len(taken)}/{count}")
        taken.sort(key=lambda row: stable_hash([SEED, "split", row["hostname"]]))
        selected.extend({**row, "stratum": stratum, "split": "dev" if index < development else "heldout", "from_500_row_sample": row["href"] in sampled_urls} for index, row in enumerate(taken))
    connection.execute("CREATE TEMP TABLE chosen(filename VARCHAR,file_row_number BIGINT)")
    connection.executemany("INSERT INTO chosen VALUES (?,?)", [(row["filename"], row["file_row_number"]) for row in selected])
    payloads = {(row[0], row[1]): row[2] for row in connection.execute("SELECT raw.filename,raw.file_row_number,html_content FROM raw JOIN chosen USING(filename,file_row_number)").fetchall()}
    input_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT / "data/raw").glob("*.parquet"))}
    private = ROOT / "data/evaluation"
    private.mkdir(parents=True, exist_ok=True)
    snapshots = []
    review_documents = []
    for row in selected:
        payload = payloads[(row["filename"], row["file_row_number"])]
        payload_hash, snapshot_id = snapshot_identity(payload, row["href"])
        format = "markdown" if row["stratum"] == "markdown" else "text" if row["stratum"] == "text" else "html"
        snapshot = {"snapshot_id": snapshot_id, "payload_hash": payload_hash, "href": row["href"], "hostname": row["hostname"], "format": format, "split": row["split"], "stratum": row["stratum"], "source_file": row["filename"], "source_file_hash": input_hashes[row["filename"]], "source_row": row["file_row_number"], "from_500_row_sample": row["from_500_row_sample"]}
        snapshots.append(snapshot)
        (private / f"{snapshot_id}.txt").write_text(payload)
        title, blocks = source_blocks(payload, format)
        full = {"snapshot_id": snapshot_id, "href": row["href"], "format": format, "title": title, "blocks": blocks}
        (private / f"{snapshot_id}.source.json").write_text(json.dumps(full, ensure_ascii=False, indent=2))
        meaningful = [block for block in blocks if len(block["text"]) >= 60 and not re.search(r"nav|footer", block["context"], re.I)]
        nav = [block for block in blocks if re.search(r"nav|footer", block["context"], re.I) and len(block["text"]) >= 12]
        headings = [block for block in blocks if re.fullmatch(r"h[1-6]", block["tag"])]
        sampled = []
        for pool, limit in [(headings, 8), (meaningful, 16), (nav, 4)]:
            indices = sorted({round(index * (len(pool) - 1) / max(1, min(limit, len(pool)) - 1)) for index in range(min(limit, len(pool)))}) if pool else []
            sampled.extend({**pool[index], "text": pool[index]["text"][:1000]} for index in indices)
        if not sampled:
            sampled = [{**block, "text": block["text"][:2000]} for block in blocks[:8]]
        review_documents.append({**full, "blocks": sampled, "all_source_blocks_path": str((private / f"{snapshot_id}.source.json").relative_to(ROOT)), "source_sample_note": "Bounded, evenly spaced source DOM blocks; full source block file available. Not candidate extraction output."})
    enforce_payload_disjoint(snapshots)
    manifest = {"version": 1, "seed": SEED, "sampling": "100 distinct hostnames, one snapshot each; source format/page-type strata. Prioritize URLs in existing 500-row sample, supplement from full corpus. Split assigned within strata by seeded host hash, then identical payloads grouped with deterministic rebalancing to 60/40. No citation labels/queries exported.", "row_numbering": "zero-based", "input_hashes": input_hashes, "quotas": QUOTAS, "snapshots": snapshots}
    manifest["manifest_hash"] = stable_hash(manifest)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    for batch in range(4):
        documents = review_documents[batch::4]
        (private / f"review-batch-{batch + 1}.json").write_text(json.dumps(documents, indent=2, ensure_ascii=False))
    print(json.dumps({"snapshots": len(snapshots), "hosts": len(used_hosts), "split": dict(Counter(row["split"] for row in snapshots)), "format": dict(Counter(row["format"] for row in snapshots)), "manifest_hash": manifest["manifest_hash"]}, indent=2))


if __name__ == "__main__":
    main()
