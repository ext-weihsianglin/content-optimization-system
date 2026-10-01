"""Offline extraction preserves source facts, relationships, and uncertainty."""

import socket

import pytest

from preprocessing.adapters.local import extract_baseline, extract_conservative, extract_markdown_text
from preprocessing.blocks import blocks_to_markdown, blocks_to_text, html_to_blocks
from preprocessing.quality import classify_payload, source_inventory
from preprocessing.schema import Snapshot


def snapshot(payload, format="html", href="https://example.test/docs/page"):
    return Snapshot("snapshot", "payload", href, "example.test", payload, format)


@pytest.mark.parametrize(("payload", "expected"), [
    ("<p>Hello</p>", "html"), ("# Heading\n\nBody", "markdown"),
    ("Plain Unicode café 中文", "text"), ("", "unknown"),
    ('{"error": "bad"}', "unknown"), ("# Heading\n<div>Mixed</div>", "unknown"),
    ("%PDF-1.7 binary", "unknown"), ("<person@example.test>", "text"),
    ("```html\n<p>Code example</p>\n```", "markdown"),
])
def test_classification(payload, expected):
    assert classify_payload(payload) == expected


def test_inventory_keeps_metadata_out_of_body():
    payload = '''<html lang="zh" dir="ltr"><head><title>Document title</title>
    <meta name="author" content="Writer"><link rel="canonical" href="../canonical">
    <script type="application/ld+json">{"@type":"Product","name":"Metadata only"}</script>
    <script type="application/ld+json">invalid</script></head><body>
    <h1>Visible title</h1><p hidden>Hidden source text</p><script>secret()</script></body></html>'''
    result = source_inventory(payload, "https://example.test/docs/page", "html")
    assert result["title"] == "Document title"
    assert result["language"] == "zh"
    assert result["headings"] == ["Visible title"]
    assert "Metadata only" not in result["body_text"]
    assert "secret" not in result["body_text"]
    assert "Document title" not in result["body_text"]
    assert result["jsonld"][0]["types"] == ["Product"]
    assert result["jsonld"][1]["parse_status"] == "error"
    assert result["canonical"]["resolved_target"] == "https://example.test/canonical"
    assert result["visibility"][0]["computed_visibility"] == "unknown"


def test_conservative_multiple_sections_and_useful_forms():
    payload = '''<nav>Menu</nav><article><header><h1>One</h1></header><p>First</p>
    <footer>Article attribution</footer></article><article><h2>Two</h2><p>Second</p></article>
    <aside>Technical caveat</aside><form><label>Price $42</label></form>
    <footer>Site footer</footer><script>evil()</script>'''
    result = extract_conservative(snapshot(payload))
    assert result.method == "conservative_dom"
    for text in ("One", "First", "Two", "Second", "Technical caveat", "Price $42", "Article attribution"):
        assert text in result.text
    for text in ("Menu", "Site footer", "evil()"):
        assert text not in result.text
    assert result.html and result.markdown and result.blocks


def test_nested_lists_no_duplicate_text_and_code_whitespace():
    blocks = html_to_blocks('<ul><li>Parent<ul><li>Child</li></ul>Tail</li></ul><pre>  x\n    y\n</pre>', "")
    text = blocks_to_text(blocks)
    for word in ("Parent", "Child", "Tail"):
        assert text.count(word) == 1
    lists = [block for block in blocks if block["type"] == "list"]
    assert lists[1]["parent_id"] is not None
    assert blocks[-1]["text"] == "  x\n    y\n"
    markdown = blocks_to_markdown(blocks)
    assert "  - Child" in markdown
    assert "  x\n    y\n" in markdown


def test_table_grid_headers_spans_caption_and_html_fallback():
    html = '''<table><caption>Prices</caption><thead><tr><th rowspan="2" id="plan">Plan</th>
    <th colspan="2" scope="colgroup">Cost</th></tr><tr><th>Monthly</th><th>Yearly</th></tr></thead>
    <tbody><tr><th scope="row">Pro</th><td headers="plan">$4</td><td>$40</td></tr></tbody></table>'''
    blocks = html_to_blocks(html, "")
    assert len(blocks) == 1
    table = blocks[0]["table"]
    assert table["caption"] == "Prices"
    assert table["columns"] == 3
    assert table["cells"][0]["rowspan"] == 2
    assert table["cells"][1]["colspan"] == 2
    assert table["cells"][2]["column"] == 1
    assert table["cells"][5]["headers"] == ["plan"]
    assert table["cells"][4]["scope"] == "row"
    assert 'rowspan="2"' in blocks_to_markdown(blocks)


def test_link_resolution_and_provenance_ambiguity():
    source = '<main><p><a href="../help">Help</a></p><p>Repeat</p><p>Repeat</p></main>'
    blocks = html_to_blocks('<p><a href="../help">Help</a></p><p>Repeat</p><p>Absent</p>', "https://example.test/docs/page", source)
    assert blocks[0]["links"][0]["target"] == "../help"
    assert blocks[0]["links"][0]["resolved_target"] == "https://example.test/help"
    assert blocks[0]["mapping_status"] == "exact"
    assert blocks[1]["mapping_status"] == "ambiguous"
    assert blocks[1]["source_locator"] is None
    assert blocks[2]["mapping_status"] == "unavailable"
    assert "https://example.test/help" in blocks_to_markdown(blocks)
    assert blocks_to_markdown(blocks).count("Help") == 1
    normalized = html_to_blocks("<p>Space here</p>", "", "<p>Space   here</p>")
    assert normalized[0]["mapping_status"] == "normalized_match"


def test_baseline_is_exact_frozen_output():
    from scripts.analyze_content import extract

    payload = "<article>One</article><article><h1>Second</h1><p>Longer body here.</p></article><aside>Aside</aside>"
    result = extract_baseline(snapshot(payload))
    assert result.text == extract(payload)["extracted_text"]
    assert result.blocks == []
    assert result.html == result.markdown == ""
    assert extract_baseline(snapshot("# Plain", "markdown")).text == extract("# Plain")["extracted_text"]


def test_markdown_structures_pdf_url_and_plain_text_ranges():
    payload = "# Café\n\n- Parent\n  - Child\n\n[Help](../help)\n\n```py\n  value = 42\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    result = extract_markdown_text(snapshot(payload, "markdown", "https://example.test/docs/file.pdf"))
    assert {"heading", "list", "list_item", "code", "table"} <= {block["type"] for block in result.blocks}
    assert result.blocks[0]["source_locator"] == {"line_range": [0, 1]}
    assert result.text.count("Parent") == 1
    assert "https://example.test/help" in result.markdown
    assert "  value = 42\n" in result.text
    plain = "  Keep spaces\r\n\n第二行\n"
    result = extract_markdown_text(snapshot(plain, "text"))
    assert result.text == plain
    for block in result.blocks:
        start, end = block["source_locator"]["text_range"]
        assert plain[start:end] == block["text"]


def test_format_routing_flags_determinism_and_no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network call")

    monkeypatch.setattr(socket, "socket", forbidden)
    assert extract_conservative(snapshot("Text", "text")).status == "unsupported_format"
    assert extract_markdown_text(snapshot("<p>HTML</p>")).status == "unsupported_format"
    html = '<html><body><script src="https://example.test/app.js">run()</script><p>Enable JavaScript</p>'
    result = source_inventory(html, "https://example.test", "html")
    assert {"possible_script_shell", "possible_truncation", "possible_error_response"} <= set(result["quality_flags"])
    candidate = snapshot('<p><a href="/path">Text</a></p>')
    assert extract_conservative(candidate).to_dict() == extract_conservative(candidate).to_dict()
