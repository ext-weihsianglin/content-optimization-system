# Issue #10: inline semantics and source boundaries

Implemented `dom-blocks-v2` in the isolated `deck/markdownify-fix` worktree.
The six reported fidelity gaps were reproduced against revision
`3d4d35d3c32ac5b8c14983f99f92c2f633669417`. This is deterministic offline
source conversion, not an investigation of model hallucination.

## Implementation

Paragraphs/headings retain ordered `inline_nodes`: text, nested emphasis/strong,
links, inline code/kbd, deletion, hard breaks and media, including original tag
names/attributes. Inline images stay between their neighboring text, inside any
containing link/emphasis. Text nodes preserve parsed source text even though the
plain-text convenience view still normalizes prose whitespace. Serialization reads
these nodes; the cached `inline_markdown` field is retained for compatibility.

Code spans choose a delimiter longer than any source backtick run. Code containing
newlines, empty content or only whitespace uses an HTML fallback. Parser settings
preserve code/kbd whitespace before serialization. `<del>`, `<s>` and `<strike>`
serialize with GFM strikethrough; hard breaks use CommonMark backslash/newline.

Definition lists have a parent block and ordered term/description containers;
multiple terms/descriptions and nested content remain within the same chunk group.
They serialize as retained HTML because CommonMark has no native definition-list
syntax. Thematic separators become explicit `thematic_break` blocks. Table HTML,
cell spans and header roles stay authoritative, with cell inline nodes added.

Inline source references require an exact element match, either unique directly or
located through a unique exact enclosing subtree. They never inherit semantic
provenance from text-only matches. Text references use a parsed DOM path plus a
zero-based index into the parent's `contents`. Ambiguous/unavailable mappings stay
explicit. Native Markdown inline nodes do not claim generated HTML paths as source
locations; existing block line ranges remain available.

The schema version is recorded on newly parsed blocks and in conservative-parser
diagnostics. New chunk identities include block schema versions to distinguish
changed representations even when sequential block IDs match a previous export.
Legacy blocks remain renderable. Existing frozen exports are not migrated.

## Development serializer comparison

[HTML comparison](development/report.html) and [structured evidence](development/results.json)
contain the original HTML, unchanged baseline output, new structured output,
markdownify output, source-location checks, dependency versions and code hashes.
All **12 development fixtures** match the new expected output, including the six
issue examples, code backticks inside emphasis, multiline/whitespace-only code,
empty-alt media and a spanning table. These fixtures informed implementation;
they are not independent accuracy evidence.

[python-markdownify](https://github.com/matthewwithanm/python-markdownify) **1.2.3**
was tested with `heading_style=ATX` and `bs4_options=html.parser`, using its default
remaining options. It handles all six original examples and backticks/emphasized
code. Its definition-list syntax is a Markdown extension; image targets stay
relative. In the added edge fixtures it strips code edge whitespace, drops
whitespace-only inline code, and flattens the spanning table into a Markdown grid.
It does not return our structured provenance or region/metadata contract.

Decision: retain the focused structured serializer for this fix. Markdownify is a
viable future serializer with custom code/table converters and an adapter over
structured nodes; its unmodified output cannot be substituted for the extraction
model. It is installed only in the development dependency group and locked at
1.2.3. No serializer was selected using held-out outputs.

## Separate held-out diagnostics

[Diagnostic HTML](heldout/report.html) and [per-snapshot results](heldout/results.json)
cover all **37 held-out HTML snapshots**, of which **32** have eligible content
anchors. Exact payload-plus-URL hashes were checked against the frozen manifest.
Saved snapshots were read from the main repository's cache without modifying it.
Markdownify was not run on held-out snapshots.

| Measurement | Baseline at reported revision | Structured v2 |
| --- | ---: | ---: |
| Required selected anchors | 126/129 | 126/129 |
| Unwanted selected anchors | 46/50 | 46/50 |

Markdown changed on 34/37 snapshots; plain text changed on 16/37, principally due
to keeping inline image alt text adjacent to neighboring prose. Original source
text is available in the inline nodes. Among blocks and inline nodes there were
22,412 valid reported locators, zero invalid, 305 unavailable and 1,378 ambiguous
mappings; 171 valid block mappings were text-normalized matches rather than exact.
These counts include text nodes and table cell annotations, not just block roots.
Held-out nodes included 178 hard breaks and 790 inline images but no inline
code/deletion tags, so this set does not validate those semantic fixes in real pages.

Sparse AI-assisted anchors are not human gold, exhaustive precision/recall,
structural accuracy, citation uplift or verified frontier-model ingestion.
Unchanged anchor counts do not prove unchanged interpretation. Native held-out
inputs were excluded from this diagnostic; native compatibility is regression-tested.

## Validation and reproduction

Use `uv` (or the repository-local `.tools/uv` executable):

```sh
uv sync --locked --dev
npm ci --prefix preprocessing/node
uv run --offline python -m pytest -q
uv run --offline python -m preprocessing.inline_fidelity \
  --output analysis/inline-fidelity-v2-replay/development
uv run --offline python -m preprocessing.inline_fidelity \
  --output analysis/inline-fidelity-v2-replay/heldout \
  --heldout-cache /path/to/hash-verified/local/data/evaluation
```

The report command rejects an existing output directory. Conversion runs with
Python network connections disabled. Reports record hashes of all frozen evaluation
JSON files and assert they were unchanged. No frozen result/reference, original
analysis or existing export was overwritten. The initial full suite failed only
because this new worktree lacked Node dependencies; `npm ci` resolved that setup.
Final validation: **141 tests passed, 12 subtests passed**.

Remaining limits: DOM locators are parsed-tree positions, not byte offsets or
rendered coordinates. Raw payloads remain authoritative for exact source bytes.
Deletion needs a GFM-capable renderer; definition/table/code fallbacks need a
consumer that retains HTML. Unknown inline tags retain their names/attributes and
children but may flatten in the Markdown convenience view. This is not a general
lossless HTML serializer. Conservative region exclusions and quality flags are
unchanged. Corpus exports, cached features and scorer models were not regenerated;
a versioned migration and consumer review remain rollout gates. No concrete blocker
remains for this scoped fix.
