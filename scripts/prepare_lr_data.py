"""Build row-level features and a frozen hostname split before any model fitting."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import random
from urllib.parse import urldefrag

import duckdb
import numpy as np

from analyze_content import extract
from analyze_quality import normalize, probe
from lr_features import FEATURE_NAMES, FEATURE_VERSION, features_from_extraction


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def assign_hosts(hosts, seed=42):
    hosts = sorted(set(hosts))
    random.Random(seed).shuffle(hosts)
    train_end, val_end = int(len(hosts) * .8), int(len(hosts) * .9)
    return {host: "train" if i < train_end else "validation" if i < val_end else "test" for i, host in enumerate(hosts)}


def extract_record(row):
    prompt, label, href, host, html, filename, file_row = row
    page = extract(html)
    flags = probe((prompt, label, href, host, html))["flags"]
    features = features_from_extraction(prompt, href, page, flags)
    return {
        "source_file": Path(filename).name, "source_row": file_row,
        "record_id": digest(json.dumps([prompt, label, href, host, html], ensure_ascii=False)),
        "hostname": host.strip().lower(), "href": urldefrag(href.strip())[0],
        "prompt_hash": digest(normalize(prompt)), "blank_prompt": not normalize(prompt),
        "html_sha256": digest(html), "text_sha256": digest(normalize(page["extracted_text"])),
        "text_nonempty": bool(page["extracted_text"].strip()), "is_cited_high": int(label == "top"),
        "clean": bool(flags["html_markup"] and not flags["clear_failure_union"] and not flags["sparse_body_candidate"] and page["word_count"] >= 100),
        "features": features,
    }


def prepare(records, host_splits):
    labels = defaultdict(set)
    html_hosts, text_hosts = defaultdict(set), defaultdict(set)
    for row in records:
        labels[row["href"]].add(row["is_cited_high"])
        html_hosts[row["html_sha256"]].add(row["hostname"])
        if row["text_nonempty"]:
            text_hosts[row["text_sha256"]].add(row["hostname"])
    seen = set()
    for row in records:
        reasons = []
        if row["record_id"] in seen:
            reasons.append("exact_duplicate")
        seen.add(row["record_id"])
        if row["blank_prompt"]:
            reasons.append("blank_prompt")
        if len(labels[row["href"]]) > 1:
            reasons.append("conflicting_url_labels")
        # Exclude all copies, independent of split and outcome, avoiding split-priority bias.
        if len(html_hosts[row["html_sha256"]]) > 1:
            reasons.append("html_shared_across_hosts")
        if row["text_nonempty"] and len(text_hosts[row["text_sha256"]]) > 1:
            reasons.append("text_shared_across_hosts")
        row["split"] = host_splits[row["hostname"]]
        row["exclusions"] = reasons
    return records


def leakage_audit(records):
    eligible = [r for r in records if not r["exclusions"]]
    result = {}
    for key in ("hostname", "href", "html_sha256", "text_sha256", "record_id", "prompt_hash"):
        sets = {split: {r[key] for r in eligible if r["split"] == split and (key != "text_sha256" or r["text_nonempty"])} for split in ("train", "validation", "test")}
        overlaps = {f"{a}__{b}": len(sets[a] & sets[b]) for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))}
        result[key] = overlaps
        if key != "prompt_hash":
            assert not any(overlaps.values()), (key, overlaps)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/lr"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.output_dir / "manifest.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing to replace frozen dataset: {manifest}; use a new output directory")
    con = duckdb.connect()
    source = con.execute("SELECT prompt, citation_category, href, hostname, html_content, filename, file_row_number FROM read_parquet(?, filename=true, file_row_number=true) ORDER BY filename, file_row_number", [str(args.input_dir / "*.parquet")]).fetchall()
    assert all(row[1] in {"top", "bottom"} for row in source)
    host_splits = assign_hosts(row[3].strip().lower() for row in source)
    (args.output_dir / "host_splits.json").write_text(json.dumps(host_splits, indent=2, sort_keys=True) + "\n")
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(extract_record, source, chunksize=10):
            records.append(row)
            if len(records) % 500 == 0:
                print(f"Extracted {len(records)}/{len(source)}", flush=True)
    prepare(records, host_splits)
    audit = leakage_audit(records)
    eligible = [r for r in records if not r["exclusions"]]
    np.savez_compressed(args.output_dir / "features.npz",
        X=np.array([[r["features"][f] for f in FEATURE_NAMES] for r in eligible]),
        y=np.array([r["is_cited_high"] for r in eligible]),
        hosts=np.array([r["hostname"] for r in eligible]),
        splits=np.array([r["split"] for r in eligible]),
        clean=np.array([r["clean"] for r in eligible]),
        ids=np.array([r["record_id"] for r in eligible]))
    with (args.output_dir / "records.jsonl").open("w") as stream:
        for row in records:
            meta = {k: v for k, v in row.items() if k != "features"}
            stream.write(json.dumps(meta) + "\n")
    with (args.output_dir / "features.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(["record_id", "split", "is_cited_high", *FEATURE_NAMES])
        for row in eligible:
            writer.writerow([row["record_id"], row["split"], row["is_cited_high"], *[row["features"][f] for f in FEATURE_NAMES]])
    split_counts = {s: {"rows": sum(r["split"] == s for r in eligible), "hosts": len({r["hostname"] for r in eligible if r["split"] == s}), "positive": sum(r["is_cited_high"] for r in eligible if r["split"] == s), "clean_rows": sum(r["clean"] for r in eligible if r["split"] == s)} for s in ("train", "validation", "test")}
    payload = {
        "feature_version": FEATURE_VERSION, "feature_names": FEATURE_NAMES, "seed": 42,
        "split_method": "Python random.Random(42) shuffle of sorted unique normalized hostnames; first 80% train, next 10% validation, remaining test",
        "raw_rows": len(records), "eligible_rows": len(eligible), "splits": split_counts,
        "exclusions_overlapping": dict(Counter(reason for r in records for reason in r["exclusions"])),
        "leakage_audit": audit,
        "clean_policy": "Per-snapshot recognized HTML, no heuristic failure or <=30-body-token flag, >=100 extracted words; evaluation subset only",
        "source_files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.input_dir.glob("*.parquet"))},
        "extractor_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), Path(__file__).with_name("lr_features.py"), Path(__file__).with_name("analyze_content.py"), Path(__file__).with_name("analyze_quality.py")]},
    }
    payload["features_sha256"] = hashlib.sha256((args.output_dir / "features.npz").read_bytes()).hexdigest()
    manifest.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
