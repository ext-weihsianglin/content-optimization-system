"""Conservative scrape-quality and prompt-confounding audit; no network requests."""

import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import duckdb


ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"\w+", re.UNICODE)
BLOCK = re.compile(r"access denied|request blocked|attention required|just a moment|verify (?:that )?you are human|checking your browser|security verification", re.I)
ERROR = re.compile(r"^(?:404(?:\b|\s)|403\b|500\b|502\b|503\b|page not found|not found\b|service unavailable|internal server error|bad gateway)", re.I)
JS = re.compile(r"(?:enable|turn on) javascript|javascript (?:is required|must be enabled)|you need to enable javascript", re.I)
PATH_RULES = {
    "editorial": r"/(?:blog|blogs|articles?|news|insights|resources|guides?|learn|tutorials?)(?:/|$)",
    "commerce": r"/(?:products?|collections?|shop|store|pricing|plans|packages)(?:/|$)",
    "support_docs": r"/(?:help|support|docs|documentation|faq|faqs)(?:/|$)",
    "corporate_legal": r"/(?:careers|jobs|about|about-us|contact|privacy|terms)(?:/|$)",
    "directory_search": r"/(?:search|category|categories|tag|tags|directory)(?:/|$)",
}


class TextProbe(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.excluded = []
        self.title_depth = 0
        self.title_parts = []
        self.parts = []
        self.scripts = 0
        self.tags = 0
        self.pdf_embed = False

    def handle_starttag(self, tag, attrs):
        self.tags += 1
        attributes = dict(attrs)
        if tag == "script":
            self.scripts += 1
        if tag in {"script", "style", "template", "noscript", "head"}:
            self.excluded.append(tag)
        if tag == "title":
            self.title_depth += 1
        if tag in {"embed", "object", "iframe"}:
            self.pdf_embed |= "pdf" in (attributes.get("type", "") or "").lower() or bool(re.search(r"\.pdf(?:$|[?#])", attributes.get("src", "") or attributes.get("data", "") or "", re.I))

    def handle_endtag(self, tag):
        if tag in self.excluded:
            reverse_index = self.excluded[::-1].index(tag)
            del self.excluded[len(self.excluded) - reverse_index - 1:]
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)

    def handle_data(self, data):
        if self.title_depth:
            self.title_parts.append(data)
        if not self.excluded:
            self.parts.append(data)


def normalize(prompt):
    return " ".join(unicodedata.normalize("NFKC", prompt or "").casefold().split())


def probe(row):
    prompt, category, href, host, content = row
    content = content or ""
    parser = TextProbe()
    parser.feed(content)
    title = " ".join(" ".join(parser.title_parts).split())
    body = " ".join(" ".join(parser.parts).split())
    words = len(TOKEN.findall(body))
    path = unquote(urlsplit(href or "").path).lower()
    html = bool(re.search(r"<(?:html|head|body|div|p|article|script|!doctype)\b", content, re.I))
    stripped = content.lstrip()
    flags = {
        "empty_content": not stripped,
        "html_markup": html,
        "markdown_like_without_html": not html and bool(re.search(r"(?m)^\s{0,3}#{1,6}\s|\[[^\]\n]+\]\(https?://", content)),
        "pdf_url": bool(re.search(r"\.pdf$", path)),
        "pdf_magic": stripped.startswith("%PDF-"),
        "pdf_embed": parser.pdf_embed,
        "no_recognized_html": not html,
        "explicit_unimplemented_payload": stripped.casefold() == "not-implemented",
        "image_document_candidate": words == 0 and bool(re.search(r"\.(?:png|jpe?g|gif|webp)\s*\(\d+\s*[×x]\s*\d+\)", title, re.I)),
        "blocked_title_or_short_body": bool(BLOCK.search(title) or (words <= 150 and BLOCK.search(body))),
        "error_title_or_short_body": bool(ERROR.search(title) or (words <= 100 and ERROR.search(body))),
        "explicit_js_requirement_short_body": words <= 150 and bool(JS.search(body)),
        "sparse_script_shell_candidate": words <= 30 and parser.scripts >= 1,
        "sparse_body_candidate": words <= 30,
    }
    flags["clear_failure_union"] = any(flags[name] for name in ("empty_content", "explicit_unimplemented_payload", "blocked_title_or_short_body", "error_title_or_short_body", "explicit_js_requirement_short_body"))
    prompt_text = prompt or ""
    prompt_words = len(TOKEN.findall(prompt_text))
    styles = {
        "missing_or_blank": not prompt_text.strip(),
        "contains_question_mark": "?" in prompt_text or "？" in prompt_text,
        "long_40plus_words": prompt_words >= 40,
        "short_1to5_words": 1 <= prompt_words <= 5,
        "contains_non_ascii": any(ord(character) > 127 for character in prompt_text),
        "english_question_start": bool(re.match(r"^(?:what|which|where|when|why|how|who|can|could|is|are|do|does|should|will)\b", prompt_text.strip(), re.I)),
        "english_comparison_marker": bool(re.search(r"\b(?:best|compare|comparison|versus|vs|better|cheapest)\b", prompt_text, re.I)),
    }
    for script, pattern in {
        "devanagari": r"[\u0900-\u097f]", "han": r"[\u3400-\u4dbf\u4e00-\u9fff]",
        "kana": r"[\u3040-\u30ff]", "hangul": r"[\uac00-\ud7af]",
        "arabic": r"[\u0600-\u06ff]", "cyrillic": r"[\u0400-\u04ff]",
        "thai": r"[\u0e00-\u0e7f]", "hebrew": r"[\u0590-\u05ff]",
    }.items():
        styles[f"contains_{script}_block"] = bool(re.search(pattern, prompt_text))
    return {
        "prompt": prompt, "category": category, "href": href, "host": host,
        "title": title, "body_words": words, "body_excerpt": body[:700],
        "raw_prefix": content[:220], "flags": flags,
        "path_hints": [name for name, pattern in PATH_RULES.items() if re.search(pattern, path)] + (["homepage"] if path in {"", "/"} else []),
        "prompt_words": prompt_words, "prompt_chars": len(prompt_text), "styles": styles,
    }


def distribution(values):
    ordered = sorted(values)
    return {"n": len(values), "mean": round(statistics.mean(values), 3), "median": statistics.median(values), "p10": ordered[int((len(ordered) - 1) * .1)], "p90": ordered[int((len(ordered) - 1) * .9)], "max": max(values)} if values else {"n": 0}


def example(row):
    return {key: row[key] for key in ("host", "category", "href", "prompt", "title", "body_words", "body_excerpt", "raw_prefix", "path_hints")}


def main():
    connection = duckdb.connect()
    cursor = connection.execute("SELECT prompt,citation_category,href,hostname,html_content FROM read_parquet(?, filename=true, file_row_number=true) ORDER BY filename, file_row_number", [str(ROOT / "data/raw/*.parquet")])
    records = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        while batch := cursor.fetchmany(100):
            records.extend(pool.map(probe, batch, chunksize=5))
            if len(records) % 1000 == 0:
                print(f"Parsed {len(records)} rows", flush=True)
    categories = sorted({row["category"] for row in records})
    result = {
        "scope": "Scrape integrity, path hints and prompt confounding only; rows are citation records, not independent trials.",
        "row_count": len(records),
        "format": {"columns": [column[0] for column in cursor.description], "markdown_column_present": False},
        "heuristics": {
            "body_text": "HTMLParser text excluding head/script/style/template/noscript; includes navigation and CSS-hidden text, not rendered or main-article text.",
            "blocked_title_or_short_body": BLOCK.pattern + "; match title, or body only when <=150 word tokens.",
            "error_title_or_short_body": ERROR.pattern + "; match title start, or body start only when <=100 word tokens.",
            "explicit_js_requirement_short_body": JS.pattern + "; body <=150 words; noscript fallback excluded.",
            "sparse_script_shell_candidate": "<=30 body words and >=1 script; suspicion only, not proven failed render.",
            "sparse_body_candidate": "<=30 body words; diagnostic, not automatic failure.",
            "clear_failure_union": "Union of empty, literal not-implemented payload, blocked, error and explicit short-body JS requirement flags; heuristic proxy, not HTTP status evidence.",
            "explicit_unimplemented_payload": "Entire trimmed payload equals not-implemented (case-insensitive).",
            "image_document_candidate": "Zero body words and title ending with image filename plus pixel dimensions; browser image-document suspicion, not a confirmed MIME type.",
            "pdf_url": "Decoded URL path ends .pdf; does not prove stored payload is PDF.",
            "pdf_magic": "Payload begins %PDF- after left whitespace removal.",
            "pdf_embed": "embed/object/iframe type contains pdf or src/data ends .pdf before query/fragment.",
            "no_recognized_html": "No html/head/body/div/p/article/script/doctype start markup; includes fragments and empty content, not a MIME classifier.",
            "markdown_like_without_html": "No recognized HTML plus markdown heading or HTTP markdown link.",
            "path_hints": PATH_RULES,
            "prompt_normalization": "Unicode NFKC, casefold, collapse whitespace; preserve punctuation; exclude blanks from overlap.",
            "style": "Literal punctuation, Unicode codepoints and English regex proxies; non-ASCII is NOT language identification.",
        },
        "quality_by_category": {}, "path_hints_by_category": {}, "prompt_by_category": {},
    }
    for category in categories:
        selected = [row for row in records if row["category"] == category]
        result["quality_by_category"][category] = {name: {"count": sum(row["flags"][name] for row in selected), "pct": round(100 * sum(row["flags"][name] for row in selected) / len(selected), 3)} for name in selected[0]["flags"]}
        result["path_hints_by_category"][category] = dict(Counter(hint for row in selected for hint in (row["path_hints"] or ["unclassified"])))
        result["prompt_by_category"][category] = {"all_rows_words": distribution([row["prompt_words"] for row in selected]), "nonblank_words": distribution([row["prompt_words"] for row in selected if not row["styles"]["missing_or_blank"]]), "characters": distribution([row["prompt_chars"] for row in selected]), "style_counts": {name: sum(row["styles"][name] for row in selected) for name in selected[0]["styles"]}}
    hosts = defaultdict(lambda: defaultdict(list))
    url_labels = defaultdict(set)
    for row in records:
        hosts[row["host"]][row["category"]].append(row)
        url_labels[row["href"]].add(row["category"])
    conflicted_urls = {url for url, labels in url_labels.items() if len(labels) > 1}
    overlaps = []
    exact_examples = []
    disjoint_examples = []
    candidate_strata = []
    for host, groups in sorted(hosts.items()):
        if not all(category in groups for category in ("top", "bottom")):
            continue
        sets = {category: {normalize(row["prompt"]) for row in groups[category]} - {""} for category in ("top", "bottom")}
        shared = sets["top"] & sets["bottom"]
        union = sets["top"] | sets["bottom"]
        matched = {category: sum(bool(normalize(row["prompt"])) and normalize(row["prompt"]) in shared for row in groups[category]) for category in ("top", "bottom")}
        eligible_pairs = sum(sum(normalize(row["prompt"]) == query for row in groups["top"]) * sum(normalize(row["prompt"]) == query for row in groups["bottom"]) for query in shared)
        different_url_queries = sum(any(top["href"] != bottom["href"] for top in groups["top"] for bottom in groups["bottom"] if normalize(top["prompt"]) == query and normalize(bottom["prompt"]) == query) for query in shared)
        for query in sorted(shared):
            pairs = [(top, bottom) for top in groups["top"] for bottom in groups["bottom"] if normalize(top["prompt"]) == query and normalize(bottom["prompt"]) == query and top["href"] != bottom["href"]]
            if pairs:
                candidate_strata.append({"host": host, "normalized_prompt": query, "different_url_pairs": len(pairs), "pairs_without_clear_failure": sum(not top["flags"]["clear_failure_union"] and not bottom["flags"]["clear_failure_union"] for top, bottom in pairs), "pairs_html_without_failure_or_sparse_body": sum(all(row["flags"]["html_markup"] and not row["flags"]["clear_failure_union"] and not row["flags"]["sparse_body_candidate"] for row in (top, bottom)) for top, bottom in pairs), "top": [example(row) for row in groups["top"] if normalize(row["prompt"]) == query], "bottom": [example(row) for row in groups["bottom"] if normalize(row["prompt"]) == query]})
                candidate_strata[-1]["pairs_excluding_conflicted_urls"] = sum(top["href"] not in conflicted_urls and bottom["href"] not in conflicted_urls for top, bottom in pairs)
                candidate_strata[-1]["pairs_html_usable_excluding_conflicted_urls"] = sum(all(row["href"] not in conflicted_urls and row["flags"]["html_markup"] and not row["flags"]["clear_failure_union"] and not row["flags"]["sparse_body_candidate"] for row in (top, bottom)) for top, bottom in pairs)
        overlaps.append({"host": host, "top_distinct_nonblank": len(sets["top"]), "bottom_distinct_nonblank": len(sets["bottom"]), "shared_distinct": len(shared), "jaccard": len(shared) / len(union) if union else None, "matched_rows": matched, "eligible_cross_category_row_pairs": eligible_pairs, "shared_queries_with_different_urls": different_url_queries})
        if shared and len(exact_examples) < 12:
            target = sorted(shared)[0]
            exact_examples.append({"host": host, "top": example(next(row for row in groups["top"] if normalize(row["prompt"]) == target)), "bottom": example(next(row for row in groups["bottom"] if normalize(row["prompt"]) == target))})
        if not shared and len(disjoint_examples) < 15:
            disjoint_examples.append({"host": host, "top": [example(row) for row in groups["top"][:2]], "bottom": [example(row) for row in groups["bottom"][:2]]})
    result["within_host_prompt_overlap"] = {"hosts_with_both_categories": len(overlaps), "hosts_with_no_shared_nonblank_prompt": sum(row["shared_distinct"] == 0 for row in overlaps), "hosts_with_shared_prompt": sum(row["shared_distinct"] > 0 for row in overlaps), "matched_rows": {category: sum(row["matched_rows"][category] for row in overlaps) for category in ("top", "bottom")}, "host_jaccard": distribution([row["jaccard"] for row in overlaps if row["jaccard"] is not None]), "per_host": overlaps}
    result["examples"] = {"quality_flags": {}, "same_normalized_prompt_pairs": exact_examples, "disjoint_prompt_host_samples": disjoint_examples}
    result["within_host_prompt_overlap"]["eligible_host_query_strata"] = sum(row["shared_distinct"] for row in overlaps)
    result["within_host_prompt_overlap"]["eligible_cross_category_row_pairs"] = sum(row["eligible_cross_category_row_pairs"] for row in overlaps)
    result["within_host_prompt_overlap"]["host_query_strata_with_different_urls"] = sum(row["shared_queries_with_different_urls"] for row in overlaps)
    result["within_host_prompt_overlap"]["matching_note"] = "Eligibility requires same recorded hostname and same normalized nonblank prompt across labels. Pair counts are Cartesian combinations, not independent observations. Different-URL strata are the minimum candidate set for comparing page features."
    result["within_host_prompt_overlap"]["different_url_candidate_strata"] = candidate_strata
    result["within_host_prompt_overlap"]["different_url_pairs"] = sum(row["different_url_pairs"] for row in candidate_strata)
    result["within_host_prompt_overlap"]["strata_without_clear_failure"] = sum(row["pairs_without_clear_failure"] > 0 for row in candidate_strata)
    result["within_host_prompt_overlap"]["strata_html_without_failure_or_sparse_body"] = sum(row["pairs_html_without_failure_or_sparse_body"] > 0 for row in candidate_strata)
    result["within_host_prompt_overlap"]["strata_only_same_url"] = sum(row["shared_distinct"] for row in overlaps) - len(candidate_strata)
    for key in ("pairs_excluding_conflicted_urls", "pairs_html_usable_excluding_conflicted_urls"):
        result["within_host_prompt_overlap"][key] = sum(row[key] for row in candidate_strata)
        result["within_host_prompt_overlap"][key.replace("pairs_", "strata_", 1)] = sum(row[key] > 0 for row in candidate_strata)
    result["format"]["pdf_url_by_representation"] = {category: dict(Counter("html" if row["flags"]["html_markup"] else "markdown_like" if row["flags"]["markdown_like_without_html"] else "other" for row in records if row["category"] == category and row["flags"]["pdf_url"])) for category in categories}
    result["manual_review"] = [
        {"host": "a1.art", "assessment": "Top 'How to create AI Art?' and bottom 'How to use an AI Art Generator?' are plausible related intents despite no exact match, but their URLs target Brazilian and India-boy art respectively. Other rows include French free-art generation, Hindi generation, textile/apparel and high-resolution requests. Host-level top/bottom comparison does not hold locale, task or page topic fixed.", "evidence": [example(row) for row in records if row["host"] == "a1.art"]},
        {"host": "respond.io", "assessment": "Top includes detailed WhatsApp vendor-selection scenarios and a Sleekflow-alternative query; bottom includes general AI customer-service and contact-collection queries, with /zh/ and /th/ page paths for English prompts. Intent and localization vary within host.", "evidence": [example(row) for row in records if row["host"] == "respond.io"]},
        {"host": "accuknox.com", "assessment": "Identical runtime-defense question pairs a CWPP vendors article with a bottom comparison URL whose scraped title is Page Not Found. This is exact-query eligible before quality filtering, but unsuitable as evidence of better writing."},
        {"host": "bryteflow.com", "assessment": "Identical SAP HANA-to-Redshift migration question pairs a focused SAP-to-Redshift page against general SAP-on-AWS fundamentals. Plausible matched intent, but topical specificity and page purpose still differ."},
        {"host": "civil-protection-humanitarian-aid.ec.europa.eu", "assessment": "Identical Syria humanitarian situation query pairs a country overview with a dated January 2025 funding announcement. Same question, different page purpose and potential temporal relevance."},
        {"host": "bouqs.com", "assessment": "Identical flower-ordering question cites the exact same homepage under both labels. No distinct-page feature contrast; resolve label context before modeling."},
    ]
    result["heuristics"]["script_blocks"] = "Presence of at least one codepoint in named Unicode blocks; counts overlap. This is not language detection: Latin French/German/Spanish are not separated from English, Han is shared across languages, and punctuation may trigger block flags."
    for flag in records[0]["flags"]:
        if flag == "html_markup":
            continue
        selected = []
        seen = set()
        for row in records:
            if row["flags"][flag] and (row["host"], row["category"]) not in seen:
                selected.append(example(row))
                seen.add((row["host"], row["category"]))
                if len(selected) == 8:
                    break
        result["examples"]["quality_flags"][flag] = selected
    result["limitations"] = ["No HTTP statuses, content types, fetch timestamps or rendered screenshots available; quality flags are conservative text heuristics with possible misses and false positives.", "Raw HTML is not cleaned markdown; regex markdown feature counting on raw HTML is invalid.", "Path hints overlap and miss localized or atypical routes; they are not verified page labels.", "Different normalized prompts can express the same intent; exact overlap is a lower bound on potentially comparable prompts.", "Same prompt alone does not establish matched exposure, citation opportunity, scrape time or same page type; labels rank within hostname.", "Prompt word/style summaries are row-weighted, multilingual tokenization is approximate, and repeated prompts/hosts make naive row-level significance tests misleading.", "No causal claim or citation probability can be inferred from balanced top/bottom sampling; all rows were cited to some degree."]
    result["limitations"].append("Language heterogeneity is directly evident in sampled French/Hindi prompts; Unicode-block counts cannot estimate language prevalence or detect Latin-script language mismatch. Manual review is purposive, not a representative estimate of semantic match rate.")
    result["implications"] = ["Separate actual HTML, extracted document text and failures before structural feature comparisons; do not treat missing HTML headings on document text as missing editorial structure.", "Use host-plus-query matching only on different-URL candidates with usable content; manually assess topical fit, page purpose and locale. The eligible subset is small and selected, so conclusions will have limited coverage.", "For broader host-controlled comparisons, adjust or stratify by query intent, language and page type and report residual confounding; host control alone does not imply matched questions.", "Treat sparse/script-rich pages as review candidates rather than failed scrapes without render evidence; do not infer poor original page quality from a later failed scrape."]
    destination = ROOT / "analysis/quality_analysis.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags_destination = ROOT / "analysis/quality_flags.parquet"
    connection.execute("CREATE TEMP TABLE quality_flags (hostname VARCHAR, href VARCHAR, category VARCHAR, prompt VARCHAR, clear_failure_union BOOLEAN, sparse_body_candidate BOOLEAN, sparse_script_shell_candidate BOOLEAN, html_markup BOOLEAN, markdown_like_without_html BOOLEAN, body_words INTEGER, path_hints VARCHAR[])")
    connection.executemany("INSERT INTO quality_flags VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [(row["host"], row["href"], row["category"], row["prompt"], row["flags"]["clear_failure_union"], row["flags"]["sparse_body_candidate"], row["flags"]["sparse_script_shell_candidate"], row["flags"]["html_markup"], row["flags"]["markdown_like_without_html"], row["body_words"], row["path_hints"]) for row in records])
    connection.execute("COPY quality_flags TO ? (FORMAT PARQUET)", [str(flags_destination)])
    result["row_flags"] = {"path": "analysis/quality_flags.parquet", "rows": len(records), "join_note": "href is copied exactly, without normalization. Records preserve duplicates: aggregate bool_or(clear_failure_union), bool_or(sparse_body_candidate), etc. by exact href before URL-level joins to avoid many-to-many expansion. category preserves citation_category. path_hints is a VARCHAR[]; empty means unclassified."}
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
