"""Self-contained, escaped offline semantic explorer with source drill-down."""

import json
from pathlib import Path

from .storage import atomic_bytes, load_run, read_rows


def build_report(run, output):
    run = Path(run)
    manifest = load_run(run)
    unit_lookup = {u["unit_id"]: u for u in read_rows(run / "units.parquet")}
    associations = read_rows(run / "associations.parquet")
    from collections import defaultdict
    by_snapshot, by_query = defaultdict(list), defaultdict(list)
    for association in associations:
        by_snapshot[association["snapshot_id"]].append(association)
        by_query[association["query_unit_id"]].append(association)
    maps = []
    for identity, projection in manifest.get("projections", {}).items():
        folder = run / projection["path"]
        if not (folder / "umap.parquet").exists():
            continue
        model_name = next((name for name, model in manifest["models"].items() if model["config_id"] == projection["model_config_id"]), None)
        model_info = manifest["models"].get(model_name, {})
        vector_path = f"vectors/{model_info.get('config_id')}/vectors.npy"
        if projection["vector_hash"] != manifest["artifacts"].get(vector_path):
            raise ValueError("Projection is stale after embedding changes; rebuild it")
        align_info = manifest.get("alignment", {}).get(model_name)
        alignments = read_rows(run / align_info["path"]) if align_info else []
        aligned_snapshot, aligned_query = defaultdict(list), defaultdict(list)
        for association in alignments:
            aligned_snapshot[association["snapshot_id"]].append(association)
            aligned_query[association["query_unit_id"]].append(association)
        if align_info and align_info["vector_hash"] != projection["vector_hash"]:
            raise ValueError("Alignment is stale; rerun align")
        points = []
        for coordinate in read_rows(folder / "umap.parquet"):
            unit = unit_lookup[coordinate["unit_id"]]
            related = by_snapshot[unit["snapshot_id"]] if unit["snapshot_id"] else by_query[unit["unit_id"]]
            matched = aligned_snapshot[unit["snapshot_id"]] if unit["snapshot_id"] else aligned_query[unit["unit_id"]]
            supporting = list(dict.fromkeys(uid for a in matched for uid in a["best_section_unit_ids"]))[:5]
            input_text = unit["text"]
            if unit["status"] == "derived":
                member_ids = json.loads(unit["diagnostics_json"])["members"]
                input_text = "\n\n".join(unit_lookup[uid]["text"] for uid in member_ids)
            points.append({**coordinate, "view": unit["view"], "text": input_text[:4000],
                           "excerpt": len(input_text) > 4000, "subview": unit["subview"],
                           "status": unit["status"], "block_ids": unit["block_ids"],
                           "associations": related,
                           "alignment": [{k: a[k] for k in ("href", "prompt", "page_similarity", "path_similarity", "section_max")} for a in matched[:10]],
                           "support": [{"unit_id": uid, "text": unit_lookup[uid]["text"][:1200], "block_ids": unit_lookup[uid]["block_ids"]} for uid in supporting]})
        maps.append({"id": identity, "name": f"{model_name} · {projection['view']}", "metadata": projection, "points": points})
    if not maps:
        raise ValueError("No UMAP maps. Run project --exploratory --umap first")
    data = {"maps": maps, "coverage": {"records": manifest["records"], "units": manifest["units"], "statuses": manifest["statuses"], "models": manifest["models"]}}
    # Escape script delimiters even inside JSON strings; never embed source markup.
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = Path(__file__).with_name("report_template.html").read_text()
    atomic_bytes(output, template.replace("__EXPLORER_DATA__", serialized).encode())
    return {"maps": len(maps), "output": str(output)}
