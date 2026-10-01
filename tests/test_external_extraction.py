import json
from pathlib import Path
import socket
import subprocess

import pytest

from preprocessing.adapters.external import ReadabilityWorker, extract_trafilatura
from preprocessing.schema import Snapshot


NODE_DIR = Path(__file__).resolve().parents[1] / "preprocessing" / "node"
ARTICLE = """<!doctype html><html lang="en"><head><title>Offline extraction guide</title>
<meta name="author" content="A. Writer"></head><body>
<nav>Unrelated navigation</nav><main><article><h1>Offline extraction guide</h1>
<p>This article explains how to preserve source evidence in archived documents.
The main article contains useful facts, detailed instructions, and practical examples.
Readers can compare the listed values without contacting an external website.</p>
<p>Use the <a href="/guide">reference guide</a> to interpret the <strong>important values</strong>.
These measurements describe the original record and should survive conversion faithfully.</p>
<table><thead><tr><th>Plan</th><th>Price</th></tr></thead>
<tbody><tr><td>Basic</td><td>$17</td></tr><tr><td>Pro</td><td>$29</td></tr></tbody></table>
<pre><code>def preserve(value):
    return value + 17</code></pre>
<p>The procedure keeps the supplied content available for later inspection.
The conclusion confirms that these numbers belong to the archived source.</p>
</article></main></body></html>"""


def snapshot(payload=ARTICLE, format="html"):
    return Snapshot("snapshot", "hash", "https://example.test/article", "example.test", payload, format)


@pytest.fixture(params=["trafilatura", "readability"])
def extract(request):
    if request.param == "trafilatura":
        yield extract_trafilatura
    else:
        with ReadabilityWorker() as worker:
            yield worker.extract


def test_article_table_code_and_links_survive(extract):
    result = extract(snapshot())
    assert result.status == "ok", result.diagnostics
    assert "archived documents" in result.text
    assert "<table" in result.html
    assert "<th" in result.html
    assert "$17" in result.text and "$29" in result.text
    assert "preserve(value)" in result.text
    assert "<code" in result.html or "<pre" in result.html
    assert "<a " in result.html and "/guide" in result.html
    assert "<strong" in result.html or "<b>" in result.html
    assert result.blocks == []
    if result.method == "readability":
        assert "```" in result.markdown
        assert "    return value + 17" in result.markdown
        assert "| Plan | Price |" in result.markdown


@pytest.mark.parametrize("format", ["text", "markdown", "unknown"])
def test_non_html_is_unsupported(extract, format):
    result = extract(snapshot(format=format))
    assert result.status == "unsupported_format"
    assert not result.html and not result.text and not result.markdown


@pytest.mark.parametrize("payload", ["", "  ", "<html><body></body></html>",
    '<html><head><script type="application/ld+json">{"@type":"Article",'
    '"articleBody":"Metadata invented body should never become visible."}</script></head><body></body></html>'])
def test_no_output_and_jsonld_does_not_become_body(extract, payload):
    result = extract(snapshot(payload))
    assert result.status == "no_output", result.diagnostics
    assert not result.text and not result.html


def test_extraction_is_offline_and_scripts_are_inert(extract, monkeypatch, tmp_path):
    def deny_connection(*args, **kwargs):
        pytest.fail("Extraction attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", deny_connection)
    marker = tmp_path / "network-attempt"
    guard = tmp_path / "guard.cjs"
    guard.write_text(
        'const deny = () => { require("node:fs").writeFileSync('
        + json.dumps(str(marker)) + ', "attempt"); throw Error("network forbidden"); };\n'
        'for (const name of ["node:http", "node:https"]) {\n'
        '  const module = require(name); module.request = deny; module.get = deny;\n'
        '}\nrequire("node:net").Socket.prototype.connect = deny; global.fetch = deny;\n'
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={guard}")
    payload = ARTICLE.replace("</head>", """<link rel="stylesheet" href="https://example.test/style.css">
    <script src="https://example.test/script.js"></script></head>""").replace(
        "</article>", """<img src="https://example.test/image.png" onerror="document.body.textContent='EXECUTED_SCRIPT'">
        <iframe src="https://example.test/frame"></iframe>
        <script>document.body.textContent = 'EXECUTED_SCRIPT'; fetch('https://example.test/fetch');</script>
        </article>"""
    )
    result = extract(snapshot(payload))
    assert result.status == "ok", result.diagnostics
    assert "archived documents" in result.text
    assert "EXECUTED_SCRIPT" not in result.text
    assert not marker.exists()


def test_worker_reuses_process_and_closes():
    worker = ReadabilityWorker()
    assert worker.extract(snapshot()).status == "ok"
    process = worker._process
    assert worker.extract(snapshot()).status == "ok"
    assert worker._process is process
    worker.close()
    assert process.poll() is not None
    worker.close()


@pytest.mark.parametrize("program, status", [
    ('setInterval(() => {}, 1000);', "timeout"),
    ('process.stdin.once("data", () => process.stdout.write("not json\\n"));', "error"),
    ('process.stdin.once("data", () => process.exit(0));', "error"),
    ('process.stdin.once("data", () => process.stdout.write("{\\\"status\\\":\\\"ok\\\",\\\"text\\\":17}\\n"));', "error"),
])
def test_worker_failure_restarts(program, status, tmp_path):
    path = tmp_path / "bad-worker.cjs"
    path.write_text(program)
    with ReadabilityWorker(timeout_seconds=0.5, worker_path=path) as worker:
        assert worker.extract(snapshot()).status == status
        assert worker._process is None
        worker.worker_path = NODE_DIR / "worker.cjs"
        worker.timeout_seconds = 10
        assert worker.extract(snapshot()).status == "ok"


def test_worker_recovers_after_invalid_input_line():
    request = json.dumps({"html": ARTICLE, "url": "https://example.test/article"})
    process = subprocess.run(
        ["node", str(NODE_DIR / "worker.cjs")],
        input="not-json\n" + request + "\n", text=True, capture_output=True, timeout=10,
    )
    results = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 0, process.stderr
    assert [result["status"] for result in results] == ["error", "ok"]


def test_complex_table_stays_html_in_markdown():
    payload = ARTICLE.replace("<td>Basic</td>", '<td rowspan="2">Basic</td>')
    with ReadabilityWorker() as worker:
        result = worker.extract(snapshot(payload))
    assert result.status == "ok"
    assert '<td rowspan="2">Basic</td>' in result.markdown
    assert result.diagnostics["complex_tables_preserved_as_html"] == 1


def test_timeout_also_bounds_blocked_stdin(tmp_path):
    path = tmp_path / "not-reading.cjs"
    path.write_text("setInterval(() => {}, 1000);")
    with ReadabilityWorker(timeout_seconds=0.2, worker_path=path) as worker:
        assert worker.extract(snapshot(ARTICLE * 1000)).status == "timeout"
        assert worker._process is None


def test_partial_response_line(tmp_path):
    path = tmp_path / "chunked.cjs"
    path.write_text(
        'process.stdin.once("data", () => {\n'
        'process.stdout.write(\'{"status":"ok",\');\n'
        'setTimeout(() => process.stdout.write(\'"text":"retained"}\\n\'), 20);\n'
        '});\n'
    )
    with ReadabilityWorker(worker_path=path) as worker:
        result = worker.extract(snapshot())
    assert result.status == "ok" and result.text == "retained"


def test_deterministic_candidate_content(extract):
    assert extract(snapshot()).to_dict() == extract(snapshot()).to_dict()


def test_oversized_payload_is_explicit(extract, monkeypatch):
    monkeypatch.setattr("preprocessing.adapters.external.MAX_PAYLOAD_BYTES", 10)
    result = extract(snapshot())
    assert result.status == "error"
    assert result.diagnostics["reason"] == "payload_too_large"
