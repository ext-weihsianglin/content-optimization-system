# Default markdownify extraction and full-corpus re-extraction

The active extraction pipeline now uses **python-markdownify 1.2.3** as a pinned
runtime dependency. The handwritten Markdown converter has been removed from the
active path. Markdownify owns traversal and standard heading/emphasis/deletion/list/
quote rendering; custom converters preserve source code whitespace, hard breaks,
media targets, table spans and definition relationships where ordinary Markdown
conversion is lossy. Source structure/provenance extraction remains independent.

`conservative_dom` remains the method name for the existing retention/region policy;
its Markdown backend is now `markdownify-structured-v1`. This names the replacement
explicitly without changing the established source-region exclusions. Native
Markdown/text keeps native parsing, uses the same convenience-view serializer and
retains original text/range references. New blocks declare `dom-blocks-v3`, including
plain text, so chunk IDs cannot alias the prior serialization. Candidate diagnostics
and downstream `representation` record the actual serializer/dependency versions.

Tables and definitions use retained HTML fallbacks. Code spans choose delimiters
longer than source backtick runs; multiline/empty/whitespace-only code uses HTML to
preserve source text. Terminal hard breaks use `<br>` because CommonMark does not
render a terminal backslash/newline as a break. Inline media retains placement,
empty alt text, enclosing links/emphasis and source attributes. Exact subtree
matching and DOM position indexing are cached once to avoid repeated work on large
snapshots. Ambiguous/unavailable provenance remains explicit; no text-only semantic
mapping or replacement extractor is introduced.

## Development evidence

[Release comparison](development-release/report.html) and
[structured JSON](development-release/results.json) compare the prior structured
serializer at `caf590d1c3b78fa0d66899e799307635e84d23b2` with the actual default
markdownify pipeline. **12/12 development fixtures** match expected output, including
all six issue #10 examples, backticks in emphasized code, multiline/whitespace-only
code, empty-alt media and a spanning table. Tests spy on the markdownify library to
prove that default extraction invokes it. Additional regressions cover native
formats, versioned chunks, original locators, ordered starts outside CommonMark's
range, cached-document corruption, duplicate row references, multi-file export and
resuming interrupted finalization.

The earlier `analysis/inline-fidelity-v2/` reports are preserved as historical
comparison evidence. Preliminary reports remain archived separately under
`data/processed/markdownify-report-pilots/`; use the `*-release` paths for the
final implementation.

## Separate held-out diagnostics

[Release held-out report](heldout-release/report.html) and
[per-snapshot JSON](heldout-release/results.json) cover the same frozen **37 held-out
HTML snapshots**, **32** content-evaluable. This is a reused diagnostic set, not a
new independent test. The library/adapters were fixed using development fixtures;
held-out outputs were not used to select or tune conversion behavior.

| Selected AI-assisted anchors | Prior structured serializer | Markdownify default |
| --- | ---: | ---: |
| Required | 126/129 | 126/129 |
| Unwanted | 46/50 | 46/50 |

**22,382 reported source locators were valid; none was invalid.** Among mappings,
307 were unavailable and 1,379 ambiguous; 170 block mappings were normalized rather
than exact. These counts include inline text nodes and table annotations. This
subset contains no inline code/deletion tags, so it does not validate those fixes
on real pages. Sparse AI-assisted anchors are not human gold, exhaustive semantic
precision/recall, citation uplift or verified frontier-model ingestion.

## Corpus export and integrity

The full-corpus results and independent verification are reported in
`corpus/results.json` and `corpus/report.html`. The versioned local export is
`/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/markdownify-corpus-v1-complete/`.
This worktree's ignored `data/` symlink points to the shared project data directory,
so the original relative paths still resolve. Raw data,
full documents and caches stay outside Git; the committed corpus report contains
only aggregate evidence and explicitly bounded, escaped previews.

Release run: **9,700 rows / 9,551 distinct snapshots**, with
**zero extraction errors/timeouts**. The 149 additional row references share already-parsed
snapshots rather than being dropped. Coverage statuses: **9,167 selected**, **334
retained for review**, **47 source-insufficient**, **3 unsupported-format**. All
9,700 original payload/URL/query/label/host/row references were independently
verified against the original Parquet data.

The export contains **3,309,747 ordered blocks**, **278,479 chunks**, and **2,448
oversized chunks** retained without truncation. **8,973,098 declared HTML locators
were valid; none was invalid.** Every document file/content checksum and all six
JSONL/Parquet artifact hashes passed independent verification. Pipeline wall time:
**1191.539 seconds** with four workers (including export indexing).
This is an operational measurement on this machine, not a serializer speed benchmark.
Source formats: 9,484 HTML, 58 Markdown, 6 text and 3 unknown snapshots; 9,443 HTML
and 58 native snapshots have selected content. Raw-only outcomes retain their source
references, metadata and explicit status/reasons.

Each exact payload-plus-URL snapshot has a gzip document containing metadata,
quality flags, ordered blocks, full Markdown/text and complete chunks. Every original
Parquet row has a separate index reference, including rows that share a snapshot.
The original payload remains authoritative in the hash-verified source Parquet row;
no live webpage, remote API or model is used. Queries/labels are retained in the row
index and are never supplied to content extraction.

Artifacts:

- `documents/*.json.gz`: full source-derived documents and chunks, with content checksums.
- `records.jsonl/.parquet`: original row metadata and exact snapshot/source references.
- `documents.jsonl/.parquet`: document paths, statuses, sizes and file hashes.
- `chunks.jsonl/.parquet`: full ordered chunk partition, without truncation.
- `manifest.json`: source/code/dependency/configuration fingerprints and completion counts.

The reader processes one file at a time with bounded in-flight jobs. Every HTML
snapshot checks original-source locators; every selected block occurs exactly once
in its ordered chunk partition. Final report verification rereads raw rows and
checks payload-plus-URL identities, queries, labels, hosts, document file/content
hashes, indexes and chunk coverage. Explicit failures keep source references and
never substitute another extractor. An existing completed export is rejected;
`--resume` permits only an unfinished run with identical source/code/dependencies/
configuration. Resume keeps cached document bytes unchanged, including diagnostics.

## Reproduction and validation

```sh
uv sync --locked --dev
npm ci --prefix preprocessing/node
uv run --offline python -m pytest -q
uv run --offline python -m preprocessing.corpus \
  --input-dir /path/to/local/data/raw \
  --output data/processed/markdownify-corpus-v1-replay --workers 4
uv run --offline python -m preprocessing.markdownify_report --mode development \
  --output analysis/markdownify-corpus-v1-replay/development
uv run --offline python -m preprocessing.markdownify_report --mode heldout \
  --heldout-cache /path/to/local/data/evaluation \
  --output analysis/markdownify-corpus-v1-replay/heldout
uv run --offline python -m preprocessing.markdownify_report --mode corpus \
  --corpus-export data/processed/markdownify-corpus-v1-replay \
  --output analysis/markdownify-corpus-v1-replay/corpus
```

Final regression suite: **154 tests passed, 12 subtests passed**. The 50-row
operational pilot had no extraction errors. A global-sort reader initially exceeded
its memory cap before extraction and was replaced by per-file reads. An early full
attempt exposed three large-page timeouts; exact-match caching and DOM indexes
reduced those pages to approximately 1–5 seconds with valid declared locators.
Native-format version labels were finalized before the complete release run. All
superseded attempts use separate ignored output directories; no frozen result,
reference, original analysis, prior export or other worktree was overwritten.

Remaining limits: this is source extraction coverage and integrity, not human
semantic validation. GFM deletion and HTML fallbacks require capable consumers.
Unknown inline tag attributes remain structured but may flatten in the convenience
view. DOM locators are parsed-tree positions, not byte offsets or rendered geometry;
raw payloads remain authoritative. Conservative region exclusions are unchanged.
Existing corpus feature caches and trained models were not regenerated or retuned;
consumer migration and any requested model re-evaluation remain separate work.
