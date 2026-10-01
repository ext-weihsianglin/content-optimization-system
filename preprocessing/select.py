"""Conservative diagnostic selection without citation labels or target queries."""

from collections import Counter
import re


def select_candidate(snapshot, candidates, inventory):
    method = "conservative_dom" if snapshot.format == "html" else "markdown_text"
    flags = list(inventory.get("quality_flags", []))
    common = {"policy": "retention-first-v1", "human_validated": False, "quality_flags": flags}
    if snapshot.format not in {"html", "markdown", "text"}:
        return {**common, "status": "unsupported_format", "method": None, "reasons": ["Ambiguous source format"]}
    if snapshot.payload.strip().casefold() == "not-implemented" or not inventory.get("body_text", "").strip():
        return {**common, "status": "source_insufficient", "method": None, "reasons": ["No useful text established in saved source"]}
    candidate = next((row for row in candidates if row["method"] == method and row["status"] == "ok" and row["text"].strip()), None)
    if candidate is None:
        return {**common, "status": "needs_review", "method": None, "reasons": ["Preferred retention candidate unavailable; no silent substitution"]}
    return {**common, "status": "needs_review" if flags else "selected", "method": method, "reasons": ["Preserve content and structure before downstream relevance decisions; flagged content remains available. Boilerplate is expected."]}


def select_precision_candidate(snapshot, candidates, inventory):
    usable = {row["method"]: row for row in candidates if row["status"] == "ok" and row["text"].strip()}
    flags = inventory.get("quality_flags", [])
    if snapshot.payload.strip().casefold() == "not-implemented" or not inventory.get("body_text", "").strip():
        return {"status": "source_insufficient", "method": None, "reasons": ["No useful text established in saved source"], "quality_flags": flags}
    if snapshot.format in {"markdown", "text"}:
        method = "markdown_text" if "markdown_text" in usable else None
        return {"status": "selected" if method else "needs_review", "method": method, "reasons": ["Native format preservation; no HTML article selection"], "quality_flags": flags}
    if snapshot.format != "html":
        return {"status": "unsupported_format", "method": None, "reasons": ["Ambiguous source format"], "quality_flags": flags}
    if "possible_error_response" in flags:
        return {"status": "needs_review", "method": None, "reasons": ["Source contains possible error-response language; not automatically discarded"], "quality_flags": flags}
    if not all(method in usable for method in ["readability", "trafilatura"]):
        return {"status": "needs_review", "method": None, "reasons": ["Independent article candidates did not both return content"], "quality_flags": flags}
    tokens = {method: Counter(re.findall(r"\w+", usable[method]["text"].casefold())) for method in ["readability", "trafilatura"]}
    overlap = sum((tokens["readability"] & tokens["trafilatura"]).values())
    denominator = sum((tokens["readability"] | tokens["trafilatura"]).values())
    agreement = overlap / denominator if denominator else 0
    if agreement < .65:
        return {"status": "needs_review", "method": None, "reasons": ["Substantial candidate disagreement"], "agreement": agreement, "quality_flags": flags}
    complex_structure = bool(re.search(r"<pre\b|<(?:th|td)\b[^>]*(?:rowspan|colspan)\s*=", snapshot.payload, re.I))
    method = "readability" if complex_structure else "trafilatura"
    return {"status": "selected", "method": method, "reasons": ["Diagnostic proposal: Trafilatura balances content/noise on development references; Readability is preferred for code or spanning tables based on controlled structural fixtures. Agreement is not proof of correctness."], "agreement": agreement, "quality_flags": flags, "human_validated": False}
