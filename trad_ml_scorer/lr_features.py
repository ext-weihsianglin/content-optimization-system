"""Inference-time features shared by training and prediction; no fitted statistics."""

import math
import re
from urllib.parse import unquote, urlsplit

import numpy as np

from scripts.analyze_content import coverage, extract, words
from scripts.analyze_quality import PATH_RULES, probe

FEATURE_VERSION = "lr-handcrafted-v1"
ALIGNMENT = [f"coverage_{name}" for name in ("title", "headings", "body", "intro", "url_path")]
PROMPT = ["log_prompt_words", "prompt_question", "prompt_comparison", "prompt_how_to"]
COUNTS = ["word_count", "title_words", "heading_count", "h1_count", "list_items", "table_count"]
PAGE = [f"log_{name}" for name in COUNTS] + [
    "headings_per_1000_words", "list_items_per_1000_words", "has_table", "has_list",
    "has_main", "has_article", "has_jsonld", "has_article_schema", "removed_text_fraction",
    "focus_text_fraction", "script_char_ratio", "path_depth", "path_homepage",
    "path_editorial", "path_commerce", "path_support_docs", "empty_title", "sparse_body",
    "failure_page", "recognized_html",
]
FEATURE_NAMES = ALIGNMENT + PROMPT + PAGE
FAMILIES = {
    "alignment": ALIGNMENT,
    "prompt": PROMPT,
    "content_size": [f"log_{name}" for name in COUNTS],
    "structure": ["headings_per_1000_words", "list_items_per_1000_words", "has_table", "has_list"],
    "html_metadata": ["has_main", "has_article", "has_jsonld", "has_article_schema"],
    "url": ["path_depth", "path_homepage", "path_editorial", "path_commerce", "path_support_docs"],
    "quality": ["removed_text_fraction", "focus_text_fraction", "script_char_ratio", "empty_title", "sparse_body", "failure_page", "recognized_html"],
}


def features_from_extraction(prompt, href, page, quality):
    """Coverage is always recomputed for this prompt, never averaged across records."""
    path = unquote(urlsplit(href or "").path).casefold()
    targets = [page["title"], " ".join(page["headings"]), page["extracted_text"],
               " ".join(words(page["extracted_text"])[:200]), path]
    result = {name: coverage([prompt], text) for name, text in zip(ALIGNMENT, targets)}
    result.update({
        "log_prompt_words": math.log1p(len(words(prompt))),
        "prompt_question": int(bool(re.match(r"^(what|which|where|when|why|how|who|can|could|is|are|do|does|should|will)\b", prompt.strip(), re.I)) or "?" in prompt or "？" in prompt),
        "prompt_comparison": int(bool(re.search(r"\b(best|compare|comparison|versus|vs|better|cheapest)\b", prompt, re.I))),
        "prompt_how_to": int(bool(re.search(r"\bhow\s+to\b", prompt, re.I))),
    })
    result.update({f"log_{name}": math.log1p(page[name]) for name in COUNTS})
    for name in PAGE:
        if name in page:
            result[name] = page[name]
    result.update({
        "path_depth": len([part for part in path.split("/") if part]),
        "path_homepage": int(path in {"", "/"}),
        "empty_title": int(not page["title"].strip()),
        "sparse_body": int(quality["sparse_body_candidate"]),
        "failure_page": int(quality["clear_failure_union"]),
        "recognized_html": int(quality["html_markup"]),
    })
    for name in ("editorial", "commerce", "support_docs"):
        result[f"path_{name}"] = int(bool(re.search(PATH_RULES[name], path)))
    return {name: float(result[name]) if result[name] is not None else np.nan for name in FEATURE_NAMES}


def extract_features(prompt, html, href=""):
    page = extract(html)
    quality = probe((prompt, None, href, "", html))["flags"]
    return features_from_extraction(prompt, href, page, quality)


def predict(bundle, prompt, html, href=""):
    if bundle["feature_version"] != FEATURE_VERSION:
        raise ValueError("Model feature version does not match this extractor")
    row = extract_features(prompt, html, href)
    matrix = np.array([[row[name] for name in bundle["feature_names"]]])
    return float(bundle["pipeline"].predict_proba(matrix)[0, 1])
