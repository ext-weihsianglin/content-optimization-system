"""Host-grouped exploratory ablations; all learned transforms fit in-fold."""

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .runner import load_vectors
from .storage import content_identity, read_rows, write_json


def analyze(run, model_name, output):
    run = Path(run)
    vectors, manifest = load_vectors(run, model_name)
    alignment = manifest.get("alignment", {}).get(model_name)
    if alignment is None:
        raise ValueError("Run align before analyze")
    vector_path = f"vectors/{manifest['models'][model_name]['config_id']}/vectors.npy"
    if alignment["vector_hash"] != manifest["artifacts"][vector_path]:
        raise ValueError("Alignment is stale after embedding changes")
    aligned = read_rows(run / alignment["path"])
    units = read_rows(run / "units.parquet")
    unit_lookup = {u["unit_id"]: u for u in units}
    pages = {u["snapshot_id"]: u for u in units if u["view"] == "page" and not u["subview"].endswith(":chunk") and u["unit_id"] in vectors}
    grouped = defaultdict(list)
    for row in aligned:
        grouped[row["href"]].append(row)
    features = ("title_similarity", "h1_similarity", "outline_similarity", "page_similarity",
                "section_max", "section_top3_mean", "section_median", "section_q25", "section_q75", "section_chunk_count")
    structure_names = ("word_count", "heading_count", "table_count", "list_count", "code_count")
    rows, excluded = [], []
    for href, associations in sorted(grouped.items()):
        labels = {a["citation_category"] for a in associations}
        if not labels <= {"top", "bottom"} or len(labels) != 1:
            excluded.append({"href": href, "reason": "ambiguous_or_unknown_label"})
            continue
        # Collapse exact prompt/snapshot repeats, then average snapshots per query,
        # then queries per URL. One URL contributes one prediction/weight.
        dedup = {(a["prompt"], a["snapshot_id"]): a for a in associations if a["snapshot_id"] in pages and a["status"] == "available"}
        if not dedup:
            excluded.append({"href": href, "reason": "no_usable_alignment"})
            continue
        def mean(values):
            known = [v for v in values if v is not None and np.isfinite(v)]
            return float(np.mean(known)) if known else np.nan
        prompts = defaultdict(list)
        for association in dedup.values():
            prompts[association["prompt"]].append(association)
        semantic = [mean([mean([a[f] for a in group]) for group in prompts.values()]) for f in features]
        path = mean([mean([a["path_similarity"] for a in group]) for group in prompts.values()])
        sids = sorted({a["snapshot_id"] for a in dedup.values()})
        structural = [mean([json.loads(pages[sid]["diagnostics_json"])["structure"][name] for sid in sids]) for name in structure_names]
        vector = np.mean([vectors[pages[sid]["unit_id"]] for sid in sids], axis=0)
        first = next(iter(dedup.values()))
        rows.append({"href": href, "host": first["hostname"], "label": int(first["citation_category"] == "top"),
                     "structure": structural, "alignment": semantic, "path": [path], "vector": vector,
                     "payloads": {a["payload_hash"] for a in dedup.values()},
                     "texts": {content_identity(pages[sid], unit_lookup) for sid in sids}})
    parent = {r["host"]: r["host"] for r in rows}
    def find(host):
        while host != parent[host]:
            parent[host] = parent[parent[host]]
            host = parent[host]
        return host
    seen = {}
    for row in rows:
        for identity in row["payloads"] | row["texts"]:
            if identity in seen:
                a, b = find(row["host"]), find(seen[identity])
                parent[max(a, b)] = min(a, b)
            seen[identity] = row["host"]
    groups = np.asarray([find(r["host"]) for r in rows])
    if len(set(groups)) < 3 or len({r["label"] for r in rows}) < 2:
        raise ValueError("Need at least three independent hostname/content groups and both labels")
    y = np.asarray([r["label"] for r in rows])
    folds = list(GroupKFold(n_splits=min(5, len(set(groups)))).split(rows, y, groups))
    structural = np.asarray([r["structure"] for r in rows])
    path = np.asarray([r["path"] for r in rows])
    semantic = np.asarray([r["alignment"] for r in rows])
    raw = np.stack([r["vector"] for r in rows])
    ablations = {"structure_only": structural, "path_only": path, "alignment_only": semantic,
                 "structure_alignment_path": np.column_stack([structural, semantic, path]),
                 "combined_with_fold_pca": np.column_stack([structural, semantic, path])}
    results = {}
    for name, matrix in ablations.items():
        predictions = np.full(len(rows), np.nan)
        fit_details = []
        for train, test in folds:
            if len(set(y[train])) < 2:
                raise ValueError("A training fold has only one label; more data or different frozen splits required")
            train_x, test_x = matrix[train], matrix[test]
            if name == "combined_with_fold_pca":
                size = min(32, len(train) - 1, raw.shape[1])
                pca = PCA(n_components=size, svd_solver="full", whiten=False).fit(raw[train])
                train_x = np.column_stack([train_x, pca.transform(raw[train])])
                test_x = np.column_stack([test_x, pca.transform(raw[test])])
            pipeline = make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                                     StandardScaler(), LogisticRegression(C=1.0, max_iter=1000, random_state=42))
            counts = defaultdict(int)
            for i in train:
                counts[rows[i]["host"]] += 1
            weights = np.asarray([1 / counts[rows[i]["host"]] for i in train])
            weights *= len(weights) / weights.sum()
            pipeline.fit(train_x, y[train], logisticregression__sample_weight=weights)
            predictions[test] = pipeline.predict_proba(test_x)[:, 1]
            fit_details.append({"training_urls": [rows[i]["href"] for i in train], "heldout_urls": [rows[i]["href"] for i in test]})
        hosts = sorted({r["host"] for r in rows})
        rankings = []
        for host in hosts:
            top = [predictions[i] for i, r in enumerate(rows) if r["host"] == host and r["label"] == 1]
            bottom = [predictions[i] for i, r in enumerate(rows) if r["host"] == host and r["label"] == 0]
            if top and bottom:
                rankings.append(float(np.mean([1 if a > b else .5 if a == b else 0 for a in top for b in bottom])))
        # Bootstrap independent host/content groups, not individual rows.
        rng, boot = np.random.default_rng(42), []
        independent = sorted(set(groups))
        for _ in range(200):
            selected = rng.choice(independent, len(independent), replace=True)
            indices = np.concatenate([np.flatnonzero(groups == g) for g in selected])
            if len(set(y[indices])) == 2:
                boot.append(roc_auc_score(y[indices], predictions[indices]))
        results[name] = {"roc_auc": float(roc_auc_score(y, predictions)), "pr_auc": float(average_precision_score(y, predictions)),
                         "roc_auc_group_bootstrap_95_interval": np.quantile(boot, [.025, .975]).tolist() if boot else None,
                         "within_host_pairwise_accuracy": float(np.mean(rankings)) if rankings else None,
                         "paired_hosts": len(rankings), "folds": fit_details}
    result = {"scope": "Exploratory relative-label prediction; not citation uplift", "model": model_name,
              "weighting": "One URL; equal-weight queries after snapshot averaging; inverse host-size training weights",
              "urls": len(rows), "hosts": len(parent), "independent_host_content_groups": len(set(groups)),
              "exclusions": excluded, "results": results,
              "limitations": "Query intent, page purpose, language and exposure remain confounders; no prospective citation experiment."}
    write_json(output, result)
    return {"urls": len(rows), "hosts": len(parent), "output": str(output)}
