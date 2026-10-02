"""Frozen baseline, conservative DOM, and Markdown/plain-text candidates."""

from bs4 import BeautifulSoup, Comment
from markdown_it import MarkdownIt

from preprocessing.blocks import BLOCK_SCHEMA_VERSION, PRESERVE_WHITESPACE_TAGS, blocks_to_markdown, blocks_to_text, dom_path, html_to_blocks
from preprocessing.schema import CandidateResult
from preprocessing.markdownify_serializer import MARKDOWNIFY_VERSION, SERIALIZER_VERSION


def extract_baseline(snapshot):
    from scripts.analyze_content import extract

    result = extract(snapshot.payload)
    return CandidateResult(method="baseline", text=result["extracted_text"], metadata={key: value for key, value in result.items() if key != "extracted_text"}, diagnostics={"structure": "unavailable: frozen baseline returns flattened text only"})


def extract_conservative(snapshot):
    if snapshot.format != "html":
        return CandidateResult(method="conservative_dom", status="unsupported_format")
    soup = BeautifulSoup(snapshot.payload, "html.parser", preserve_whitespace_tags=PRESERVE_WHITESPACE_TAGS)
    removed = 0
    for node in list(soup.find_all(True)):
        if node.parent is None:
            continue
        role = node.get("role", "").lower()
        remove = node.name in {"script", "style", "template", "noscript", "nav"} or role == "navigation"
        remove = remove or (node.name == "footer" and not node.find_parent(["article", "main", "section"]))
        if remove:
            node.decompose()
            removed += 1
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    html = str(soup.body or soup)
    blocks = html_to_blocks(html, snapshot.href, source_html=snapshot.payload)
    return CandidateResult(method="conservative_dom", html=html, text=blocks_to_text(blocks), markdown=blocks_to_markdown(blocks), blocks=blocks, diagnostics={"block_schema_version": BLOCK_SCHEMA_VERSION, "serializer": SERIALIZER_VERSION, "markdownify_version": MARKDOWNIFY_VERSION, "removed_nodes": removed, "order": "DOM order; computed visibility unknown"})


def extract_markdown_text(snapshot):
    if snapshot.format not in {"markdown", "text"}:
        return CandidateResult(method="markdown_text", status="unsupported_format")
    if snapshot.format == "text":
        blocks = []
        offset = 0
        for chunk in snapshot.payload.splitlines(keepends=True):
            text = chunk.rstrip("\r\n")
            if text:
                blocks.append({"schema_version": BLOCK_SCHEMA_VERSION, "block_id": f"b{len(blocks):06d}", "order": len(blocks), "parent_id": None, "type": "paragraph", "text": text, "heading_level": None, "links": [], "table": None, "source_locator": {"text_range": [offset, offset + len(text)]}, "mapping_status": "exact"})
            offset += len(chunk)
        return CandidateResult(method="markdown_text", text=snapshot.payload, markdown=blocks_to_markdown(blocks), blocks=blocks, diagnostics={"serializer": SERIALIZER_VERSION, "markdownify_version": MARKDOWNIFY_VERSION, "block_schema_version": BLOCK_SCHEMA_VERSION, "text_policy": "Original plain text retained verbatim; blocks preserve nonempty lines."})
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(snapshot.payload)
    for token in tokens:
        if token.map and token.nesting == 1:
            token.attrSet("data-source-lines", ":".join(map(str, token.map)))
    html = parser.renderer.render(tokens, parser.options, {})
    blocks = html_to_blocks(html, snapshot.href)
    soup = BeautifulSoup(html, "html.parser")
    paths = {dom_path(node): node for node in soup.find_all(True)}

    def clear_generated_locators(nodes):
        for node in nodes:
            node["source_locator"] = None
            node["mapping_status"] = "unavailable"
            clear_generated_locators(node.get("children", []))

    for block in blocks:
        node = paths.get(block["source_locator"]["dom_path"])
        declaration = node.get("data-source-lines") if node else None
        block["source_locator"] = {"line_range": list(map(int, declaration.split(":")))} if declaration else None
        block["mapping_status"] = "normalized_match" if declaration else "unavailable"
        # Generated HTML paths are not locations in the original Markdown.
        clear_generated_locators(block.get("inline_nodes", []))
        for cell in (block.get("table") or {}).get("cells", []):
            clear_generated_locators(cell.get("inline_nodes", []))
    return CandidateResult(method="markdown_text", html=html, text=blocks_to_text(blocks), markdown=blocks_to_markdown(blocks), blocks=blocks, diagnostics={"serializer": SERIALIZER_VERSION, "markdownify_version": MARKDOWNIFY_VERSION, "source_ranges": "Zero-based, end-exclusive lines; inline HTML treated as literal text."})
