"""Render actual teacher judgments and trace links for human smoke review."""

import argparse
from collections import Counter, defaultdict
from html import escape
import json
import os
from pathlib import Path

from encoder_scorer.curate import sha256


def build(run_dir, packets_dir, output):
    if output.with_suffix(".html").exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Use a new report path")
    run_manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    labels = json.loads((run_dir / "labels.json").read_text()) if (run_dir / "labels.json").exists() else []
    packets = {p["record_id"]: p for p in (json.loads(line) for line in (packets_dir / "packets.jsonl").open())}
    grouped, traces = defaultdict(list), []
    for path in sorted((run_dir / "traces").glob("*.json")):
        trace = json.loads(path.read_text())
        traces.append((path, trace))
    for label in labels:
        grouped[label["record_id"]].append(label)
    differences = []
    for record_id, versions in grouped.items():
        if len(versions) < 2:
            continue
        a, b = versions[:2]
        for stage in ("body", "title"):
            if a["stages"].get(stage) is None or b["stages"].get(stage) is None:
                continue
            for component, first in a["stages"][stage]["components"].items():
                second = b["stages"][stage]["components"][component]
                differences.append({"record_id": record_id, "component": component,
                    "models": [a["model"], b["model"]], "scores": [first["score"], second["score"]],
                    "applicability": [first["applicability"], second["applicability"]],
                    "absolute_difference": abs(first["score"] - second["score"]) if first["score"] is not None and second["score"] is not None else None})
    report = {"version": "teacher-smoke-review-v1", "summary": summary, "config": run_manifest["config"],
              "run_manifest_sha256": sha256((run_dir / "manifest.json").read_bytes()),
              "labels_sha256": sha256((run_dir / "labels.json").read_bytes()) if labels else None,
              "component_comparisons": differences,
              "comparison_limit": "Independent teachers derive their own requirements; score differences can reflect rubric interpretation as well as body judgments",
              "teacher_annotations": labels, "human_reviewed_cases": 0}
    output.parent.mkdir(parents=True, exist_ok=True)

    def link(path, label):
        return f'<a href="{escape(os.path.relpath(path, output.parent), quote=True)}">{escape(label)}</a>'

    def render_evidence(items, item):
        source = {b["block_id"]: b["text"] for b in item["packet"]["blocks"]}
        parts = []
        for evidence in items:
            full = source.get(evidence["block_id"], "(not in body view)")
            # Full referenced passages aid review; large blocks stay local in trace files.
            preview = full[:3000]
            parts.append(f"<blockquote><strong>{escape(evidence['block_id'])}</strong>: {escape(evidence['quote'])}"
                         f"<details><summary>Source block context</summary><pre>{escape(preview)}</pre>"
                         + ("<p>Context shortened; full block is in the local request trace.</p>" if len(full) > 3000 else "") + "</details></blockquote>")
        return "".join(parts)

    articles = []
    for record_id in run_manifest["config"]["record_ids"]:
        item = packets[record_id]
        views = []
        for annotation in grouped[record_id]:
            content = [f"<h3>{escape(annotation['model'])}</h3>"]
            req = annotation["stages"].get("requirements")
            if req:
                content.append(f"<p>Task: {escape(req['task_type'])}; ambiguity: {escape(req['ambiguity'] or 'none recorded')}</p><ol>")
                for r in req["requirements"]:
                    content.append(f"<li><strong>{escape(r['requirement_id'])}</strong> {escape(r['text'])} <small>({escape(r['origin'])}, {escape(r['importance'])})</small></li>")
                content.append("</ol>")
            else:
                content.append("<p class='warning'>Requirements failed validation; body assessment unavailable.</p>")
            for stage in ("body", "title", "support"):
                value = annotation["stages"].get(stage)
                if value is None:
                    content.append(f"<p class='warning'>{escape(stage)}: no valid label after bounded repair.</p>")
                    continue
                for name, rating in value["components"].items():
                    number = str(rating["score"]) + "/3" if rating["score"] is not None else rating["applicability"]
                    content.append(f"<h4>{escape(name)}: {escape(number)}</h4><p>{escape(rating['reason'])}</p>" + render_evidence(rating["evidence"], item))
                if stage == "support":
                    content.append("<p><small>Support is a deterministic missing-evidence abstention, not a model judgment.</small></p>")
                if value.get("requirement_assessments"):
                    content.append("<details><summary>Requirement judgments and evidence</summary>")
                    for r in value["requirement_assessments"]:
                        content.append(f"<p><strong>{escape(r['requirement_id'])}: {escape(r['state'])}</strong> — {escape(r['reason'])}</p>" + render_evidence(r["evidence"], item))
                    content.append("</details>")
                content.append(f"<details><summary>Full {escape(stage)} label</summary><pre>{escape(json.dumps(value,ensure_ascii=False,indent=2))}</pre></details>")
            local = [(p, t) for p, t in traces if t["record_id"] == record_id and t["model"] == annotation["model"]]
            content.append("<p>Local call traces: " + " · ".join(link(p, t["stage"] + " attempt " + str(t["attempt"]) + " (" + t["validation_status"] + ")") for p, t in local) + "</p>")
            views.append("<section>" + "".join(content) + "</section>")
        coverage = item["packet"]["coverage"]
        title = item["title"] or "(missing)"
        if not views:
            views.append("<p>No completed annotation record. Inspect raw traces and run summary for failures.</p>")
        articles.append(f"<article><h2>{escape(item['packet']['query'])}</h2><p>Title: {escape(title)}</p>"
                        f"<p>Body coverage: {len(coverage['included_block_ids'])}/{coverage['original_block_count']} blocks; {escape(coverage['scope'])}.</p>"
                        + "<div class='models'>" + "".join(views) + "</div>"
                        + f"<p><small>Record {escape(record_id)}</small></p></article>")
    numeric = [d for d in differences if d["absolute_difference"] is not None]
    agreement = f"<p>{len(numeric)} numeric component comparisons; {sum(d['absolute_difference'] == 0 for d in numeric)} exact matches; {sum(d['absolute_difference'] <= 1 for d in numeric)} within one point.</p>" if differences else "<p>No cross-model comparison was executed in this run.</p>"
    html = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teacher smoke annotation review</title><style>
body{font:16px/1.55 system-ui,sans-serif;max-width:1300px;margin:30px auto;padding:0 24px;background:#f7f9fb;color:#253348}
h1,h2,h3,h4{line-height:1.25}.warning{background:#fff0cf;padding:14px;border-left:4px solid #b87c18}
article{border:1px solid #d8e0e8;padding:22px;margin:22px 0;background:white;border-radius:8px}
.models{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:28px}section{min-width:0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#f3f5f7;padding:12px}blockquote{margin:12px 0;padding:12px;border-left:3px solid #709db3;background:#f2f7fa}
small,a{overflow-wrap:anywhere}a{color:#146594}details{margin:12px 0}summary{cursor:pointer;font-weight:600}
</style><main><h1>Teacher smoke annotation review</h1><p class="warning">AI-assisted development judgments awaiting human review.
No student training, reliability certification, or citation-uplift claim. Scores are ordinal 0–3, not citation probabilities.</p>"""
    html += f"<p>Primary: {escape(str(summary['primary_model']))}; comparison: {escape(str(summary['review_model']))}. "
    html += f"{summary['generation_calls']} generation calls; {summary['valid_calls']} valid and {summary['invalid_calls']} invalid attempts. "
    html += f"Estimated standard API cost: ${summary['estimated_cost_usd']:.4f}; this is not a billing invoice.</p>"
    html += "<p>Local trace links include the exact requests, visible outputs, usage, timing, and validation errors. They work in the local report; full source-bearing traces are not committed to Git.</p>"
    html += "<h2>Cross-model checks</h2>" + agreement + "<p>Each teacher derives its own query requirements. Agreement is not evidence of correctness or independent human review.</p>"
    html += "".join(articles) + "</main></html>"
    output.with_suffix(".html").write_text(html + "\n")
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.run, args.packets, args.output)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
