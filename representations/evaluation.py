"""Label-blind relevance review manifests and judged-pool ranking metrics."""

from collections import defaultdict
from pathlib import Path

import numpy as np

from .runner import load_vectors
from .storage import content_identity, digest, load_run, read_json, read_rows, write_json


def review_manifest(run, output, cases=120):
    run = Path(run)
    manifest = load_run(run)
    units = read_rows(run / "units.parquet")
    sections = defaultdict(list)
    ready = {u["unit_id"]: u for u in units if u["status"] == "ready"}
    for unit in ready.values():
        if unit["view"] == "section":
            sections[unit["snapshot_id"]].append(unit["unit_id"])
    rows = [r for r in read_rows(run / "associations.parquet") if r["query_unit_id"] in ready and sections[r["snapshot_id"]]]
    lookup = {u["unit_id"]: u for u in units}
    pages = {u["snapshot_id"]: content_identity(u, lookup) for u in units if u["view"] == "page" and not u["subview"].endswith(":chunk")}
    # Host components unite exact payload duplicates so development/holdout do not leak.
    parent = {r["hostname"]: r["hostname"] for r in rows}
    def find(host):
        while parent[host] != host:
            parent[host] = parent[parent[host]]
            host = parent[host]
        return host
    hashes = {}
    for row in rows:
        for key in (row["payload_hash"], pages.get(row["snapshot_id"])):
            if key is None:
                continue
            if key in hashes:
                a, b = find(row["hostname"]), find(hashes[key])
                parent[max(a, b)] = min(a, b)
            hashes[key] = row["hostname"]
    groups = sorted({find(r["hostname"]) for r in rows}, key=lambda x: digest([42, x]))
    dev = set(groups[:max(1, len(groups) // 2)])
    split_by_snapshot = {r["snapshot_id"]: ("development" if find(r["hostname"]) in dev else "heldout") for r in rows}
    selected, seen = [], set()
    for row in sorted(rows, key=lambda r: digest([42, r["record_id"]])):
        key = (row["query_unit_id"], row["snapshot_id"])
        if key in seen:
            continue
        seen.add(key)
        split = "development" if find(row["hostname"]) in dev else "heldout"
        if sum(c["split"] == split for c in selected) >= (cases + 1) // 2:
            continue
        own = sorted(sections[row["snapshot_id"]])
        others = sorted([uid for sid, ids in sections.items() if sid != row["snapshot_id"] and split_by_snapshot.get(sid) == split for uid in ids], key=lambda uid: digest([row["query_unit_id"], uid]))[:5]
        selected.append({"case_id": digest(key), "split": split, "hostname": row["hostname"],
                         "group_id": find(row["hostname"]),
                         "query_unit_id": row["query_unit_id"], "prompt": row["prompt"],
                         "snapshot_id": row["snapshot_id"], "href": row["href"],
                         "candidate_unit_ids": sorted(set(own + others)),
                         "annotations": [{"unit_id": uid, "grade": None, "note": ""} for uid in sorted(set(own + others))]})
    result = {"schema_version": "1.0.0", "run_hash": digest(manifest["upstream"]["hashes"]),
              "unit_artifact_hash": manifest["artifacts"]["units.parquet"],
              "sampling": "Deterministic hostname/payload-group-separated sample; inspect and supplement slice coverage before freezing.",
              "rubric": "0 unrelated; 1 topical but no answer support; 2 partial support; 3 direct source-supported answer. Review all candidates without citation labels.",
              "metric_scope": "Judged candidate pools only; not corpus recall", "cases": selected}
    result["manifest_hash"] = digest(result)
    write_json(output, result)
    return {"cases": len(selected), "development": sum(c["split"] == "development" for c in selected)}


def evaluate(run, model_name, annotations, output, split="heldout"):
    reviewed = read_json(annotations)
    claimed = reviewed.pop("manifest_hash")
    # Annotation fields are intentionally editable; freeze IDs separately from judgments.
    structure = {**reviewed, "cases": [{**c, "annotations": [{"unit_id": a["unit_id"], "grade": None, "note": ""} for a in c["annotations"]]} for c in reviewed["cases"]]}
    if digest(structure) != claimed:
        raise ValueError("Evaluation manifest identity or candidate pools changed")
    vectors, manifest = load_vectors(run, model_name)
    if reviewed["unit_artifact_hash"] != manifest["artifacts"]["units.parquet"]:
        raise ValueError("Evaluation inputs differ from frozen units")
    metrics, exclusions = [], []
    for case in reviewed["cases"]:
        if case["split"] != split:
            continue
        grades = {a["unit_id"]: a["grade"] for a in case["annotations"]}
        ids = case["candidate_unit_ids"]
        if set(grades) != set(ids) or any(type(grades[uid]) is not int or not 0 <= grades[uid] <= 3 for uid in ids):
            raise ValueError("All candidates require integer relevance grades from 0 to 3")
        if case["query_unit_id"] not in vectors or any(uid not in vectors for uid in ids):
            exclusions.append({"case_id": case["case_id"], "reason": "missing_vectors"})
            continue
        ranked = sorted(ids, key=lambda uid: (-float(vectors[case["query_unit_id"]] @ vectors[uid]), uid))
        def dcg(order):
            return sum((2 ** grades[uid] - 1) / np.log2(index + 2) for index, uid in enumerate(order[:5]))
        ideal = dcg(sorted(ids, key=lambda uid: -grades[uid]))
        relevant = {uid for uid in ids if grades[uid] >= 2}
        metrics.append({"case_id": case["case_id"], "hostname": case["hostname"], "group_id": case["group_id"], "ndcg_at_5": dcg(ranked) / ideal if ideal else None,
                        "recall_at_5": len(set(ranked[:5]) & relevant) / len(relevant) if relevant else None,
                        "relevant_candidates": len(relevant), "judged_candidates": len(ids)})
    result = {"model": model_name, "split": split, "scope": "judged pools only", "cases": metrics, "exclusions": exclusions}
    for name in ("ndcg_at_5", "recall_at_5"):
        values = [r[name] for r in metrics if r[name] is not None]
        by_group = defaultdict(list)
        for row in metrics:
            if row[name] is not None:
                by_group[row["group_id"]].append(row[name])
        group_values = [np.mean(v) for v in by_group.values()]
        rng = np.random.default_rng(42)
        samples = [np.mean(rng.choice(group_values, len(group_values), replace=True)) for _ in range(200)] if group_values else []
        result[name] = {"mean": float(np.mean(values)) if values else None, "denominator": len(values),
                        "group_weighted_mean": float(np.mean(group_values)) if group_values else None,
                        "independent_groups": len(group_values),
                        "group_bootstrap_95_interval": np.quantile(samples, [.025, .975]).tolist() if samples else None}
    write_json(output, result)
    return result
