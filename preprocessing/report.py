"""Self-contained offline comparison report: supplied content is always escaped."""

import base64
import hashlib
from html import escape
import json

from preprocessing.evaluate import LIMITATIONS, METHODS


_SCRIPT = """function filterSamples() {
    const filters = [...document.querySelectorAll('select')];
    document.querySelectorAll('[data-sample]').forEach(sample => {
      sample.hidden = filters.some(filter => filter.value &&
        sample.dataset[filter.id] !== filter.value);
    });
}
document.querySelectorAll('select').forEach(select => {
  select.addEventListener('change', filterSamples);
});
document.querySelectorAll('a[href^="#sample-"]').forEach(link => {
  link.addEventListener('click', () => {
    const sample = document.getElementById(link.getAttribute('href').slice(1));
    if (sample) sample.open = true;
  });
});
filterSamples();"""


def _escape(value):
    return escape(str(value), quote=True)


def _json(value):
    return _escape(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _preview(value, byte_limit):
    rendered = _escape(value) if isinstance(value, str) else _json(value)
    if len(rendered.encode("utf-8")) <= byte_limit:
        return rendered
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    lower, upper = 0, min(len(raw), byte_limit)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if len(_escape(raw[:middle]).encode("utf-8")) <= byte_limit:
            lower = middle
        else:
            upper = middle - 1
    return (_escape(raw[:lower]) + '\n[TRUNCATED PREVIEW: '
            + str(len(raw) - lower) + ' characters omitted. Full data remains in original input artifacts; '
            'candidate outputs remain in local results.jsonl.]')


def _text_preview_limit(candidates):
    sizes = [len(_escape(candidate.get("text", "")).encode("utf-8")) for candidate in candidates.values()]
    lower, upper = 0, 40_000
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if sum(min(size, middle) for size in sizes) <= 4_000_000:
            lower = middle
        else:
            upper = middle - 1
    return lower


def _heldout_interpretation(metrics):
    groups = [group for group in metrics["groups"] if group["split"] == "heldout"
              and group["subset"] == "html" and group["stratum"] is None
              and group["method"] != "markdown_text"]
    if not groups:
        return ""
    descriptions = [
        f'{group["method"]}: {_percent(group["retention"]["micro"])} required-anchor retention '
        f'({group["retention"]["numerator"]}/{group["retention"]["denominator"]}), '
        f'{group["leakage"]["numerator"]}/{group["leakage"]["denominator"]} unwanted anchors leaked'
        for group in groups
    ]
    return '<p><strong>Heldout HTML interpretation:</strong> ' + _escape('; '.join(descriptions)) + (
        '. Assess retention alongside leakage and support coverage: retaining more anchors can also '
        'retain more boilerplate. These selected-anchor proxies do not establish a usability winner.</p>')


def _native_interpretation(metrics):
    group = next((group for group in metrics["groups"] if group["split"] == "heldout"
                  and group["subset"] == "native_non_html" and group["stratum"] is None
                  and group["method"] == "markdown_text"), None)
    if group is None:
        return ""
    return '<p>' + _escape(
        f'Heldout native adapter: {group["retention"]["numerator"]}/{group["retention"]["denominator"]} '
        f'required anchors retained and {group["leakage"]["numerator"]}/{group["leakage"]["denominator"]} '
        f'unwanted anchors leaked across {group["supported_documents"]} supported non-HTML cases. '
        'Interpret this small subset separately; complete anchor retention does not imply clean extraction '
        'or general non-HTML accuracy.'
    ) + '</p>'


def _number(value):
    return "N/A" if value is None else f"{value:.4f}"


def _percent(value):
    return "N/A" if value is None else f"{value:.1%}"


def _anchor_summary(metric):
    return (f'{_percent(metric["micro"])} ({metric["numerator"]}/{metric["denominator"]} anchors); '
            f'macro {_percent(metric["macro"])} ({metric["eligible_documents"]} docs)')


def _primary_table(groups):
    return _table([
        "Split", "Method", "Evaluable sources", "Support coverage", "Retention", "Unwanted leakage",
        "Output failures", "Latency median / p95 ms (n)",
    ], [[
        group["split"], group["method"], f'{group["content_evaluable_documents"]}/{group["documents"]}',
        f'{_percent(group["support_coverage"])} ({group["supported_documents"]}/{group["documents"]})',
        _anchor_summary(group["retention"]), _anchor_summary(group["leakage"]),
        f'{_percent(group["output_failure_rate"])} ({group["output_failures"]}/{group["supported_documents"]})',
        f'{_number(group["latency_ms"]["median"])} / {_number(group["latency_ms"]["p95"])} ({group["latency_ms"]["count"]})',
    ] for group in groups])


def _table(headers, rows):
    return "<div class='scroll'><table><thead><tr>" + "".join(
        f"<th>{_escape(header)}</th>" for header in headers
    ) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
    ) + "</tbody></table></div>"


def _fixture_section(fixture_metrics):
    if fixture_metrics is None:
        return ""
    rows = []
    for group in fixture_metrics["groups"]:
        scores = []
        for numerator_key, denominator_key in (("required_hits", "required_total"),
                                               ("unwanted_hits", "unwanted_total"),
                                               ("structural_passed", "structural_total")):
            numerator, denominator = group[numerator_key], group[denominator_key]
            scores.append(f'{_percent(numerator / denominator if denominator else None)} ({numerator}/{denominator})')
        rows.append([group["subset"], group["method"], group["supported_cases"], *scores])
    return (
        '<section><h2>Synthetic structural engineering checks</h2>'
        '<p><strong>NOT heldout real-page accuracy.</strong> These synthetic fixtures '
        'check engineered examples separately from the source-only annotated benchmark. '
        'They do not certify human acceptance gates. N/A means no eligible denominator.</p>'
        + _table(["Subset", "Method", "Supported cases", "Required hits / total",
                  "Unwanted hits / total", "Structural passed / total"], rows)
        + '</section>'
    )


def render_report(metrics, manifest, annotations, results, fixture_metrics=None):
    """Return HTML with local sample links and filters; no file/URL is read.

    Pass the same input records used by evaluate. Source URLs are provenance text,
    not active links. Full payloads are not present in the declared input contract.
    Optional fixture metrics are displayed separately and never change scoring.
    """
    results = list(results)
    candidates = {(row["snapshot_id"], row["method"]): row for row in results}
    text_limit = _text_preview_limit(candidates)
    sources = {row["snapshot_id"]: row for row in manifest["snapshots"]}
    documents = {row["snapshot_id"]: row for row in annotations["documents"]}
    script_hash = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
    policy = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"script-src 'sha256-{script_hash}'; connect-src 'none'; img-src 'none'; "
        "object-src 'none'; base-uri 'none'; form-action 'none'"
    )
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{_escape(policy)}">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Source-only selected-anchor benchmark</title>',
        '<style>body{font:16px system-ui;margin:2rem;max-width:1500px;color:#172431}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f7;padding:1rem}'
        'table{border-collapse:collapse;font-size:14px}th,td{padding:.5rem;border:1px solid #ccd4da;text-align:left}'
        '.scroll{overflow:auto}.notice{border-left:5px solid #ad5500;padding:1rem;background:#fff3de}'
        'select{margin:.5rem;padding:.4rem}article{border-top:2px solid #ccd4da;margin-top:2rem}'
        '[hidden]{display:none!important}summary{cursor:pointer;padding:.5rem}a{color:#174fac}</style></head><body>',
        '<h1>Source-only selected-anchor benchmark</h1>',
        f'<p class="notice"><strong>{_escape(LIMITATIONS)}</strong></p>',
        '<p>Human gates: NOT ASSESSED. Thresholds: not certified. '
        'Scores measure selected literal anchors only; low leakage can also reflect failed extraction.</p>',
        '<h2>HTML comparisons — dev / heldout</h2>',
        _primary_table([group for group in metrics["groups"] if group["subset"] == "html"
                        and group["stratum"] is None and group["method"] != "markdown_text"]),
        _heldout_interpretation(metrics),
        '<h2>Native non-HTML — dev / heldout</h2>',
        _primary_table([group for group in metrics["groups"] if group["subset"] == "native_non_html"
                        and group["stratum"] is None and group["method"] in ("baseline", "markdown_text")]),
        _native_interpretation(metrics),
        '<p>Micro percentages use anchor denominators; macro percentages average eligible documents. '
        'N/A means no eligible denominator. The HTML and native subsets have separate populations.</p>',
        _fixture_section(fixture_metrics),
        '<details><summary>Declared provenance, dates, and raw metadata</summary>',
        '<p>Dates below are supplied declarations, not inferred snapshot capture dates. '
        'Full saved source payloads are not included in these inputs. '
        'Source URLs and file paths are displayed for traceability and never fetched.</p>',
        '<pre>' + _preview({
            "semantics_version": metrics.get("semantics_version"),
            "declared_freeze_date": metrics.get("declared_freeze_date"),
            "manifest": {key: value for key, value in manifest.items() if key != "snapshots"},
            "annotation_metadata": {key: value for key, value in annotations.items() if key != "documents"},
            "sample": metrics.get("sample"), "warnings": metrics.get("warnings", []),
        }, 12_000) + '</pre></details>',
        '<details><summary>Full comparisons by split, subset, and stratum</summary>',
        '<p>Retention and leakage show numerator/denominator, micro, then macro. '
        'N/A means no eligible denominator. Failures count as zero retention on supported evaluable documents. '
        'Unsupported formats are excluded, with support coverage shown. '
        'Latency uses recorded supported attempts, including failures; p95 uses linear interpolation. '
        'Paired deltas use shared eligible documents only; positive means more anchor retention.</p>',
    ]
    rows = []
    for group in metrics["groups"]:
        retention, leakage = group["retention"], group["leakage"]
        paired, latency = group["paired_baseline_retention"], group["latency_ms"]
        rows.append([
            group["split"], group["subset"], group["stratum"] if group["stratum"] is not None else "All strata", group["method"],
            group["documents"], group["content_evaluable_documents"],
            f'{group["supported_documents"]}/{group["documents"]}',
            _anchor_summary(retention),
            _anchor_summary(leakage),
            f'{group["output_failures"]}/{group["supported_documents"]}; {_percent(group["output_failure_rate"])}',
            f'{latency["count"]}; {_number(latency["median"])} / {_number(latency["p95"])}',
            f'{paired["documents"]} docs / {paired["anchor_denominator"]} anchors; {_number(paired["micro_delta"])} / {_number(paired["macro_delta"])}',
        ])
    parts.append(_table([
        "Split", "Subset", "Stratum", "Method", "Documents", "Evaluable sources", "Supported / total",
        "Retention: micro (hits/anchors); macro (docs)", "Leakage: micro (hits/anchors); macro (docs)",
        "Output failures; rate", "Latency n; median / p95 ms", "Paired baseline: denominator; micro / macro delta",
    ], rows))
    parts.extend([
        '</details>',
        '<details><summary>Aggregate metrics and source diagnostics (per-document metrics below)</summary><pre>',
        _json({key: value for key, value in metrics.items() if key not in {"per_document", "provenance"}}),
        '</pre><details><summary>Run provenance preview</summary><pre>',
        _preview(metrics.get("provenance"), 12_000), '</pre></details></details>',
        '<h2>Traceable samples</h2><p>Initially showing heldout / trafilatura. Choose All to compare other candidates. '
        'Open a sample to inspect its provenance and outputs. All source markup, '
        'candidate HTML, Markdown, and annotations are shown as inert escaped text. '
        'Bulky fields use bounded previews, explicitly marked when truncated. '
        'All annotation anchors and per-document scores are retained. Full candidate outputs remain in '
        'the local run results.jsonl; report truncation does not affect scoring.</p>',
    ])
    for field, values in (("method", METHODS), ("split", ("dev", "heldout")),
                          ("stratum", sorted({source["stratum"] for source in sources.values()}))):
        parts.append(f'<label>{_escape(field)} <select id="{field}"><option value="">All</option>')
        default = {"method": "trafilatura", "split": "heldout"}.get(field)
        parts.extend(f'<option value="{_escape(value)}"{" selected" if value == default else ""}>{_escape(value)}</option>' for value in values)
        parts.append('</select></label>')
    indexed_rows = list(enumerate(metrics["per_document"]))
    parts.append('<details><summary>Sample links</summary><ul>')
    for index, row in indexed_rows:
        attributes = ' '.join(f'data-{field}="{_escape(row[field])}"' for field in ("method", "split", "stratum"))
        hidden = ' hidden' if row["split"] != "heldout" or row["method"] != "trafilatura" else ''
        parts.append(f'<li data-sample {attributes}{hidden}><a href="#sample-{index}">{_escape(row["snapshot_id"])} — {_escape(row["method"])}</a></li>')
    parts.append('</ul></details>')
    for index, row in indexed_rows:
        snapshot_id, method = row["snapshot_id"], row["method"]
        attributes = ' '.join(f'data-{field}="{_escape(row[field])}"' for field in ("method", "split", "stratum"))
        hidden = ' hidden' if row["split"] != "heldout" or method != "trafilatura" else ''
        parts.append(f'<details id="sample-{index}" data-sample {attributes}{hidden}><summary>{_escape(snapshot_id)} — {_escape(method)} — {_escape(row["status"])}</summary>')
        parts.append('<details><summary>Source provenance</summary><pre>' + _json({
            key: sources[snapshot_id].get(key) for key in (
                "snapshot_id", "split", "stratum", "format", "hostname", "href", "payload_hash", "source_file", "source_row"
            )
        }) + '</pre><details><summary>Additional source metadata preview</summary><pre>'
            + _preview({key: value for key, value in sources[snapshot_id].items() if key not in {
                "snapshot_id", "split", "stratum", "format", "hostname", "href", "payload_hash", "source_file", "source_row"
            }}, 1_000) + '</pre></details></details>')
        parts.append('<h4>Source-only AI annotation</h4><pre>' + _json(documents.get(snapshot_id, {"missing_annotation": True})) + '</pre>')
        parts.append('<h4>Per-document scores and eligibility</h4><pre>' + _json(row) + '</pre>')
        candidate = candidates.get((snapshot_id, method))
        if candidate is None:
            parts.append('<p>No result record supplied.</p>')
        else:
            for field in ("text", "markdown", "html", "blocks", "metadata", "diagnostics", "status", "runtime_ms"):
                value = candidate.get(field)
                rendered = _preview(value, text_limit if field == "text" else 1_200)
                parts.append(f'<details><summary>{field}</summary><pre>{rendered}</pre></details>')
        parts.append('</details>')
    parts.extend([f'<script>{_SCRIPT}</script>', '</body></html>'])
    return "\n".join(parts)
