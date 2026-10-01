"""Inspect completed Reader-LM outcomes without performing inference."""

from collections import Counter
from html import escape
import json
from pathlib import Path
import statistics

from preprocessing.evaluate import _score


def main():
    sources = {row["snapshot_id"]: row for row in json.loads(Path("evaluation/extraction/manifest.json").read_text())["snapshots"]}
    references = {row["snapshot_id"]: row for row in json.loads(Path("evaluation/extraction/annotations.json").read_text())["documents"]}
    with Path("data/processed/reader-lm-v1/results.jsonl").open() as stream:
        results = [json.loads(line) for line in stream]
    html = [row for row in results if sources[row["snapshot_id"]]["format"] == "html"]
    eligible = [row for row in html if references[row["snapshot_id"]]["evaluable"]]
    identities = {row["snapshot_id"] for row in eligible}
    with Path("data/processed/eval-v2/results.jsonl").open() as stream:
        originals = [json.loads(line) for line in stream]
    comparisons = []
    for method in ["reader_lm", "baseline", "trafilatura", "readability", "conservative_dom"]:
        candidates = eligible if method == "reader_lm" else [row for row in originals if row["snapshot_id"] in identities and row["method"] == method]
        scores = [_score(sources[row["snapshot_id"]], references[row["snapshot_id"]], row, method) for row in candidates]
        comparisons.append({"method": method, **{key: sum(row[key] for row in scores) for key in ["retention_numerator", "retention_denominator", "leakage_numerator", "leakage_denominator"]}})
    examples = []
    for row in eligible:
        paragraphs = [part.strip() for part in row["text"].split("\n\n") if len(part.strip()) > 30]
        counts = Counter(paragraphs)
        repeated = counts.most_common(1)
        examples.append({"snapshot_id": row["snapshot_id"], "hostname": sources[row["snapshot_id"]]["hostname"], "split": sources[row["snapshot_id"]]["split"], "diagnostics": row["diagnostics"], "most_repeated_long_paragraph": repeated[0] if repeated else None, "output_preview": row["text"][:1800], "annotations": references[row["snapshot_id"]]})
    review = {"decision": "Do not resume this configuration unchanged", "completed": len(results), "html_completed": len(html), "evaluable_completed": len(eligible), "split_counts": dict(Counter(sources[row["snapshot_id"]]["split"] for row in eligible)), "stratum_counts": dict(Counter(sources[row["snapshot_id"]]["stratum"] for row in eligible)), "input_truncated": sum(row["diagnostics"].get("input_truncated", False) for row in html), "output_capped": sum(row["diagnostics"].get("output_capped", False) for row in html), "evaluable_output_capped": sum(row["diagnostics"].get("output_capped", False) for row in eligible), "median_seconds_html": statistics.median(row["runtime_ms"] / 1000 for row in html), "comparisons": comparisons, "examples": examples, "limitations": "Matched completed subset only, not the full evaluation split. All ten evaluable pages are from the table stratum. Source-only AI anchors are not human gold. Repetition counts are exact long-paragraph diagnostics, not validated failure classifiers. This run cannot separate model limitations from decoding/backend and input/output-budget effects."}
    Path("analysis/reader-lm-review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n")
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'"><title>Reader-LM quality checkpoint</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px;line-height:1.5}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #ccc}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f5f5;padding:16px}details{margin:15px 0}</style><h1>Reader-LM: stop and inspect</h1><p>Benchmark and MLX server stopped. Do not resume the current configuration unchanged.</p>']
    parts.append('<p>' + escape(review["limitations"]) + '</p><h2>Same completed pages, all methods</h2><table><tr><th>Method</th><th>Required retention ↑</th><th>Unwanted leakage ↓</th></tr>')
    for row in comparisons:
        cells = [row["method"]]
        for metric in ["retention", "leakage"]:
            numerator, denominator = row[f"{metric}_numerator"], row[f"{metric}_denominator"]
            cells.append(f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)" if denominator else "N/A")
        parts.append('<tr>' + ''.join('<td>' + escape(cell) + '</td>' for cell in cells) + '</tr>')
    parts.append('</table><h2>Run diagnostics</h2><pre>' + escape(json.dumps({key: value for key, value in review.items() if key not in {"examples", "comparisons"}}, indent=2)) + '</pre><h2>Eyeball the completed content pages</h2>')
    for example in examples:
        parts.append('<details><summary>' + escape(example["hostname"]) + '</summary><pre>' + escape(json.dumps(example, ensure_ascii=False, indent=2)) + '</pre></details>')
    parts.append('</html>')
    Path("analysis/reader-lm-review.html").write_text('\n'.join(parts))
    print(json.dumps({key: value for key, value in review.items() if key != "examples"}, indent=2))


if __name__ == "__main__":
    main()
