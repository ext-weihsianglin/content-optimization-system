"""Exploratory, page-balanced HTML feature comparisons; no network access."""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import statistics
from urllib.parse import urldefrag

from bs4 import BeautifulSoup, Comment
import duckdb
from scipy.stats import wilcoxon


STOPWORDS = set("a an and are as at be best by can do does for from how i in is it me my of on or that the this to top what when where which who why with you your".split())
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
REMOVABLE = ("script", "style", "noscript", "template", "svg")
BOILERPLATE = ("nav", "header", "footer", "aside", "form")
FEATURES = [
    "title_words", "heading_count", "h1_count", "word_count", "raw_body_words",
    "removed_text_fraction", "focus_text_fraction", "list_count", "list_items",
    "table_count", "list_items_per_1000_words", "headings_per_1000_words",
    "has_table", "has_list", "has_main", "has_article", "has_jsonld",
    "jsonld_blocks", "valid_jsonld_blocks", "has_article_schema",
    "script_char_ratio", "query_title_coverage", "query_body_coverage",
]


def words(text):
    return TOKEN.findall(text.casefold())


def clean_text(node):
    return " ".join(node.stripped_strings)


def schema_types(value):
    found = set()
    if isinstance(value, dict):
        types = value.get("@type", [])
        types = [types] if isinstance(types, str) else types
        if isinstance(types, list):
            found.update(item for item in types if isinstance(item, str))
        for child in value.values():
            found.update(schema_types(child))
    elif isinstance(value, list):
        for child in value:
            found.update(schema_types(child))
    return found


def extract(html):
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title) if soup.title else ""
    has_main = bool(soup.find("main") or soup.find(attrs={"role": "main"}))
    has_article = bool(soup.find("article"))
    scripts = soup.find_all("script")
    script_chars = sum(len(str(node)) for node in scripts)
    jsonld = [node for node in scripts if (node.get("type") or "").lower().split(";")[0].strip() == "application/ld+json"]
    valid_jsonld = 0
    types = set()
    for node in jsonld:
        try:
            types.update(schema_types(json.loads(node.string or node.get_text())))
            valid_jsonld += 1
        except (ValueError, TypeError, RecursionError):
            pass
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for node in soup.find_all(REMOVABLE):
        node.decompose()
    body = soup.body or soup
    raw_body_text = clean_text(body)
    raw_body_words = len(words(raw_body_text))
    for node in list(body.find_all(BOILERPLATE)):
        if node.parent is not None:
            if node.name == "header" and (node.find_parent(["main", "article"]) or node.find_parent(attrs={"role": "main"})):
                continue
            node.decompose()
    for node in list(body.select('[hidden], [aria-hidden="true"]')):
        if node.parent is not None:
            node.decompose()
    cleaned_body_words = len(words(clean_text(body)))
    candidates = body.select("main, article, [role='main']")
    focus = max(candidates, key=lambda node: len(clean_text(node))) if candidates else body
    focus_source = focus.name if candidates else "body_fallback"
    text = clean_text(focus)
    word_count = len(words(text))
    headings = [clean_text(node) for node in focus.find_all(re.compile(r"^h[1-6]$"))]
    list_count = len(focus.find_all(["ul", "ol"]))
    list_items = len(focus.find_all("li"))
    table_count = len(focus.find_all("table"))
    return {
        "title": title, "headings": headings, "extracted_text": text,
        "focus_source": focus_source, "title_words": len(words(title)),
        "heading_count": len(headings), "h1_count": len(focus.find_all("h1")),
        "word_count": word_count, "raw_body_words": raw_body_words,
        "removed_text_fraction": 1 - cleaned_body_words / raw_body_words if raw_body_words else None,
        "focus_text_fraction": word_count / raw_body_words if raw_body_words else None,
        "list_count": list_count, "list_items": list_items, "table_count": table_count,
        "list_items_per_1000_words": 1000 * list_items / word_count if word_count else None,
        "headings_per_1000_words": 1000 * len(headings) / word_count if word_count else None,
        "has_table": int(table_count > 0), "has_list": int(list_count > 0),
        "has_main": int(has_main), "has_article": int(has_article),
        "has_jsonld": int(bool(jsonld)), "jsonld_blocks": len(jsonld),
        "valid_jsonld_blocks": valid_jsonld, "schema_types": sorted(types),
        "has_article_schema": int(any(kind.rsplit("/", 1)[-1] in {"Article", "NewsArticle", "BlogPosting", "TechArticle", "ScholarlyArticle", "Report"} for kind in types)),
        "script_char_ratio": min(1, script_chars / len(html)) if html else None,
    }


def coverage(prompts, text):
    text_tokens = set(words(text))
    values = []
    for prompt in prompts:
        query_tokens = set(words(prompt)) - STOPWORDS
        if query_tokens:
            values.append(len(query_tokens & text_tokens) / len(query_tokens))
    return statistics.mean(values) if values else None


def summarize(rows, minimum_words=1):
    eligible = [row for row in rows if row["citation_category"] in {"top", "bottom"} and row["word_count"] >= minimum_words]
    results = {}
    for feature in FEATURES:
        grouped = defaultdict(lambda: defaultdict(list))
        pooled = defaultdict(list)
        for row in eligible:
            value = row[feature]
            if value is not None:
                grouped[row["hostname"]][row["citation_category"]].append(float(value))
                pooled[row["citation_category"]].append(float(value))
        differences = []
        median_differences = []
        host_effects = []
        for host, labels in sorted(grouped.items()):
            if labels["top"] and labels["bottom"]:
                difference = statistics.mean(labels["top"]) - statistics.mean(labels["bottom"])
                median_difference = statistics.median(labels["top"]) - statistics.median(labels["bottom"])
                differences.append(difference)
                median_differences.append(median_difference)
                host_effects.append({"hostname": host, "top_pages": len(labels["top"]), "bottom_pages": len(labels["bottom"]), "mean_difference": difference, "median_difference": median_difference})
        result = {"pooled": {label: {"pages": len(pooled[label]), "mean": statistics.mean(pooled[label]) if pooled[label] else None, "median": statistics.median(pooled[label]) if pooled[label] else None} for label in ("top", "bottom")}}
        if pooled["top"] and pooled["bottom"]:
            result["pooled"]["median_difference_top_minus_bottom"] = statistics.median(pooled["top"]) - statistics.median(pooled["bottom"])
            result["pooled"]["mean_difference_top_minus_bottom"] = statistics.mean(pooled["top"]) - statistics.mean(pooled["bottom"])
        positive = sum(value > 1e-12 for value in differences)
        negative = sum(value < -1e-12 for value in differences)
        result["within_host"] = {
            "paired_hosts": len(differences), "positive_hosts": positive, "negative_hosts": negative,
            "tied_hosts": len(differences) - positive - negative,
            "median_mean_difference": statistics.median(differences) if differences else None,
            "median_median_difference": statistics.median(median_differences) if median_differences else None,
            "mean_mean_difference": statistics.mean(differences) if differences else None,
            "exploratory_wilcoxon_p": float(wilcoxon(differences, method="approx").pvalue) if positive + negative >= 10 else None,
            "host_effects": host_effects,
        }
        pooled_difference = result["pooled"].get("mean_difference_top_minus_bottom")
        paired_difference = result["within_host"]["median_mean_difference"]
        result["pooled_vs_paired_mean_direction_reversal"] = pooled_difference * paired_difference < 0 if pooled_difference is not None and paired_difference is not None else None
        host_balanced_difference = result["within_host"]["mean_mean_difference"]
        result["pooled_vs_host_balanced_mean_direction_reversal"] = pooled_difference * host_balanced_difference < 0 if pooled_difference is not None and host_balanced_difference is not None else None
        result["host_weighting_mean_shift"] = host_balanced_difference - pooled_difference if pooled_difference is not None and host_balanced_difference is not None else None
        results[feature] = result
    tested = sorted((result["within_host"]["exploratory_wilcoxon_p"], feature) for feature, result in results.items() if result["within_host"]["exploratory_wilcoxon_p"] is not None)
    adjusted = 1.0
    for rank in range(len(tested), 0, -1):
        pvalue, feature = tested[rank - 1]
        adjusted = min(adjusted, pvalue * len(tested) / rank)
        results[feature]["within_host"]["exploratory_bh_q"] = adjusted
    return {"minimum_extracted_words": minimum_words, "eligible_pages": len(eligible), "features": results}


def extract_page(item):
    (host, url), page = item
    row = extract(page["html"])
    row.update({"hostname": host, "href": url, "citation_category": next(iter(page["labels"])) if len(page["labels"]) == 1 else "conflicting",
                "labels": sorted(page["labels"], key=str), "source_rows": page["rows"], "html_variants": len(page["hashes"]),
                "html_sha256": page["hash"], "prompt_count": len(page["prompts"]), "prompts": sorted(page["prompts"]),
                "html_chars": len(page["html"]), "query_title_coverage": coverage(page["prompts"], row["title"]),
                "query_body_coverage": coverage(page["prompts"], row["extracted_text"])})
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/raw/*.parquet")
    parser.add_argument("--output-dir", default="analysis")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    source = connection.execute("SELECT prompt, citation_category, href, hostname, html_content FROM read_parquet(?)", [args.input]).fetchall()
    input_rows = len(source)
    pages = {}
    for prompt, label, href, hostname, html in source:
        html = html or ""
        digest = hashlib.sha256(html.encode()).hexdigest()
        host = (hostname or "").strip().lower()
        url = urldefrag((href or "").strip())[0]
        key = (host, url or "missing-url:" + digest)
        if key not in pages:
            pages[key] = {"html": html, "hash": digest, "hashes": set(), "prompts": set(), "labels": set(), "rows": 0}
        page = pages[key]
        page["hashes"].add(digest)
        page["prompts"].add((prompt or "").strip())
        page["labels"].add(label)
        page["rows"] += 1
        if (len(html), digest) > (len(page["html"]), page["hash"]):
            page["html"], page["hash"] = html, digest
    del source
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, row in enumerate(executor.map(extract_page, sorted(pages.items()), chunksize=8), 1):
            rows.append(row)
            if index % 500 == 0:
                print(f"Parsed {index}/{len(pages)} pages", flush=True)
    temporary = output / ".content_features.jsonl"
    with temporary.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    parquet_path = str(output / "content_features.parquet").replace("'", "''")
    connection.execute(f"COPY (SELECT * FROM read_json_auto(?, format='newline_delimited', sample_size=-1)) TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD)", [str(temporary)])
    temporary.unlink(missing_ok=True)
    report = {
        "method": {
            "unit": "One equally weighted page per normalized hostname and URL with fragment removed; query strings retained. Missing URLs use HTML hash.",
            "repeated_pages": "Repeated rows collapse to one page. Distinct prompts contribute equally to average query coverage; static features count once. Conflicting-label pages are excluded from comparisons.",
            "html_variants": "Choose longest HTML snapshot, SHA256 tie-break; never weight snapshots by repetition. Variants may differ by scrape quality or time.",
            "extraction": "Remove scripts/styles/noscript/template/svg and comments; raw_body_words retains navigation and boilerplate. Then remove nav/header/footer/aside/form and explicitly hidden nodes, preserving headers inside main/article/role=main. Select largest main/article/role=main by text characters, otherwise cleaned body. Other removed elements may still contain meaningful content.",
            "ratios": "script_char_ratio uses serialized script length / original HTML characters (capped at 1); removed_text_fraction is removed body tokens / raw body tokens; focus_text_fraction is selected text / raw body tokens. Raw body is visible-text approximation, not raw HTML tokens.",
            "coverage": "Unique Unicode alphanumeric tokens, casefolded, small fixed English stopword list removed from queries; no stemming, synonyms or semantic matching. Average over distinct nonempty-token prompts per page. Coverage ranges 0–1.",
            "comparison": "Pooled page means/medians are descriptive. Primary comparison computes top-minus-bottom page means within each paired host, then the median across equally weighted hosts. Also reports median of within-host median differences, positive/negative/tied host counts and per-host effects. Binary differences are proportions (multiply by 100 for percentage points).",
            "confounding_diagnostics": "pooled_vs_paired_mean_direction_reversal compares pooled mean difference with MEDIAN host mean difference; this can reflect skew/heterogeneity rather than host confounding. pooled_vs_host_balanced_mean_direction_reversal instead compares pooled mean difference with MEAN host mean difference; host_weighting_mean_shift is the latter minus pooled. Even this changes eligible host composition when some hosts lack a label, so it is descriptive, not proof of confounding.",
            "inference": "Two-sided approximate Wilcoxon signed-rank on host mean differences when >=10 nonzero hosts. BH adjustment within each feature family/run. Exploratory only: correlated features, multiple sensitivity runs, unmodeled confounding, symmetry/independence assumptions and selection invalidate causal interpretations.",
            "stopwords": sorted(STOPWORDS),
            "feature_definitions": {
                "title_words": "Unicode alphanumeric token count in HTML title, before body cleaning.",
                "heading_count / h1_count": "All h1–h6 elements / h1 elements inside selected cleaned focus; headings stores their text.",
                "word_count": "Unicode alphanumeric token count in extracted_text; reader-text approximation, not HTML size.",
                "raw_body_words": "Body text tokens after non-content tag removal but before boilerplate removal and focus selection.",
                "list_count / list_items / table_count": "Counts of ul+ol / li / table elements inside selected cleaned focus; nested elements count individually.",
                "list_items_per_1000_words / headings_per_1000_words": "Selected focus counts divided by word_count and multiplied by 1000; null if zero words.",
                "has_table / has_list": "Binary presence of a table / ul or ol inside selected cleaned focus.",
                "has_main / has_article": "Binary presence anywhere in original HTML; main includes role=main.",
                "has_jsonld / jsonld_blocks / valid_jsonld_blocks": "Original script tags with application/ld+json MIME type: presence / count / JSON-decodable count. JSON-decodable does not mean valid schema markup.",
                "has_article_schema": "Parsed recursive @type matches Article, NewsArticle, BlogPosting, TechArticle, ScholarlyArticle or Report; URL types use last slash segment.",
                "html_chars": "Original HTML character length; metadata only, excluded from effect comparisons and never interpreted as reader text.",
            },
        },
        "feature_extraction_accounting": {
            "input_rows": input_rows, "page_records": len(rows), "collapsed_repeat_rows": input_rows - len(rows),
            "conflicting_label_pages": sum(row["citation_category"] == "conflicting" for row in rows),
            "multi_snapshot_pages": sum(row["html_variants"] > 1 for row in rows),
            "zero_word_pages": sum(row["word_count"] == 0 for row in rows),
            "focus_sources": dict(Counter(row["focus_source"] for row in rows)),
            "selected_html_hashes_shared_across_urls": sum(count > 1 for count in Counter(row["html_sha256"] for row in rows).values()),
        },
        "primary": summarize(rows),
        "sensitivity_at_least_100_words": summarize(rows, minimum_words=100),
        "limitations": [
            "Top/bottom are within-host ranks among already cited pages, not citation probabilities or uncited controls; no causal lift estimate is possible.",
            "Within-host pairing controls host identity, not page topic, query intent, page type, freshness, authority, links or scrape quality.",
            "Separate quality audit supplied by the collaborator: 920/970 hosts have no normalized shared prompt; only 42 matched host/query strata have different URLs. Host pairing therefore generally does not compare pages for the same query. These counts are external audit context, not recomputed here.",
            "Static HTML can omit JavaScript-rendered text; bot walls, error pages and navigation may survive heuristics. Semantic main/article markup does not guarantee main content.",
            "URL variants and identical HTML across distinct URLs remain separate pages; no canonical-link or near-duplicate resolution. Shared templates and organizations may create dependence across hosts.",
            "Prompts include French and Hindi (notably in the first host per the separate audit). English stopwords, no stemming and Unicode alphanumeric tokenization are not language-neutral; Hindi combining marks can split tokens. Cross-language coverage is especially unreliable. Lexical coverage is not relevance or answer completeness.",
            "No minimum pages per host beyond one per label; small host samples yield noisy contrasts. No schema/cardinality audit is attempted.",
        ],
    }
    with (output / "content_analysis.json").open("w") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False, allow_nan=False)
    print(json.dumps(report["feature_extraction_accounting"], indent=2))
    for feature in FEATURES:
        stats = report["primary"]["features"][feature]["within_host"]
        print(feature, json.dumps({key: value for key, value in stats.items() if key != "host_effects"}))


if __name__ == "__main__":
    main()
