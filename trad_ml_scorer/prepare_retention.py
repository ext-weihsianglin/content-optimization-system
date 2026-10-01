"""Full-corpus, resumable retention-first parsing joined by exact payload and URL."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np

from preprocessing.runner import time_limit
from preprocessing.schema import snapshot_identity
from scripts.analyze_quality import normalize
from trad_ml_scorer.prepare_lr_data import digest, leakage_audit
from trad_ml_scorer.retention_features import FEATURE_NAMES, FEATURE_VERSION, features_from_document, parse_snapshot


def parse_one(item):
    identity, payload, href, host, source, output = item
    path = Path(output) / f"{identity}.json.gz"
    if path.exists():
        with gzip.open(path, "rt") as stream:
            existing = json.load(stream)
        if existing["snapshot_id"] != identity:
            raise ValueError("Cached snapshot identity mismatch")
        return identity, existing.get("selection", {}).get("status", "parse_error")
    try:
        with time_limit(120):
            doc = parse_snapshot(payload, href, host, source)
        assert doc["snapshot_id"] == identity
    except Exception as error:
        doc = {"snapshot_id": identity, "source": {**source, "href": href, "hostname": host, "payload_hash": digest(payload)},
               "selection": {"status": "parse_error", "method": None}, "error": f"{type(error).__name__}: {error}", "text": "", "blocks": []}
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", compresslevel=3) as stream:
        json.dump(doc, stream, ensure_ascii=False)
    temporary.replace(path)
    return identity, doc["selection"]["status"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--v1-data-dir", type=Path, default=Path("data/lr"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/trad_ml_scorer/v2"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        raise FileExistsError("Completed v2 dataset exists; use a new output directory")
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.input_dir.glob("*.parquet"))}
    paths = [Path("preprocessing") / name for name in ("schema.py", "blocks.py", "quality.py", "select.py", "downstream.py", "adapters/local.py")]
    paths += [Path(__file__), Path(__file__).with_name("retention_features.py")]
    identity = {"source_files": source_hashes, "code_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}, "feature_version": FEATURE_VERSION}
    running = output / "run_identity.json"
    if running.exists():
        if not args.resume or json.loads(running.read_text()) != identity:
            raise ValueError("Use --resume with unchanged source/code, or a fresh output directory")
    else:
        running.write_text(json.dumps(identity, indent=2) + "\n")
    host_splits = json.loads((args.v1_data_dir / "host_splits.json").read_text())
    (output / "host_splits.json").write_text(json.dumps(host_splits, indent=2) + "\n")
    documents = output / "documents"
    documents.mkdir(exist_ok=True)
    con = duckdb.connect()
    raw = con.execute("SELECT prompt,citation_category,href,hostname,html_content,filename,file_row_number FROM read_parquet(?,filename=true,file_row_number=true) ORDER BY filename,file_row_number", [str(args.input_dir / "*.parquet")]).fetchall()
    records, snapshots = [], {}
    from urllib.parse import urldefrag
    for prompt, label, href, host, payload, filename, index in raw:
        assert label in {"top", "bottom"}
        payload_hash, snapshot_id = snapshot_identity(payload, href)
        source = {"source_file": Path(filename).name, "source_file_hash": source_hashes[Path(filename).name], "source_row": index}
        snapshots.setdefault(snapshot_id, (snapshot_id, payload, href, host, source, str(documents)))
        record_id = digest(json.dumps([prompt, label, href, host, payload], ensure_ascii=False))
        records.append({**source, "record_id": record_id, "snapshot_id": snapshot_id, "hostname": host.strip().lower(),
                        "href": urldefrag(href.strip())[0], "prompt": prompt, "prompt_hash": digest(normalize(prompt)),
                        "html_sha256": payload_hash, "is_cited_high": int(label == "top"), "split": host_splits[host.strip().lower()]})
    del raw
    print(f"Parsing {len(snapshots)} exact snapshots for {len(records)} records", flush=True)
    counts = Counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i, (_, status) in enumerate(pool.map(parse_one, snapshots.values(), chunksize=1), 1):
            counts[status] += 1
            if i % 100 == 0 or i == len(snapshots):
                print(f"Parsed {i}/{len(snapshots)}: {dict(counts)}", flush=True)
    del snapshots
    labels, html_hosts, text_hosts = defaultdict(set), defaultdict(set), defaultdict(set)
    features = {}
    for record in records:
        with gzip.open(documents / f"{record['snapshot_id']}.json.gz", "rt") as stream:
            doc = json.load(stream)
        assert doc["snapshot_id"] == record["snapshot_id"] and doc["source"]["payload_hash"] == record["html_sha256"]
        record["status"] = doc["selection"]["status"]
        record["text_sha256"] = digest(normalize(doc["text"]))
        record["text_nonempty"] = bool(doc["text"].strip())
        usable = bool(doc["selection"].get("method")) and record["text_nonempty"]
        record["usable"] = usable
        if usable:
            features[record["record_id"]] = features_from_document(record["prompt"], doc)
        record["clean"] = usable and record["status"] == "selected" and len(doc["text"].split()) >= 100
        labels[record["href"]].add(record["is_cited_high"])
        html_hosts[record["html_sha256"]].add(record["hostname"])
        if record["text_nonempty"]:
            text_hosts[record["text_sha256"]].add(record["hostname"])
    seen = set()
    for record in records:
        reasons = []
        if record["record_id"] in seen:
            reasons.append("exact_duplicate")
        seen.add(record["record_id"])
        if not normalize(record["prompt"]):
            reasons.append("blank_prompt")
        if len(labels[record["href"]]) > 1:
            reasons.append("conflicting_url_labels")
        if len(html_hosts[record["html_sha256"]]) > 1:
            reasons.append("html_shared_across_hosts")
        if record["text_nonempty"] and len(text_hosts[record["text_sha256"]]) > 1:
            reasons.append("retained_text_shared_across_hosts")
        if not record["usable"]:
            reasons.append("no_selected_retained_content")
        record["exclusions"] = reasons
    eligible = [r for r in records if not r["exclusions"]]
    audit = leakage_audit(records)
    old = np.load(args.v1_data_dir / "features.npz")
    old_index = {str(identity): i for i, identity in enumerate(old["ids"])}
    common = np.array([r["record_id"] in old_index for r in eligible])
    x_old = np.full((len(eligible), old["X"].shape[1]), np.nan)
    for i, r in enumerate(eligible):
        if r["record_id"] in old_index:
            j = old_index[r["record_id"]]
            assert old["splits"][j] == r["split"] and old["y"][j] == r["is_cited_high"]
            x_old[i] = old["X"][j]
    np.savez_compressed(output / "features.npz", X=np.array([[features[r["record_id"]][name] for name in FEATURE_NAMES] for r in eligible]),
                        y=np.array([r["is_cited_high"] for r in eligible]), hosts=np.array([r["hostname"] for r in eligible]),
                        splits=np.array([r["split"] for r in eligible]), ids=np.array([r["record_id"] for r in eligible]),
                        clean=np.array([r["clean"] for r in eligible]), common=common, X_v1=x_old)
    with (output / "records.jsonl").open("w") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    v2_ids = {r["record_id"] for r in eligible}
    split_counts = {split: {"rows": sum(r["split"] == split for r in eligible), "hosts": len({r["hostname"] for r in eligible if r["split"] == split}),
                           "common_rows": sum(r["split"] == split and r["record_id"] in old_index for r in eligible)} for split in ("train", "validation", "test")}
    manifest = {**identity, "feature_names": FEATURE_NAMES, "parser_policy": "retention-first-v1", "raw_rows": len(records), "unique_snapshots": sum(counts.values()),
                "snapshot_statuses": dict(counts), "splits": split_counts, "eligible_rows": len(eligible), "common_rows": int(common.sum()),
                "v1_only_rows": len(set(old_index) - v2_ids), "v2_only_rows": len(v2_ids - set(old_index)),
                "exclusions_overlapping": dict(Counter(reason for r in records for reason in r["exclusions"])), "leakage_audit": audit,
                "features_sha256": hashlib.sha256((output / "features.npz").read_bytes()).hexdigest(),
                "test_status": "Reused v1 host benchmark, not a fresh independent holdout", "clean_policy": "selected without source quality flags and >=100 whitespace-separated retained words; differs from v1"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
