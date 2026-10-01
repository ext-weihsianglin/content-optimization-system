# LR Feature Definitions

Feature version: `lr-handcrafted-v1`. The selected model uses 35 raw features plus four fitted missing-value indicators. Values come from the individual prompt, its actual HTML snapshot, and the supplied URL; hostname identity is excluded.

## Extraction

`analyze_content.extract` removes scripts, styles, comments, hidden elements, and common boilerplate, preserving article-internal headers. It selects the largest `main`, `article`, or `role=main` container by text length, otherwise the cleaned body. This approximates visible content; it does not execute JavaScript. Tokenization uses Unicode alphanumeric runs and case folding, with a fixed small English stopword list for query coverage. It does not implement semantic similarity or robust multilingual segmentation.

## Alignment and prompt features

| Feature | Definition |
| --- | --- |
| `coverage_title` | Fraction of unique non-stopword prompt tokens present in the HTML title |
| `coverage_headings` | Same coverage against all extracted H1–H6 text combined |
| `coverage_body` | Same coverage against the extracted main text |
| `coverage_intro` | Same coverage against the first 200 extracted body tokens |
| `coverage_url_path` | Same coverage against the decoded URL path |
| `log_prompt_words` | `log1p` of prompt token count |
| `prompt_question` | English question-start regex or ASCII/full-width question mark |
| `prompt_comparison` | English best/compare/comparison/versus/vs/better/cheapest marker |
| `prompt_how_to` | Literal English “how to” phrase |

Coverage is recomputed separately for every row. An empty query-token set yields missing coverage, not zero. Blank prompts are excluded from the modeling population; the inference extractor still defines their missing values.

## Page features

| Feature(s) | Definition |
| --- | --- |
| `log_word_count`, `log_title_words` | `log1p` of extracted body/title token counts |
| `log_heading_count`, `log_h1_count` | `log1p` of all H1–H6 / H1 element counts in the focus container |
| `log_list_items`, `log_table_count` | `log1p` of list-item / table element counts in the focus container |
| `headings_per_1000_words`, `list_items_per_1000_words` | Corresponding count divided by extracted word count × 1,000; missing for empty text |
| `has_table`, `has_list` | Table / UL-or-OL presence in extracted focus |
| `has_main`, `has_article` | Main-or-role-main / article container presence in original HTML |
| `has_jsonld` | Application/LD+JSON script presence |
| `has_article_schema` | Parsed JSON-LD type matches the extractor’s Article-family types |
| `removed_text_fraction` | Fraction of raw-body tokens removed by boilerplate removal; missing for empty raw body |
| `focus_text_fraction` | Focus-container tokens divided by raw-body tokens; missing for empty raw body |
| `script_char_ratio` | Serialized script characters / original HTML characters, capped at one; missing for empty HTML |
| `path_depth` | Count of nonempty decoded URL path segments |
| `path_homepage` | Empty path or `/` |
| `path_editorial` | Existing editorial path regex (blog, articles, news, insights, resources, guides, learn, tutorials) |
| `path_commerce` | Existing commerce path regex (products, collections, shop, store, pricing, plans, packages) |
| `path_support_docs` | Existing support path regex (help, support, docs, documentation, FAQ) |
| `empty_title` | Missing or whitespace-only extracted title |
| `sparse_body` | Quality probe finds at most 30 body tokens |
| `failure_page` | Existing heuristic union: empty/unimplemented payload, blocked/error title or short body, short-body JavaScript requirement |
| `recognized_html` | Quality probe recognizes HTML markup using its fixed regex |

The quality probe uses its own broader body-text extraction, including navigation, so its token count differs from main-content extraction. Full regexes and extraction rules are versioned in `scripts/analyze_quality.py` and `scripts/analyze_content.py`; source hashes are recorded in the dataset manifest.

## Fitted transformations and interpretation

Train-only median imputation adds indicators for columns missing during fitting; all resulting columns are standardized using training means and scales. L2 logistic regression then fits coefficients. The four fitted missing indicators concern heading density, list-item density, removed-text fraction, and focus-text fraction.

Coefficient plots show signed log-odds effects per training standard deviation, including for binary columns. A binary 0→1 effect is therefore not equal to the displayed standardized coefficient. Permutation plots measure validation log-loss degradation after shuffling one raw feature; the pipeline recomputes its missing indicator. Family ablations refit train-only models at the selected C. Response plots average predictions over validation rows while varying one feature over training quantiles; binary features use both observed states. These diagnostics are descriptive, can be affected by correlated or inconsistent feature combinations, and do not estimate causal editing effects.
