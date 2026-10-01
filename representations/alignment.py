"""Query–view cosine features in the original model space."""

from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa

from .runner import load_vectors, run_lock
from .storage import file_hash, read_rows, write_json, write_rows


def align(run, model_name):
    run = Path(run)
    with run_lock(run):
        vectors, manifest = load_vectors(run, model_name)
        units = read_rows(run / "units.parquet")
        snapshots = defaultdict(list)
        for unit in units:
            if unit["snapshot_id"]:
                snapshots[unit["snapshot_id"]].append(unit)
        rows = []
        for association in read_rows(run / "associations.parquet"):
            query = vectors.get(association["query_unit_id"])
            row = {**association, "model_config_id": manifest["models"][model_name]["config_id"]}
            doc_units = snapshots[association["snapshot_id"]]
            reasons = {}
            for feature, view, prefix in (("title", "title", "document_title"), ("h1", "title", "h1"),
                                          ("outline", "outline", "outline"), ("page", "page", "page"), ("path", "path", "url_path")):
                candidates = [u for u in doc_units if u["view"] == view and u["subview"].startswith(prefix) and not u["subview"].endswith(":chunk")]
                scores = [float(query @ vectors[u["unit_id"]]) for u in candidates if query is not None and u["unit_id"] in vectors]
                row[feature + "_similarity"] = max(scores) if scores else None
                if not scores:
                    reasons[feature] = "query_unavailable" if query is None else "view_unavailable_or_not_embedded"
            sections = [u for u in doc_units if u["view"] == "section"]
            scored = sorted([(float(query @ vectors[u["unit_id"]]), u) for u in sections if query is not None and u["unit_id"] in vectors], key=lambda pair: (-pair[0], pair[1]["unit_id"]))
            scores = [score for score, _ in scored]
            row.update(section_count=len({u["section_id"] for u in sections}), section_chunk_count=len(sections),
                       scored_section_chunks=len(scored), section_max=max(scores) if scores else None,
                       section_top3_mean=float(np.mean(scores[:3])) if scores else None,
                       section_median=float(np.median(scores)) if scores else None,
                       section_q25=float(np.quantile(scores, .25)) if scores else None,
                       section_q75=float(np.quantile(scores, .75)) if scores else None,
                       best_section_unit_ids=[u["unit_id"] for _, u in scored[:3]],
                       best_section_block_ids=list(dict.fromkeys(b for _, u in scored[:3] for b in u["block_ids"])))
            import json
            row["missing_reasons_json"] = json.dumps(reasons, sort_keys=True)
            row["status"] = "available" if query is not None and scored else "unavailable"
            rows.append(row)
        from .contracts import ASSOCIATION_SCHEMA
        schema = pa.schema(list(ASSOCIATION_SCHEMA) + [pa.field("model_config_id", pa.string())]
                           + [pa.field(k + "_similarity", pa.float64()) for k in ("title", "h1", "outline", "page", "path")]
                           + [pa.field(k, pa.int64()) for k in ("section_count", "section_chunk_count", "scored_section_chunks")]
                           + [pa.field(k, pa.float64()) for k in ("section_max", "section_top3_mean", "section_median", "section_q25", "section_q75")]
                           + [pa.field(k, pa.list_(pa.string())) for k in ("best_section_unit_ids", "best_section_block_ids")]
                           + [pa.field(k, pa.string()) for k in ("missing_reasons_json", "status")])
        relative = f"alignment/{manifest['models'][model_name]['config_id']}.parquet"
        write_rows(run / relative, rows, schema)
        manifest["artifacts"][relative] = file_hash(run / relative)
        manifest.setdefault("alignment", {})[model_name] = {"path": relative, "records": len(rows),
                "vector_hash": manifest["artifacts"][f"vectors/{manifest['models'][model_name]['config_id']}/vectors.npy"]}
        write_json(run / "manifest.json", manifest)
        return {"records": len(rows), "available": sum(r["status"] == "available" for r in rows)}
