"""Offline source inventory and deliberately heuristic payload classification."""

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from preprocessing.blocks import _dom_index, html_to_blocks, blocks_to_text


HTML = re.compile(r"<!doctype\s+html\b|</?(?:html|head|body|title|meta|link|main|article|section|div|span|p|h[1-6]|ul|ol|li|table|tr|td|th|pre|code|a|img|script|style|nav|footer|header|form|aside|blockquote|br|hr|dl|dt|dd|del|s|strike|kbd|samp|figure|figcaption|address|details|summary)\b[^>]*>", re.I)
MARKDOWN = re.compile(r"(?m)^ {0,3}(?:#{1,6}\s|```|~~~|>\s|[-+*]\s|\d+[.)]\s)|\[[^\]\n]+\]\([^\n)]+\)|\*\*[^*\n]+\*\*|(?m:^.+\n(?:===+|---+)\s*$)")


def classify_payload(payload):
    if not isinstance(payload, str) or not payload.strip() or "\x00" in payload:
        return "unknown"
    if re.match(r"\s*(?:\{|\[|<\?xml\b|%PDF-)", payload):
        return "unknown"
    outside_fences = re.sub(r"(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1\s*$", "", payload)
    html = bool(HTML.search(outside_fences))
    markdown = bool(MARKDOWN.search(payload))
    if html and markdown and not re.search(r"<(?:html|body|main|article)\b", payload, re.I):
        return "unknown"
    return "html" if html else "markdown" if markdown else "text"


def source_inventory(payload, href, format):
    result = {"title": "", "language": None, "direction": None, "description": None, "canonical": None, "headings": [], "quality_flags": [], "jsonld": [], "body_text": "", "counts": {}, "visibility": [], "metadata": {}}
    if format == "html":
        soup = BeautifulSoup(payload, "html.parser")
        source_paths = _dom_index(soup)[0]
        result["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
        result["language"] = soup.html.get("lang") if soup.html else None
        result["direction"] = soup.html.get("dir") if soup.html else None
        for node in soup.find_all("meta"):
            key = node.get("name") or node.get("property")
            if key and node.has_attr("content"):
                result["metadata"].setdefault(key.lower(), []).append(node["content"])
        result["description"] = next(iter(result["metadata"].get("description", [])), None)
        canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
        if canonical and canonical.has_attr("href"):
            result["canonical"] = {"target": canonical["href"], "resolved_target": urljoin(href, canonical["href"])}
        for node in soup.find_all("script"):
            if node.get("type", "").split(";")[0].strip().lower() != "application/ld+json":
                continue
            entry = {"source_locator": {"dom_path": source_paths[id(node)]}, "raw": node.get_text(), "parse_status": "ok", "types": []}
            try:
                entry["value"] = json.loads(entry["raw"])
                pending = [entry["value"]]
                types = set()
                while pending:
                    value = pending.pop()
                    if isinstance(value, dict):
                        declared = value.get("@type", [])
                        declared = [declared] if isinstance(declared, str) else declared
                        if isinstance(declared, list):
                            types.update(item for item in declared if isinstance(item, str))
                        pending.extend(value.values())
                    elif isinstance(value, list):
                        pending.extend(value)
                entry["types"] = sorted(types)
            except (ValueError, RecursionError) as error:
                entry.update(parse_status="error", error=type(error).__name__)
            result["jsonld"].append(entry)
        groups = {"headings": [f"h{level}" for level in range(1, 7)], "lists": ["ul", "ol"], "list_items": ["li"], "tables": ["table"], "links": ["a"], "images": ["img"], "code": ["pre", "code"], "semantic_containers": ["main", "article", "section", "aside", "nav", "header", "footer"], "scripts": ["script"]}
        result["counts"] = {key: len(soup.find_all(tags)) for key, tags in groups.items()}
        result["headings"] = [node.get_text(" ", strip=True) for node in soup.find_all(groups["headings"])]
        for node in soup.find_all(True):
            hints = {key: node[key] for key in ("hidden", "aria-hidden", "style", "lang", "dir") if node.has_attr(key)}
            if hints:
                result["visibility"].append({"source_locator": {"dom_path": source_paths[id(node)]}, "attributes": hints, "computed_visibility": "unknown"})
        # Inventory needs the source text view, not a second Markdown serialization.
        result["body_text"] = blocks_to_text(html_to_blocks(payload, href, include_inline=False))
        if result["counts"]["scripts"] and len(result["body_text"].split()) < 10:
            result["quality_flags"].append("possible_script_shell")
        if re.search(r"<[^>]*$", payload) or (re.search(r"<html\b", payload, re.I) and not re.search(r"</html\s*>", payload, re.I)):
            result["quality_flags"].append("possible_truncation")
    else:
        result["body_text"] = payload
        if format == "unknown":
            result["quality_flags"].append("ambiguous_or_unsupported_payload")
    if not result["body_text"].strip():
        result["quality_flags"].append("empty_body")
    if re.search(r"\b(?:access denied|forbidden|captcha|not found|internal server error|service unavailable|enable javascript)\b", result["title"] + " " + result["body_text"], re.I):
        result["quality_flags"].append("possible_error_response")
    result["counts"]["body_words"] = len(result["body_text"].split())
    return result
