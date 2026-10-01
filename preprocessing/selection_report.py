"""Persist diagnostic selection proposals separately from extraction results."""

import argparse
import json
from pathlib import Path

import duckdb

from preprocessing.runner import evaluation_inputs, write_parquet
from preprocessing.select import select_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="data/processed/eval-v2")
    args = parser.parse_args()
    directory = Path(args.run)
    connection = duckdb.connect()
    inventories = {row[0]: json.loads(row[1]) for row in connection.execute("SELECT snapshot_id,inventory_json FROM read_parquet(?)", [str(directory / "source_features.parquet")]).fetchall()}
    candidates = {}
    with (directory / "results.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            candidates.setdefault(row["snapshot_id"], []).append(row)
    rows = []
    for snapshot, entry in evaluation_inputs(Path("evaluation/extraction/manifest.json")):
        if snapshot.snapshot_id in candidates:
            rows.append({"snapshot_id": snapshot.snapshot_id, **select_candidate(snapshot, candidates[snapshot.snapshot_id], inventories[snapshot.snapshot_id])})
    write_parquet(connection, rows, directory / "selection.parquet")
    (directory / "selection.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(connection.sql(f"SELECT status,method,count(*) AS snapshots FROM read_parquet('{directory}/selection.parquet') GROUP BY status,method").fetchall())


if __name__ == "__main__":
    main()
