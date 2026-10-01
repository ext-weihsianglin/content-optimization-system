"""Curate a bounded, label-blind development pilot from frozen LR documents."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "teacher-curation-v1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def query_type(query):
    words = query.lower().split()
    if any(w.strip("?.,") in {"best", "compare", "comparison", "versus", "vs", "cheapest"} for w in words):
        return "comparison"
    if "how to" in query.lower():
        return "procedure"
    if "?" in query or (words and words[0] in {"what", "which", "why", "when", "where", "who", "how"}):
        return "question"
    return "other"


def page_role(href):
    path = urlsplit(href).path.lower()
    if path in {"", "/"}:
        return "homepage"
    pieces = set(path.split("/"))
    if pieces & {"blog", "guides", "articles", "news"}:
        return "editorial"
    if pieces & {"products", "product", "shop", "pricing"}:
        return "commerce"
    if pieces & {"docs", "help", "faq", "support"}:
        return "support"
    return "other"


def development_pool(records, host_splits, max_candidates=900):
    """One record per development host; never inspect test documents or labels.

    Prioritize underrepresented metadata strata without looking at outcomes.
    Query/page-role tags are curation heuristics, not teacher labels.
    """
    eligible = []
    for row in records:
        if row["split"] not in {"train", "validation"}:
            continue
        if row["exclusions"] or not row.get("usable") or not row["prompt"].strip():
            continue
        if host_splits.get(row["hostname"]) != row["split"]:
            raise ValueError("Frozen hostname split mismatch")
        eligible.append(row)
    tags = lambda r: (query_type(r["prompt"]), page_role(r["href"]), r["status"])
    frequencies = Counter(tags(r) for r in eligible)
    ranked = sorted(eligible, key=lambda r: (frequencies[tags(r)], sha256((VERSION + r["record_id"]).encode())))
    seen, pool = set(), []
    for row in ranked:
        if row["hostname"] not in seen:
            seen.add(row["hostname"])
            pool.append(row)
            if len(pool) >= max_candidates:
                break
    return pool


def load_case(row, documents):
    path = documents / f"{row['snapshot_id']}.json.gz"
    compressed = path.read_bytes()
    doc = json.loads(gzip.decompress(compressed))
    if doc["snapshot_id"] != row["snapshot_id"] or doc["source"]["payload_hash"] != row["html_sha256"]:
        raise ValueError("Cached document/source identity mismatch")
    if not doc.get("blocks") or not doc.get("text", "").strip():
        raise ValueError("Eligible cached document has no content")
    ids = [b["block_id"] for b in doc["blocks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source block IDs")
    length = len(doc["text"].split())
    strata = {
        "query_type": query_type(row["prompt"]), "page_role": page_role(row["href"]),
        "status": row["status"], "source_format": doc["source"]["format"],
        "length": "short" if length < 500 else "medium" if length < 3000 else "long",
        "tables": "present" if any(b["type"] == "table" for b in doc["blocks"]) else "absent",
        "code": "present" if any(b["type"] == "code" for b in doc["blocks"]) else "absent",
    }
    # Citation labels and LR scores are deliberately not copied into this contract.
    case = {k: row[k] for k in ("record_id", "snapshot_id", "hostname", "split", "prompt", "html_sha256")}
    case.update(document_sha256=sha256(compressed), strata=strata, word_count=length,
                block_count=len(ids), quality_flags=doc["selection"].get("quality_flags", []))
    return case, doc


def select_cases(cases, train_count, validation_count):
    selected = []
    for split, count in (("train", train_count), ("validation", validation_count)):
        remaining = [c for c in cases if c["split"] == split]
        if len(remaining) < count:
            raise ValueError(f"Need {count} distinct {split} hosts; only {len(remaining)} available")
        frequencies = Counter((k, v) for c in remaining for k, v in c["strata"].items())
        covered = Counter()
        for _ in range(count):
            def priority(case):
                gain = sum(1 / ((1 + covered[k, v]) * frequencies[k, v]) for k, v in case["strata"].items())
                return (-gain, sha256((VERSION + case["record_id"]).encode()))
            chosen = min(remaining, key=priority)
            remaining.remove(chosen)
            selected.append(chosen)
            covered.update(chosen["strata"].items())
    return selected


def counts(cases):
    result = {"split": dict(Counter(c["split"] for c in cases))}
    for key in ("query_type", "page_role", "status", "source_format", "length", "tables", "code"):
        result[key] = dict(sorted(Counter(c["strata"][key] for c in cases).items()))
    return result


def curate(source, output, train_count=96, validation_count=24, max_candidates=900):
    if output.exists():
        raise FileExistsError("Use a new curation directory; frozen outputs are never overwritten")
    if train_count < 12 or validation_count < 1 or max_candidates < train_count + validation_count:
        raise ValueError("Need at least 12 train/1 validation cases and a sufficient bounded pool")
    records_path, hosts_path = source / "records.jsonl", source / "host_splits.json"
    records = [json.loads(line) for line in records_path.open()]
    hosts = json.loads(hosts_path.read_text())
    pool = development_pool(records, hosts, max_candidates)
    loaded = [load_case(row, source / "documents")[0] for row in pool]
    selected = select_cases(loaded, train_count, validation_count)
    # Preserve diversity for the first 12 training cases and a distinct-host review queue.
    smoke = select_cases([c for c in selected if c["split"] == "train"], 12, 0)
    smoke_ids = {c["record_id"] for c in smoke}
    review = sorted(selected, key=lambda c: sha256(("review-v1" + c["record_id"]).encode()))[:max(1, len(selected) // 4)]
    for c in selected:
        c["smoke"] = c["record_id"] in smoke_ids
        c["independent_review"] = c in review
    if len({c["hostname"] for c in selected}) != len(selected):
        raise ValueError("Pilot must contain distinct hosts")
    source_manifest = json.loads((source / "manifest.json").read_text())
    manifest = {
        "version": VERSION, "source_feature_version": source_manifest["feature_version"],
        "source_records_sha256": sha256(records_path.read_bytes()),
        "source_manifest_sha256": sha256((source / "manifest.json").read_bytes()),
        "host_splits_sha256": sha256(hosts_path.read_bytes()),
        "source_files": source_manifest["source_files"], "source_parser_policy": source_manifest["parser_policy"],
        "candidate_limit": max_candidates, "candidate_count": len(loaded),
        "candidate_counts": counts(loaded), "selected_counts": counts(selected),
        "selection_policy": "rare metadata strata, one per host, bounded cached-document pool; inverse-frequency coverage",
        "test_documents_loaded": 0, "labels_used_for_selection": False,
        "smoke_ids": sorted(smoke_ids), "review_ids": sorted(c["record_id"] for c in review),
        "teacher_model": None, "teacher_status": "awaiting_user_model_choice",
        "limitations": ["Curated development pilot, not a random corpus sample or held-out evaluation",
                        "Strata are heuristic; no human or teacher quality labels yet",
                        "Document byte hashes frozen now; source payload identity checked against cached metadata, not raw re-extraction"],
        "cases": selected,
    }
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train", type=int, default=96)
    parser.add_argument("--validation", type=int, default=24)
    parser.add_argument("--max-candidates", type=int, default=900)
    args = parser.parse_args()
    manifest = curate(args.source, args.output, args.train, args.validation, args.max_candidates)
    print(json.dumps({"selected": manifest["selected_counts"], "candidate_count": manifest["candidate_count"],
                      "teacher_status": manifest["teacher_status"]}, indent=2))


if __name__ == "__main__":
    main()
