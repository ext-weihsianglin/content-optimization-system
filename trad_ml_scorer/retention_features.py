"""v2 features consume the retention-first document contract, not the v1 extractor."""

import math
import re
from urllib.parse import unquote, urlsplit

import numpy as np

from preprocessing.adapters.local import extract_conservative, extract_markdown_text
from preprocessing.downstream import document
from preprocessing.quality import classify_payload, source_inventory
from preprocessing.schema import Snapshot, snapshot_identity
from scripts.analyze_content import coverage, words
from scripts.analyze_quality import PATH_RULES

FEATURE_VERSION = "lr-retention-v2"
PARSER_POLICY = "retention-first-v1"
PROMPT = ["log_prompt_words", "prompt_question", "prompt_comparison", "prompt_how_to"]
URL = ["path_depth", "path_homepage", "path_editorial", "path_commerce", "path_support_docs"]
ALIGNMENT = ["coverage_title", "coverage_headings", "coverage_body", "coverage_intro"]
COUNTS = ["word_count", "title_words", "heading_count", "h1_count", "list_items", "table_count", "paragraph_count", "code_count", "ordered_steps"]
STRUCTURE = ["headings_per_1000_words", "list_items_per_1000_words", "has_table", "has_list"]
METADATA = ["has_jsonld", "has_article_schema", "log_source_script_count", "empty_title"]
QUALITY = ["retained_text_fraction", "needs_review", "possible_error_response", "sparse_body", "format_html"]
SECTION = ["coverage_h1", "coverage_table_headers", "best_section_coverage", "mean_section_coverage", "matching_section_fraction", "best_section_heading_coverage", "best_section_position", "comparison_x_table_header_coverage", "how_to_x_ordered_steps"]
WHOLE_NAMES = PROMPT + URL + ALIGNMENT + [f"log_{name}" for name in COUNTS] + STRUCTURE + METADATA + QUALITY
FEATURE_NAMES = WHOLE_NAMES + SECTION
FAMILIES = {"prompt": PROMPT, "url": URL, "whole_alignment": ALIGNMENT, "content_size": [f"log_{name}" for name in COUNTS], "structure": STRUCTURE, "source_metadata": METADATA, "quality": QUALITY, "section_alignment": SECTION}


def parse_snapshot(payload, href, hostname="", source=None):
    """Same source inventory, adapters, selection, and document builder as preprocessing."""
    payload_hash, identity = snapshot_identity(payload, href)
    format_name = classify_payload(payload)
    snapshot = Snapshot(identity, payload_hash, href, hostname, payload, format_name)
    inventory = source_inventory(payload, href, format_name)
    candidate = extract_conservative(snapshot) if format_name == "html" else extract_markdown_text(snapshot)
    source = {**(source or {}), "payload_hash": payload_hash, "href": href, "hostname": hostname, "format": format_name}
    for key in ("source_file", "source_file_hash", "source_row"):
        source.setdefault(key, None)
    doc, chunks = document(snapshot, source, [candidate.to_dict()], inventory)
    # Model-only diagnostic derived from the parser's original source view, same tokenizer.
    doc["scorer_source_word_count"] = len(words(inventory["body_text"]))
    # Caller can load the immutable source Parquet row rather than an eval-only .txt path.
    doc["raw_payload_path"] = None
    doc["raw_payload_reference"] = {key: source[key] for key in ("source_file", "source_file_hash", "source_row", "payload_hash")}
    doc["chunks"] = chunks
    return doc


def sections_from_blocks(blocks):
    """Non-overlapping sections in DOM order; parent containers own no child text."""
    sections = []
    current = {"heading": "", "texts": []}
    for block in blocks:
        if block["type"] == "heading":
            if current["texts"]:
                sections.append(current)
            current = {"heading": block.get("text", ""), "texts": [block.get("text", "")]}
        elif block.get("text"):
            current["texts"].append(block["text"])
    if current["texts"]:
        sections.append(current)
    return sections


def features_from_document(prompt, doc):
    if doc.get("schema_version") != "downstream-document-v1" or doc["selection"]["policy"] != PARSER_POLICY:
        raise ValueError("Unsupported retention document schema or policy")
    if not doc["selection"].get("method") or not doc["text"].strip():
        raise ValueError("No selected retained content; preserve status and abstain")
    blocks = doc["blocks"]
    metadata = doc["source_metadata"]
    title = metadata.get("title", "")
    text = doc["text"]
    headings = [b for b in blocks if b["type"] == "heading"]
    h1 = [b["text"] for b in headings if b.get("heading_level") == 1]
    tables = [b for b in blocks if b["type"] == "table"]
    table_headers = [cell["text"] for b in tables for cell in b["table"]["cells"] if cell["is_header"]]
    indexed = {b["block_id"]: b for b in blocks}
    steps = sum(b["type"] == "list_item" and bool(indexed.get(b.get("parent_id"), {}).get("ordered")) for b in blocks)
    counts = {
        "word_count": len(words(text)), "title_words": len(words(title)), "heading_count": len(headings),
        "h1_count": len(h1), "list_items": sum(b["type"] == "list_item" for b in blocks),
        "table_count": len(tables), "paragraph_count": sum(b["type"] == "paragraph" for b in blocks),
        "code_count": sum(b["type"] == "code" for b in blocks), "ordered_steps": steps,
    }
    path = unquote(urlsplit(doc["source"]["href"]).path).casefold()
    comparison = int(bool(re.search(r"\b(best|compare|comparison|versus|vs|better|cheapest)\b", prompt, re.I)))
    how_to = int(bool(re.search(r"\bhow\s+to\b", prompt, re.I)))
    types = {kind.rsplit("/", 1)[-1] for item in metadata.get("jsonld", []) for kind in item.get("types", []) if isinstance(kind, str)}
    flags = doc["selection"]["quality_flags"]
    values = {
        "log_prompt_words": math.log1p(len(words(prompt))),
        "prompt_question": int(bool(re.match(r"^(what|which|where|when|why|how|who|can|could|is|are|do|does|should|will)\b", prompt.strip(), re.I)) or "?" in prompt or "？" in prompt),
        "prompt_comparison": comparison, "prompt_how_to": how_to,
        "path_depth": len([p for p in path.split("/") if p]), "path_homepage": int(path in {"", "/"}),
        "coverage_title": coverage([prompt], title), "coverage_headings": coverage([prompt], " ".join(b["text"] for b in headings)),
        "coverage_body": coverage([prompt], text), "coverage_intro": coverage([prompt], " ".join(words(text)[:200])),
        "coverage_h1": coverage([prompt], " ".join(h1)), "coverage_table_headers": coverage([prompt], " ".join(table_headers)),
        "headings_per_1000_words": 1000 * counts["heading_count"] / counts["word_count"] if counts["word_count"] else None,
        "list_items_per_1000_words": 1000 * counts["list_items"] / counts["word_count"] if counts["word_count"] else None,
        "has_table": int(bool(tables)), "has_list": int(any(b["type"] == "list" for b in blocks)),
        "has_jsonld": int(bool(metadata.get("jsonld"))),
        "has_article_schema": int(bool(types & {"Article", "NewsArticle", "BlogPosting", "TechArticle", "ScholarlyArticle", "Report"})),
        "log_source_script_count": math.log1p(metadata.get("counts", {}).get("scripts", 0)),
        "empty_title": int(not title.strip()),
        "retained_text_fraction": min(1., counts["word_count"] / doc["scorer_source_word_count"]) if doc["scorer_source_word_count"] else None,
        "needs_review": int(doc["selection"]["status"] == "needs_review"),
        "possible_error_response": int("possible_error_response" in flags),
        "sparse_body": int(counts["word_count"] <= 30), "format_html": int(doc["source"]["format"] == "html"),
    }
    for name in ("editorial", "commerce", "support_docs"):
        values[f"path_{name}"] = int(bool(re.search(PATH_RULES[name], path)))
    values.update({f"log_{name}": math.log1p(counts[name]) for name in COUNTS})
    sections = sections_from_blocks(blocks)
    scores = [coverage([prompt], " ".join(section["texts"])) for section in sections]
    valid = [(i, score) for i, score in enumerate(scores) if score is not None]
    if valid:
        best, score = max(valid, key=lambda pair: (pair[1], -pair[0]))
        values.update(best_section_coverage=score, mean_section_coverage=float(np.mean([v for _, v in valid])),
                      matching_section_fraction=sum(v > 0 for _, v in valid) / len(valid),
                      best_section_heading_coverage=coverage([prompt], sections[best]["heading"]),
                      best_section_position=best / max(1, len(sections) - 1))
    else:
        values.update({name: None for name in SECTION[2:7]})
    values["comparison_x_table_header_coverage"] = comparison * values["coverage_table_headers"] if values["coverage_table_headers"] is not None else None
    values["how_to_x_ordered_steps"] = how_to * math.log1p(steps)
    return {name: float(values[name]) if values[name] is not None else np.nan for name in FEATURE_NAMES}


def predict_retention(bundle, prompt, html, href=""):
    if bundle["feature_version"] != FEATURE_VERSION:
        raise ValueError("Model and retention feature version do not match")
    doc = parse_snapshot(html, href)
    if not doc["selection"].get("method") or not doc["text"].strip():
        return {"p_is_cited_high": None, "selection": doc["selection"], "reason": "No retained content; model abstained"}
    row = features_from_document(prompt, doc)
    matrix = np.array([[row[name] for name in bundle["feature_names"]]])
    return {"p_is_cited_high": float(bundle["pipeline"].predict_proba(matrix)[0, 1]), "selection": doc["selection"], "feature_version": FEATURE_VERSION}
