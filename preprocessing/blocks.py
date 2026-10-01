"""DOM-order blocks; collapse prose whitespace, preserve preformatted whitespace.

Container blocks own no descendant text. Locators describe parsed DOM paths,
never byte offsets or visual order. Transformed DOMs require unique matches.
"""

from collections import defaultdict
from html import escape as html_escape
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


IGNORED = {"script", "style", "template", "head", "title", "meta", "link", "noscript"}
BLOCK_SCHEMA_VERSION = "dom-blocks-v2"
PRESERVE_WHITESPACE_TAGS = {"pre", "textarea", "code", "kbd"}
STRUCTURAL = {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "form", "ul", "ol", "li", "table", "pre", "blockquote", "hr", "dl", "dt", "dd", "figure", "figcaption", "address", "details", "summary"} | {f"h{level}" for level in range(1, 7)}


def normalized(text):
    return " ".join(text.split())


def dom_path(node):
    parts = []
    while isinstance(node, Tag) and node.name != "[document]":
        index = 1 + sum(sibling.name == node.name for sibling in node.previous_siblings if isinstance(sibling, Tag))
        parts.append(f"{node.name}[{index}]")
        node = node.parent
    return "/" + "/".join(reversed(parts))


def _inline(node):
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if node.name in IGNORED:
        return ""
    if node.name == "br":
        return "\n"
    if node.name == "img":
        return node.get("alt", "")
    return "".join(_inline(child) for child in node.children)


def _links(nodes, href):
    links = []
    for node in nodes:
        if not isinstance(node, Tag):
            continue
        for anchor in ([node] if node.name == "a" else []) + list(node.find_all("a")):
            if anchor.has_attr("href"):
                target = anchor["href"]
                links.append({"text": normalized(_inline(anchor)), "target": target, "resolved_target": urljoin(href, target)})
    return links


def _target(target):
    return target.replace("<", "%3C").replace(">", "%3E").replace("\n", "%0A").replace("\r", "%0D")


def _render_inline(node):
    kind = node["type"]
    if kind == "text":
        return _escape(re.sub(r"\s+", " ", node["text"]))
    if kind == "hard_break":
        return "\\\n"
    if kind == "inline_code":
        text = node["text"]
        # CommonMark code spans normalize newlines and some edge whitespace.
        # Use HTML when a code span would lose that source information.
        if not text or "\n" in text or "\r" in text or not text.strip():
            return f"<{node['tag']}>{html_escape(text)}</{node['tag']}>"
        fence = "`" * (1 + max(map(len, re.findall(r"`+", text)), default=0))
        padding = " " if text.startswith(("`", " ")) or text.endswith(("`", " ")) else ""
        return fence + padding + text + padding + fence
    if kind == "inline_image":
        if not node.get("target"):
            return node["html"]
        return f"![{_escape(node['text'])}](<{_target(node['resolved_target'])}>)"
    text = "".join(_render_inline(child) for child in node.get("children", []))
    if kind == "link" and "target" in node:
        return f"[{text}](<{_target(node['resolved_target'])}>)"
    if kind == "strong":
        return f"**{text}**"
    if kind == "emphasis":
        return f"*{text}*"
    if kind == "deletion":
        return f"~~{text}~~"
    return text


def _table(node, href, annotation=None):
    rows = [row for row in node.find_all("tr") if row.find_parent("table") is node]
    cells = []
    occupied = set()
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            while (row_index, column) in occupied:
                column += 1
            spans = {}
            for key in ("rowspan", "colspan"):
                try:
                    spans[key] = int(cell.get(key, 1))
                except (ValueError, TypeError):
                    spans[key] = 1
            if spans["rowspan"] == 0:
                spans["rowspan"] = sum(other.parent is row.parent for other in rows[row_index:])
            spans = {key: max(1, min(value, 1000)) for key, value in spans.items()}
            cells.append({"row": row_index, "column": column, "text": normalized(_inline(cell)), "is_header": cell.name == "th", "role": cell.name, "scope": cell.get("scope"), "headers": cell.get("headers", []), "id": cell.get("id"), "row_group": cell.parent.parent.name, **spans, "links": _links([cell], href)})
            if annotation:
                cells[-1]["inline_nodes"] = [item for child in cell.children if (item := annotation(child)) is not None]
            for offset in range(min(spans["rowspan"], len(rows) - row_index)):
                for width in range(spans["colspan"]):
                    occupied.add((row_index + offset, column + width))
            column += spans["colspan"]
    caption = node.find("caption", recursive=False)
    return {"caption": normalized(_inline(caption)) if caption else "", "cells": cells, "rows": len(rows), "columns": max((cell["column"] + cell["colspan"] for cell in cells), default=0), "html": str(node), "span_policy": "Invalid spans become 1; grid spans bounded at 1000; original attributes retained in HTML."}


def html_to_blocks(html, href, source_html=None):
    soup = BeautifulSoup(html, "html.parser", preserve_whitespace_tags=PRESERVE_WHITESPACE_TAGS)
    source = soup if source_html is None or source_html == html else BeautifulSoup(source_html, "html.parser", preserve_whitespace_tags=PRESERVE_WHITESPACE_TAGS)
    exact_index = defaultdict(list)
    text_index = defaultdict(list)
    if source is not soup:
        for node in source.find_all(True):
            exact_index[(node.name, str(node))].append(node)
            text_index[(node.name, normalized(_inline(node)))].append(node)
    blocks = []
    locator_cache = {}

    def locate(node, exact_only=False):
        key = (id(node), exact_only)
        if key not in locator_cache:
            locator_cache[key] = locate_uncached(node, exact_only)
        return locator_cache[key]

    def locate_uncached(node, exact_only=False):
        if source is soup:
            return {"dom_path": dom_path(node)}, "exact"
        matches = exact_index[(node.name, str(node))]
        if len(matches) == 1:
            return {"dom_path": dom_path(matches[0])}, "exact"
        if exact_only:
            # A repeated inline element can still be located through an exact,
            # unique enclosing subtree. Never transfer semantics by text alone.
            ancestor = node.parent
            if ancestor is None:
                return None, "unavailable"
            indices = [next(i for i, child in enumerate(ancestor.contents) if child is node)]
            while isinstance(ancestor, Tag) and ancestor.name != "[document]":
                candidates = exact_index[(ancestor.name, str(ancestor))]
                if len(candidates) == 1:
                    original = candidates[0]
                    for index in reversed(indices):
                        original = original.contents[index]
                    return {"dom_path": dom_path(original)}, "exact"
                if ancestor.parent is None:
                    break
                indices.append(next(i for i, child in enumerate(ancestor.parent.contents) if child is ancestor))
                ancestor = ancestor.parent
            return None, "ambiguous" if matches else "unavailable"
        status = "exact"
        if not matches:
            matches = text_index[(node.name, normalized(_inline(node)))]
            status = "normalized_match"
        if len(matches) == 1:
            return {"dom_path": dom_path(matches[0])}, status
        return None, "ambiguous" if matches else "unavailable"

    def annotation(node):
        if isinstance(node, Comment) or (isinstance(node, Tag) and node.name in IGNORED):
            return None
        if isinstance(node, NavigableString):
            locator, status = locate(node.parent, exact_only=True)
            if locator:
                locator = {**locator, "child_index": next(i for i, child in enumerate(node.parent.contents) if child is node)}
            return {"type": "text", "text": str(node), "source_locator": locator, "mapping_status": status}
        locator, status = locate(node, exact_only=True)
        kind = {"code": "inline_code", "kbd": "inline_code", "del": "deletion", "s": "deletion", "strike": "deletion", "br": "hard_break", "img": "inline_image", "strong": "strong", "b": "strong", "em": "emphasis", "i": "emphasis", "a": "link"}.get(node.name, "span")
        result = {"type": kind, "tag": node.name, "attributes": dict(node.attrs), "source_locator": locator, "mapping_status": status}
        if kind in {"inline_code", "inline_image"}:
            result["text"] = _inline(node)
        if kind == "inline_image":
            result.update(target=node.get("src", ""), resolved_target=urljoin(href, node.get("src", "")), html=str(node))
        if kind == "link" and node.has_attr("href"):
            result.update(target=node["href"], resolved_target=urljoin(href, node["href"]))
        result["children"] = [item for child in node.children if (item := annotation(child)) is not None]
        return result

    def add(kind, node, parent, text="", links=None, **extra):
        locator, status = locate(node)
        block = {"schema_version": BLOCK_SCHEMA_VERSION, "block_id": f"b{len(blocks):06d}", "order": len(blocks), "parent_id": parent, "type": kind, "text": text, "heading_level": None, "links": links or [], "table": None, "source_locator": locator, "mapping_status": status, **extra}
        blocks.append(block)
        return block["block_id"]

    def walk(node, parent=None):
        if node.name in IGNORED:
            return
        if node.name == "table":
            table = _table(node, href, annotation)
            text = "\n".join(filter(None, [table["caption"], *["\t".join(cell["text"] for cell in table["cells"] if cell["row"] == row) for row in range(table["rows"])]]))
            add("table", node, parent, text, _links([node], href), table=table)
            return
        if node.name == "pre":
            add("code", node, parent, node.get_text(), language=(node.code.get("class", [""])[0].removeprefix("language-") if node.code else ""))
            return
        if node.name == "img":
            add("image", node, parent, node.get("alt", ""), target=node.get("src", ""), resolved_target=urljoin(href, node.get("src", "")))
            return
        if node.name == "hr":
            add("thematic_break", node, parent)
            return
        if node.name in {"ul", "ol", "li", "blockquote", "dl", "dt", "dd"}:
            kind = {"ul": "list", "ol": "list", "li": "list_item", "blockquote": "quote", "dl": "definition_list", "dt": "definition_term", "dd": "definition_description"}[node.name]
            extra = {}
            if kind == "list":
                try:
                    start = int(node.get("start", 1))
                except (ValueError, TypeError):
                    start = 1
                extra = {"ordered": node.name == "ol", "start": start}
            if kind == "definition_list":
                extra = {"html": str(node), "serialization": "HTML fallback; ordered term/description children remain authoritative."}
            parent = add(kind, node, parent, **extra)
        inline = []

        def flush():
            text = normalized("".join(_inline(child) for child in inline))
            annotations = [item for child in inline if (item := annotation(child)) is not None]
            markdown = "".join(_render_inline(item) for item in annotations).strip(" ")
            if text or markdown.strip():
                heading = bool(re.fullmatch(r"h[1-6]", node.name or ""))
                add("heading" if heading else "paragraph", node, parent, text, _links(inline, href), heading_level=int(node.name[1]) if heading else None, inline_nodes=annotations, inline_markdown=markdown)
            inline.clear()

        for child in node.children:
            if isinstance(child, Tag) and (child.name in STRUCTURAL or child.find(STRUCTURAL)):
                flush()
                walk(child, parent)
            else:
                inline.append(child)
        flush()

    walk(soup.body or soup)
    return blocks


def blocks_to_text(blocks):
    return "\n\n".join(block["text"] for block in blocks if block.get("text"))


def _escape(text):
    return re.sub(r"([\\`*_{}\[\]<>#!|])", r"\\\1", text)


def blocks_to_markdown(blocks):
    children = defaultdict(list)
    for block in blocks:
        children[block.get("parent_id")].append(block)

    def render(block):
        kind = block["type"]
        text = ("".join(_render_inline(node) for node in block["inline_nodes"]).strip(" ")
                if "inline_nodes" in block else block.get("inline_markdown", _escape(block.get("text", ""))))
        nested = "\n\n".join(render(child) for child in children[block["block_id"]])
        if kind == "heading":
            return "#" * block["heading_level"] + " " + text
        if kind == "code":
            runs = re.findall(r"`+", block["text"])
            fence = "`" * max(3, 1 + max(map(len, runs), default=0))
            return f"{fence}{block.get('language', '')}\n{block['text']}" + ("" if block["text"].endswith("\n") else "\n") + fence
        if kind == "image":
            return f"![{text}](<{block.get('resolved_target', '').replace('>', '%3E')}>)"
        if kind == "table":
            return block["table"]["html"]
        if kind == "thematic_break":
            return "---"
        if kind == "definition_list":
            return block["html"]
        if kind == "list":
            items = []
            for index, child in enumerate(children[block["block_id"]]):
                marker = f"{block.get('start', 1) + index}. " if block.get("ordered") else "- "
                content = render(child)
                lines = content.split("\n")
                items.append(marker + lines[0] + "".join("\n" + " " * len(marker) + line for line in lines[1:]))
            return "\n".join(items)
        if kind == "quote":
            return "\n".join("> " + line for line in (text + ("\n\n" if text and nested else "") + nested).split("\n"))
        return text + ("\n\n" if text and nested else "") + nested

    return "\n\n".join(render(block) for block in children[None])
