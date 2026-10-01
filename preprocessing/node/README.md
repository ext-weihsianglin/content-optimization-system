# Offline candidate worker

Install pinned Node dependencies separately from extraction:

```sh
npm ci --prefix preprocessing/node --ignore-scripts --no-audit --no-fund
.tools/uv run python -m pytest -q tests/test_external_extraction.py
```

Tested with Node 26 and npm 11. Direct versions and transitive resolutions are
recorded in `package.json` and `package-lock.json`. No dependency installation
occurs inside either adapter.

`worker.cjs` accepts one JSON object `{html, url}` per stdin line and emits one
JSON result per stdout line. Malformed requests receive an error and do not
terminate the worker. Embedded newlines are JSON escaped. The Python adapter
starts one lazy process, serializes requests, and uses nonblocking pipes with a
30-second deadline covering both writing and reading. Timeout, EOF, and invalid
responses terminate the child; the next request starts a fresh process. Call
`close()` or use `ReadabilityWorker` as a context manager. An enclosing Python
timeout interrupt also closes the child.

## Frozen extraction configuration: offline-v1

Readability uses `disableJSONLD: true` and `keepClasses: true`. jsdom's default
script execution and resource loading remain disabled: neither `runScripts`
nor `resources` is enabled. The URL only supplies the DOM base. A private virtual
console prevents page/parser messages from contaminating stdout. Windows are
closed after each request. Turndown uses ATX headings, fenced code, dash bullets,
and GFM. Tables with span attributes stay HTML in Markdown and are counted in
diagnostics. Extracted HTML remains available for authoritative block parsing.

Trafilatura preserves tables, links, formatting, and images; excludes comments;
disables deduplication; and uses balanced extraction. It receives the preserved
HTML directly. Metadata is separate from body HTML/text. Its date extractor
receives the parsed tree, uses non-extensive original-date extraction and an
explicit maximum date of 9999-12-31 to avoid a wall-clock-dependent cutoff.
Trafilatura's HTML conversion is used without metadata insertion; downstream
`html_to_blocks` owns final serialization. Its execution deadline is owned by
the Python caller/orchestrator.

Both candidates reject non-HTML input as `unsupported_format`, distinguish empty
extraction as `no_output`, and reject payloads exceeding 10 MB without truncation.
Exceptions become `error`; Node deadline expiry becomes `timeout`. No candidate
synthesizes missing body content from metadata. Extraction libraries are heuristic
candidates, not guarantees of complete structural retention. Keep these settings
fixed during held-out evaluation.
