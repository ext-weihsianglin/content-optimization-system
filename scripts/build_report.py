"""Build a standalone report with deterministic samples from the source parquet."""

import hashlib
from html import escape
import json
from pathlib import Path

import duckdb

from analyze_content import coverage, extract


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / "analysis" / name).read_text())


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th scope="col">{escape(str(value))}</th>' for value in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def main():
    audit = load("audit_data.json")
    quality = load("quality_analysis.json")
    sensitivity = load("sensitivity_analysis.json")
    con = duckdb.connect()
    con.execute("CREATE VIEW raw AS SELECT * FROM read_parquet('data/raw/*.parquet', filename=true, file_row_number=true)")
    cursor = con.execute("SELECT filename, file_row_number, prompt, citation_category, href, hostname FROM raw ORDER BY filename, file_row_number")
    columns = [column[0] for column in cursor.description]
    metadata = [dict(zip(columns, row)) for row in cursor.fetchall()]
    chosen = {}

    def add(row, group, reason):
        identifier = (row["filename"], row["file_row_number"])
        chosen.setdefault(identifier, {**row, "group": group, "reason": reason})

    for host, reason in [
        ("bryteflow.com", "Same query: migration-specific page versus broader fundamentals."),
        ("accuknox.com", "Same query: a substantive page versus a scraped page-not-found response."),
        ("bouqs.com", "Same URL and query appear under both labels; static text is sparse."),
    ]:
        pair = next(pair for pair in quality["examples"]["same_normalized_prompt_pairs"] if pair["host"] == host)
        for label in ("top", "bottom"):
            example = pair[label]
            row = next(row for row in metadata if row["href"] == example["href"] and row["prompt"] == example["prompt"] and row["citation_category"] == label)
            add(row, "Matched examples", reason)
    for label in ("top", "bottom"):
        add(next(row for row in metadata if not row["prompt"].strip() and row["citation_category"] == label), "Quality & language", "Blank prompt: cannot evaluate query alignment.")
        add(next(row for row in metadata if row["hostname"] == "a1.art" and row["citation_category"] == label and ("Quelle" in row["prompt"] or any(ord(character) >= 0x900 for character in row["prompt"]))), "Quality & language", "Multilingual prompt: English stopwords and literal token overlap have limitations.")
        example = next(example for example in quality["examples"]["quality_flags"]["markdown_like_without_html"] if example["category"] == label)
        add(next(row for row in metadata if row["href"] == example["href"] and row["prompt"] == example["prompt"] and row["citation_category"] == label), "Quality & language", "Markdown-like payload stored in html_content; HTML structure metrics are unsuitable.")
    for label in ("top", "bottom"):
        candidates = [row for row in metadata if row["citation_category"] == label and (row["filename"], row["file_row_number"]) not in chosen]
        candidates.sort(key=lambda row: hashlib.sha256(f"42:{row['filename']}:{row['file_row_number']}".encode()).hexdigest())
        for row in candidates[:4]:
            add(row, "Random sample", "Deterministic hash sample, seed 42; four rows per label, excluding curated rows.")
    con.execute("CREATE TEMP TABLE selected(filename VARCHAR, file_row_number BIGINT)")
    con.executemany("INSERT INTO selected VALUES (?, ?)", list(chosen))
    raw = con.execute("SELECT raw.filename, raw.file_row_number, raw.html_content FROM raw JOIN selected USING(filename, file_row_number)").fetchall()
    payloads = {(filename, number): content for filename, number, content in raw}
    cards = []
    manifest = []
    for index, (identifier, row) in enumerate(chosen.items(), 1):
        payload = payloads[identifier]
        features = extract(payload)
        title_coverage = coverage([row["prompt"]], features["title"])
        title_coverage_text = f"{title_coverage:.0%}" if title_coverage is not None else "n/a"
        source = f"{Path(row['filename']).name} · row {row['file_row_number'] + 1:,}"
        searchable = ' '.join([row["prompt"], row["hostname"], row["href"], features["title"], features["extracted_text"][:3000]]).casefold()
        text = features["extracted_text"][:3000] or "[No text extracted from this snapshot]"
        text += "\n[Excerpt truncated at 3,000 characters]" if len(features["extracted_text"]) > 3000 else ""
        raw_excerpt = payload[:12000] + ("\n[Raw excerpt truncated at 12,000 characters]" if len(payload) > 12000 else "")
        headings = ''.join(f'<li>{escape(heading)}</li>' for heading in features["headings"][:10]) or '<li>No headings extracted</li>'
        cards.append(f'''<article class="sample" data-category="{row['citation_category']}" data-group="{escape(row['group'], quote=True)}" data-search="{escape(searchable, quote=True)}">
<div class="sample-top"><span class="label {row['citation_category']}">{row['citation_category']}</span><span class="sample-number">Sample {index:02d} · {escape(row['group'])}</span></div>
<h3 dir="auto">{escape(row['prompt']) if row['prompt'] else '<em>[Blank prompt]</em>'}</h3>
<p class="page-title" dir="auto">{escape(features['title']) or '[No HTML title]'}</p>
<a class="url" href="{escape(row['href'], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(row['href'])}</a>
<p class="reason">{escape(row['reason'])}</p>
<dl class="mini-metrics"><div><dt>Extracted words</dt><dd>{features['word_count']:,}</dd></div><div><dt>Headings</dt><dd>{features['heading_count']}</dd></div><div><dt>Title overlap</dt><dd>{title_coverage_text}</dd></div><div><dt>Payload chars</dt><dd>{len(payload):,}</dd></div></dl>
<details><summary>Read extracted text</summary><div class="excerpt" dir="auto">{escape(text)}</div><h4>First 10 extracted headings</h4><ul>{headings}</ul><p class="small">Container: {escape(features['focus_source'])}. Extraction is heuristic and can retain boilerplate.</p></details>
<details><summary>Inspect original row &amp; raw payload</summary><dl class="row-fields"><dt>prompt</dt><dd dir="auto">{escape(row['prompt']) or '[empty string]'}</dd><dt>citation_category</dt><dd>{row['citation_category']}</dd><dt>hostname</dt><dd>{escape(row['hostname'])}</dd><dt>href</dt><dd>{escape(row['href'])}</dd><dt>html_content</dt><dd>{len(payload):,} characters; excerpt below</dd></dl><pre>{escape(raw_excerpt)}</pre></details>
<p class="source">{escape(source)} · row numbering starts at 1</p></article>''')
        manifest.append({**row, "source_row_1based": row["file_row_number"] + 1, "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(), "extracted_words": features["word_count"], "title": features["title"]})
    clean = sensitivity["clean_html"]["features"]
    feature_names = {"query_title_coverage": "Title query-token coverage", "query_body_coverage": "Body query-token coverage", "heading_count": "Heading count", "word_count": "Extracted words"}
    broad_rows = []
    matched_rows = []
    bars = []
    for feature, label in feature_names.items():
        stats = clean[feature]["within_host"]
        difference = stats["median_mean_difference"]
        effect = f"+{difference * 100:.2f} pp" if "coverage" in feature else f"+{difference:,.1f}"
        broad_rows.append([label, effect, f"{stats['positive_hosts']} / {stats['negative_hosts']} / {stats['tied_hosts']}"])
        matched = sensitivity["matched_query_clean"]["features"][feature]
        counts = [matched["positive_hosts"], matched["negative_hosts"], matched["tied_hosts"]]
        matched_rows.append([label, ' / '.join(map(str, counts)), "0" if matched["median_host_difference"] == 0 else f"+{matched['median_host_difference']:g}"])
        segments = ''.join(f'<span class="{kind}" style="width:{count / 27 * 100:.4f}%">{count}</span>' for kind, count in zip(["positive", "negative", "tied"], counts) if count)
        bars.append(f'<div class="bar-row"><span>{label}</span><div class="bar" role="img" aria-label="{label}: {counts[0]} favor top, {counts[1]} favor bottom, {counts[2]} ties">{segments}</div></div>')
    column_rows = [[name, "VARCHAR", values["distinct_nonnull"], values["null_rows"], values["blank_rows"]] for name, values in audit["columns"].items()]
    file_rows = [[entry["file"], f"{entry['actual_rows']:,}", f"{entry['size_bytes'] / 1e6:.1f} MB", "SNAPPY"] for entry in audit["files"]]
    replacements = {
        "@@SAMPLES@@": '\n'.join(cards),
        "@@BROAD_TABLE@@": table(["Feature", "Median host difference", "Top higher / lower / tied"], broad_rows),
        "@@MATCHED_TABLE@@": table(["Feature", "Top higher / lower / tied", "Median host difference"], matched_rows),
        "@@SCHEMA@@": table(["Column", "Type", "Distinct values¹", "Nulls", "Blanks"], column_rows),
        "@@FILES@@": table(["File", "Rows", "Disk size", "Compression"], file_rows),
        "@@BARS@@": '\n'.join(bars),
        "@@SAMPLE_COUNT@@": str(len(cards)),
    }
    html = (ROOT / "scripts/report_template.html").read_text()
    for marker, content in replacements.items():
        html = html.replace(marker, content)
    assert "@@" not in html
    destination = ROOT / "analysis/brief-report.html"
    destination.write_text(html)
    (ROOT / "analysis/report_samples.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Built {destination} with {len(cards)} sampled source rows ({len(html.encode()):,} bytes)")


if __name__ == "__main__":
    main()
