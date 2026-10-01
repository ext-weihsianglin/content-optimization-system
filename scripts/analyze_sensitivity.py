"""Combine independent audits and describe matched-query feature differences."""

from collections import defaultdict
import json
from pathlib import Path
import statistics
from urllib.parse import urldefrag

import duckdb

from analyze_content import FEATURES, coverage, summarize
from analyze_quality import normalize


ROOT = Path(__file__).resolve().parents[1]


def records(connection, path):
    cursor = connection.execute("SELECT * FROM read_parquet(?)", [str(path)])
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def key(row):
    return (row.get("hostname", row.get("host", "")).strip().lower(), urldefrag(row["href"].strip())[0])


def compact_summary(rows):
    result = summarize(rows, minimum_words=100)
    for feature in result["features"].values():
        feature["within_host"].pop("host_effects", None)
    return result


def matched_summary(rows):
    groups = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if row["citation_category"] not in {"top", "bottom"} or row["word_count"] < 100:
            continue
        for prompt in {normalize(prompt) for prompt in row["prompts"]} - {""}:
            groups[(row["hostname"], prompt)][row["citation_category"]][row["href"]] = row
    matched = {group: labels for group, labels in groups.items() if labels["top"] and labels["bottom"]}
    results = {}
    for feature in FEATURES:
        host_differences = defaultdict(list)
        for (host, prompt), labels in matched.items():
            values = {}
            for label in ("top", "bottom"):
                values[label] = []
                for row in labels[label].values():
                    if feature == "query_title_coverage":
                        value = coverage([prompt], row["title"])
                    elif feature == "query_body_coverage":
                        value = coverage([prompt], row["extracted_text"])
                    else:
                        value = row[feature]
                    if value is not None:
                        values[label].append(value)
            if values["top"] and values["bottom"]:
                host_differences[host].append(statistics.mean(values["top"]) - statistics.mean(values["bottom"]))
        differences = [statistics.mean(values) for values in host_differences.values()]
        results[feature] = {
            "hosts": len(differences),
            "median_host_difference": statistics.median(differences) if differences else None,
            "positive_hosts": sum(value > 1e-12 for value in differences),
            "negative_hosts": sum(value < -1e-12 for value in differences),
            "tied_hosts": sum(abs(value) <= 1e-12 for value in differences),
        }
    return {
        "host_query_groups": len(matched),
        "hosts": len({host for host, prompt in matched}),
        "unique_pages": len({(host, row["href"]) for (host, prompt), labels in matched.items() for pages in labels.values() for row in pages.values()}),
        "features": results,
    }


def main():
    connection = duckdb.connect()
    pages = records(connection, ROOT / "analysis/content_features.parquet")
    quality = records(connection, ROOT / "analysis/quality_flags.parquet")
    excluded = set()
    known = set()
    editorial = set()
    for row in quality:
        page_key = key(row)
        known.add(page_key)
        flags = row.get("flags", row)
        if flags["clear_failure_union"] or flags["sparse_body_candidate"] or not flags["html_markup"]:
            excluded.add(page_key)
        if "editorial" in row["path_hints"]:
            editorial.add(page_key)
    assert all(key(row) in known for row in pages), "Quality join omitted pages"
    clean = [row for row in pages if key(row) not in excluded]
    report = {
        "method": {
            "quality_filter": "Exclude a URL if any source row is a heuristic failure, has <=30 body tokens, or has no recognized HTML. Additional >=100 extracted-word threshold in all comparisons. Conflicting labels are excluded by the comparison functions.",
            "join": "Lowercase stripped hostname and stripped URL without fragment; same normalization as content analysis. All pages must match the quality audit.",
            "editorial_filter": "URL path heuristic from quality audit, not verified page purpose.",
            "matching": "Same hostname and normalized nonblank prompt; unique pages per label within query. Average top-minus-bottom differences within each query, then average query differences within host; report equal-host descriptive summaries. Query coverage is recomputed for the matched prompt.",
            "limitations": "Sensitivity analyses selected after exploration, not held-out validation. Matching does not control exposure, time or semantic intent. Conservative URL exclusions can discard a good snapshot if another snapshot failed. No causal conclusions or citation uplift estimates.",
        },
        "quality_excluded_unique_pages": sum(key(row) in excluded for row in pages),
        "clean_html": compact_summary(clean),
        "clean_editorial_paths": compact_summary([row for row in clean if key(row) in editorial]),
        "clean_semantic_content_container": compact_summary([row for row in clean if row["focus_source"] != "body_fallback"]),
        "matched_query_all": matched_summary(pages),
        "matched_query_clean": matched_summary(clean),
    }
    destination = ROOT / "analysis/sensitivity_analysis.json"
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(destination)
    print(json.dumps({"quality_excluded_unique_pages": report["quality_excluded_unique_pages"], "matched_query_clean": {name: value for name, value in report["matched_query_clean"].items() if name != "features"}}, indent=2))


if __name__ == "__main__":
    main()
