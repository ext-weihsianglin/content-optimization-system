"""Publish a small inspectable offline pilot report, without annotation claims."""

import argparse
from html import escape
import json
from pathlib import Path

from encoder_scorer.curate import sha256


def build(curation, packets, output, edits=None):
    if output.with_suffix(".json").exists() or output.with_suffix(".html").exists():
        raise FileExistsError("Use a new report path")
    manifest = json.loads(curation.read_text())
    packet_manifest = json.loads((packets / "manifest.json").read_text())
    prepared = [json.loads(line) for line in (packets / "packets.jsonl").open()]
    status = "Offline preparation complete; " + manifest["teacher_status"]
    summary = {"status": status,
               "teacher_model": manifest.get("teacher_model"), "model_calls": 0, "teacher_labels": 0,
               "human_reviewed_cases": 0, "test_documents_loaded": manifest["test_documents_loaded"],
               "curation_manifest_sha256": sha256(curation.read_bytes()),
               "source_records_sha256": manifest["source_records_sha256"],
               "source_manifest_sha256": manifest["source_manifest_sha256"],
               "host_splits_sha256": manifest["host_splits_sha256"],
               "selected_counts": manifest["selected_counts"], "candidate_counts": manifest["candidate_counts"],
               "smoke": packet_manifest, "review_queue_count": len(manifest["review_ids"]),
               "limitations": manifest["limitations"] + [
                   "Source-format coverage is limited to the observed selected counts; no claim of full-format coverage",
                   f"Character-limited views are not tokenizer-budgeted; {len(prepared) - packet_manifest['full_body_cases']} smoke views have omitted blocks",
                   "Heuristic curation intentionally oversamples rare strata and needs-review content",
                   "No teacher reliability, model training, LR comparison, or end-to-end dogfood completed"],
               "code_sha256": {str(p): sha256(p.read_bytes()) for p in sorted(Path("encoder_scorer").glob("*.py"))},
               "cases": [{k: c[k] for k in ("record_id", "snapshot_id", "split", "document_sha256", "strata", "smoke", "independent_review")}
                         for c in manifest["cases"]]}
    summary["source_path"] = manifest.get("source_path")
    summary["source_run_identity"] = manifest.get("source_run_identity")
    if edits is not None:
        summary["controlled_edits"] = json.loads(edits.read_text())
        if summary["controlled_edits"]["input_packets_sha256"] != packet_manifest["packets_sha256"]:
            raise ValueError("Edit pairs reference different smoke packets")
    tables = []
    for name, values in manifest["selected_counts"].items():
        rows = "".join(f"<tr><td>{escape(str(k))}</td><td>{v}</td></tr>" for k, v in values.items())
        tables.append(f"<section><h2>{escape(name)}</h2><table><tr><th>Stratum</th><th>Cases</th></tr>{rows}</table></section>")
    previews = []
    for item in prepared:
        coverage = item["packet"]["coverage"]
        excerpt = "\n".join(b["text"] for b in item["packet"]["blocks"] if b["text"])[:500]
        previews.append(f"<article><h3>{escape(item['packet']['query'])}</h3>"
                        f"<p>Title: {escape(item['title'] or '(missing)')}</p>"
                        f"<p>Body view: {len(coverage['included_block_ids'])}/{coverage['original_block_count']} blocks; "
                        f"{escape(coverage['scope'])}</p><pre>{escape(excerpt).replace(' ', '&#32;').replace(chr(9), '&#9;')}</pre>"
                        f"<small>Record: {escape(item['record_id'])}</small></article>")
    limitations = "".join(f"<li>{escape(s)}</li>" for s in summary["limitations"])
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teacher curation pilot — offline preparation</title><style>
body{font:16px/1.55 system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 24px;color:#203043;background:#fafbfd}
h1,h2,h3{line-height:1.25} .notice{padding:18px;border-left:5px solid #bf7c12;background:#fff4d9}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:24px}table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:6px;border-bottom:1px solid #dce2e8}article{padding:18px;margin:18px 0;background:white;border:1px solid #dce2e8;border-radius:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}small{overflow-wrap:anywhere}a{color:#146594}
</style><main><h1>Teacher curation pilot</h1><p class="notice">Offline preparation only. Teacher model awaits user choice.
Zero model calls, zero teacher labels, zero human-reviewed cases. No student performance claims.</p>
<p>Development curation uses distinct hosts; smoke packets use training hosts only. No test document was opened.</p>
<p>Source: frozen retention-first LR v2 cached documents. Query requirements are annotated before the page is shown;
body requests exclude URL provenance, browser title, labels, and LR scores. Brands may remain in source prose.
The title is supplied only in its separate consistency pass.</p>""" + f"<p>{len(manifest['cases'])} curated cases; {len(prepared)} smoke packets; {len(manifest['review_ids'])} cases queued for independent review.</p><div class='grid'>" + "".join(tables) + "</div><h2>Limits and remaining gates</h2><ul>" + limitations + "</ul><h2>Smoke queue previews</h2><p>These are source previews, not model judgments. Preview text is shortened; packet coverage is reported separately.</p>" + "".join(previews) + "</main></html>"
    if edits is not None:
        ed = summary["controlled_edits"]
        section = f"<h2>Controlled edits</h2><p>{ed['pairs']} blinded, unlabeled pairs across {ed['parent_cases']} training cases.</p><p>" + escape(", ".join(ed["edit_types"])) + "</p><p>Mutation intent is hidden from the comparison judge. These edits have no reviewed preference labels; original-page evidence tests fidelity only.</p>"
        document = document.replace("<h2>Smoke queue previews</h2>", section + "<h2>Smoke queue previews</h2>")
    if manifest.get("source_run_identity"):
        document = document.replace("Teacher model awaits user choice.", "GPT-5 approved; this package has not been annotated.")
        document = document.replace("frozen retention-first LR v2 cached documents", "verified saved markdownify corpus; inline Markdown preserved, code whitespace exact, tables structured")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    output.with_suffix(".html").write_text(document + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curation", type=Path, required=True)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--edits", type=Path)
    args = parser.parse_args()
    summary = build(args.curation, args.packets, args.output, args.edits)
    print(json.dumps({k: summary[k] for k in ("status", "model_calls", "review_queue_count", "test_documents_loaded")}, indent=2))


if __name__ == "__main__":
    main()
