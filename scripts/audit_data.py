"""Audit raw citation data without extracting HTML features.

Run: .tools/uv run --no-project --python .venv/bin/python python scripts/audit_data.py
"""

import argparse
import json
import platform
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb


ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["prompt", "citation_category", "href", "hostname", "html_content"]


def audit(input_dir):
    files = sorted(input_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No Parquet files in {input_dir}")
    with TemporaryDirectory(prefix="citation-audit-") as temporary, duckdb.connect() as con:
        con.execute("SET memory_limit = '4GB'")
        con.execute("SET threads = 1")
        con.execute("SET preserve_insertion_order = false")
        con.execute("SET temp_directory = ?", [temporary])

        def records(sql, parameters=None):
            result = con.execute(sql, parameters or [])
            names = [column[0] for column in result.description]
            return [dict(zip(names, row)) for row in result.fetchall()]

        def one(sql):
            return records(sql)[0]

        metadata = []
        for path in files:
            schema = records("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)])
            if [(column["column_name"], column["column_type"]) for column in schema] != [
                (column, "VARCHAR") for column in COLUMNS
            ]:
                raise ValueError(f"Unexpected schema in {path}: {schema}")
            file_meta = records("SELECT * FROM parquet_file_metadata(?)", [str(path)])[0]
            metadata.append({
                "file": path.name,
                "size_bytes": path.stat().st_size,
                "metadata_rows": file_meta["num_rows"],
                "actual_rows": con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0],
                "row_groups": file_meta["num_row_groups"],
                "created_by": file_meta["created_by"],
                "schema": schema,
                "column_chunks": records(
                    "SELECT row_group_id, row_group_num_rows, path_in_schema, type, "
                    "compression, encodings, num_values, stats_null_count, "
                    "total_compressed_size, total_uncompressed_size "
                    "FROM parquet_metadata(?) ORDER BY row_group_id, column_id", [str(path)]
                ),
            })

        con.from_parquet([str(path) for path in files]).create_view("raw")
        column_stats = {}
        for column in COLUMNS:
            column_stats[column] = one(
                f'SELECT count(*) AS rows, count(*) FILTER (WHERE "{column}" IS NULL) AS null_rows, '
                f'count(*) FILTER (WHERE "{column}" = \'\') AS empty_rows, '
                f'count(*) FILTER (WHERE regexp_full_match("{column}", \'\\s*\')) AS blank_rows, '
                f'count(DISTINCT "{column}") AS distinct_nonnull FROM raw'
            )

        exact_duplicates = one(
            "SELECT count(*) AS duplicate_groups, coalesce(sum(n), 0) AS involved_rows, "
            "coalesce(sum(n - 1), 0) AS excess_rows FROM "
            "(SELECT count(*) AS n FROM raw GROUP BY prompt, citation_category, href, hostname, html_content "
            "HAVING count(*) > 1)"
        )
        con.execute(
            "CREATE TEMP TABLE data AS SELECT prompt, citation_category, href, hostname, "
            "length(html_content) AS html_chars, "
            "regexp_full_match(html_content, '\\s*') AS html_blank FROM raw"
        )
        for name, keys in [("urls", "href"), ("prompts", "prompt"), ("hosts", "hostname")]:
            con.execute(
                f"CREATE TEMP VIEW {name} AS SELECT {keys}, count(*) AS rows, "
                "count(DISTINCT prompt) AS prompts, count(DISTINCT href) AS urls, "
                "count(DISTINCT hostname) AS hosts, count(DISTINCT citation_category) AS labels, "
                "count(*) FILTER (WHERE citation_category = 'top') AS top_rows, "
                "count(*) FILTER (WHERE citation_category = 'bottom') AS bottom_rows "
                f"FROM data GROUP BY {keys}"
            )
        con.execute(
            "CREATE TEMP VIEW prompt_label AS SELECT prompt, citation_category, count(*) AS rows, "
            "count(DISTINCT href) AS urls FROM data GROUP BY 1, 2"
        )
        con.execute(
            "CREATE TEMP VIEW prompt_url AS SELECT prompt, href, count(*) AS rows, "
            "count(DISTINCT citation_category) AS labels FROM data GROUP BY 1, 2"
        )
        quantiles = "[0, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1]"
        html_stats = (
            "count(*) AS rows, count(*) FILTER (WHERE html_chars IS NULL) AS null_rows, "
            "count(*) FILTER (WHERE html_blank) AS blank_rows, "
            "count(*) FILTER (WHERE html_chars = 0) AS empty_rows, "
            "sum(html_chars) AS total_characters, avg(html_chars) AS mean_characters, "
            f"quantile_cont(html_chars, {quantiles}) AS character_quantiles"
        )
        return {
            "method": {
                "python_version": platform.python_version(), "duckdb_version": duckdb.__version__,
                "input_directory": str(input_dir),
                "identity": "Exact stored strings; no URL, prompt or hostname normalization.",
                "blank": "Non-null strings matching DuckDB RE2 \\s* (includes empty strings).",
                "cardinality": "Distinct non-null values; SQL GROUP BY retains null groups.",
                "html": "Character lengths only; quantile_cont excludes nulls and includes empty strings. No HTML parsing.",
                "quantile_probabilities": [0, .01, .05, .25, .5, .75, .95, .99, 1],
                "both_label_eligibility": "At least one top and one bottom row; does not imply a within-prompt matched pair.",
            },
            "files": metadata,
            "totals": {"rows": column_stats["prompt"]["rows"], "files": len(files),
                       "file_size_bytes": sum(item["size_bytes"] for item in metadata),
                       "metadata_rows": sum(item["metadata_rows"] for item in metadata)},
            "columns": column_stats,
            "labels": records("SELECT citation_category, count(*) AS rows, count(DISTINCT prompt) AS prompts, count(DISTINCT href) AS urls, count(DISTINCT hostname) AS hosts FROM data GROUP BY 1 ORDER BY 1"),
            "exact_duplicate_rows": exact_duplicates,
            "granularity": {
                "unique_prompt_url_pairs": one("SELECT count(*) AS count FROM prompt_url")["count"],
                "unique_prompt_url_label_triples": one("SELECT count(*) AS count FROM (SELECT DISTINCT prompt, href, citation_category FROM data)")["count"],
                "prompt_row_distribution": records("SELECT rows, count(*) AS prompts FROM prompts GROUP BY 1 ORDER BY 1"),
                "prompt_label_distribution": records("SELECT citation_category, rows, urls, count(*) AS groups FROM prompt_label GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"),
                "max_five_per_prompt_label": one("SELECT max(rows) AS max_rows, max(urls) AS max_urls, count(*) FILTER (WHERE rows > 5) AS groups_over_five_rows, count(*) FILTER (WHERE urls > 5) AS groups_over_five_urls FROM prompt_label"),
                "over_five_groups": records("SELECT * FROM prompt_label WHERE rows > 5 ORDER BY rows DESC, prompt, citation_category"),
                "prompt_label_coverage": records("SELECT labels, count(*) AS prompts FROM prompts GROUP BY 1 ORDER BY 1"),
                "nonblank_prompt_summary": one("SELECT count(*) AS prompts, count(*) FILTER (WHERE labels > 1) AS both_label_prompts FROM prompts WHERE NOT regexp_full_match(prompt, '\\s*')"),
                "max_five_per_nonblank_prompt_label": one("SELECT max(rows) AS max_rows, count(*) FILTER (WHERE rows > 5) AS groups_over_five_rows FROM prompt_label WHERE NOT regexp_full_match(prompt, '\\s*')"),
                "repeated_prompt_url_pairs": records("SELECT * FROM prompt_url WHERE rows > 1 ORDER BY rows DESC, prompt, href"),
            },
            "urls": {
                "summary": one("SELECT count(*) AS unique_urls, count(*) FILTER (WHERE rows > 1) AS repeated_urls, coalesce(sum(rows) FILTER (WHERE rows > 1), 0) AS rows_on_repeated_urls, count(*) FILTER (WHERE prompts > 1) AS multi_prompt_urls, count(*) FILTER (WHERE labels > 1) AS conflicting_label_urls, coalesce(sum(rows) FILTER (WHERE labels > 1), 0) AS rows_on_conflicting_label_urls, count(*) FILTER (WHERE hosts > 1) AS multiple_hostname_urls, max(rows) AS max_rows_per_url FROM urls"),
                "multiplicity_distribution": records("SELECT rows, prompts, labels, count(*) AS urls FROM urls GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"),
                "repeated_urls": records("SELECT * FROM urls WHERE rows > 1 ORDER BY rows DESC, href"),
                "within_prompt_conflicts": records("SELECT * FROM prompt_url WHERE labels > 1 ORDER BY prompt, href"),
            },
            "hosts": {
                "distribution": records("SELECT * FROM hosts ORDER BY rows DESC, hostname"),
                "label_count_distribution": records("SELECT top_rows, bottom_rows, count(*) AS hosts FROM hosts GROUP BY 1, 2 ORDER BY 1, 2"),
                "max_five_per_host_label": one("SELECT max(greatest(top_rows, bottom_rows)) AS max_rows, count(*) FILTER (WHERE top_rows > 5 OR bottom_rows > 5) AS hosts_over_five_per_label FROM hosts"),
                "eligibility": one("SELECT count(*) AS hosts, count(*) FILTER (WHERE top_rows > 0 AND bottom_rows > 0) AS both_label_hosts, coalesce(sum(rows) FILTER (WHERE top_rows > 0 AND bottom_rows > 0), 0) AS rows_on_both_label_hosts, count(*) FILTER (WHERE top_rows > 0 AND bottom_rows = 0) AS top_only_hosts, count(*) FILTER (WHERE bottom_rows > 0 AND top_rows = 0) AS bottom_only_hosts FROM hosts"),
                "within_prompt_both_labels": records("SELECT hostname, count(*) AS prompts_with_both_labels FROM (SELECT hostname, prompt FROM data GROUP BY 1, 2 HAVING count(DISTINCT citation_category) FILTER (WHERE citation_category IN ('top', 'bottom')) = 2) GROUP BY 1 ORDER BY 2 DESC, 1"),
                "within_nonblank_prompt_both_labels": records("SELECT hostname, count(*) AS prompts_with_both_labels FROM (SELECT hostname, prompt FROM data WHERE NOT regexp_full_match(prompt, '\\s*') GROUP BY 1, 2 HAVING count(DISTINCT citation_category) FILTER (WHERE citation_category IN ('top', 'bottom')) = 2) GROUP BY 1 ORDER BY 2 DESC, 1"),
            },
            "html_lengths": {"overall": one(f"SELECT {html_stats} FROM data"),
                             "by_label": records(f"SELECT citation_category, {html_stats} FROM data GROUP BY 1 ORDER BY 1")},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "analysis/audit_data.json")
    args = parser.parse_args()
    result = audit(args.input_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "totals": result["totals"]}, indent=2))


if __name__ == "__main__":
    main()
