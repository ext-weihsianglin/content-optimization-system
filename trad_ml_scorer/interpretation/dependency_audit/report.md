# Feature importance for fixed-prompt HTML editing

**Model:** frozen v5, retained by v6. No refit, feature selection or test-set evaluation. This companion reinterprets the model; original experiment reports remain frozen.

## The right quantity is the change for the same prompt

For a fixed query and URL, prompt-only terms act as a query-specific intercept. They cancel in a before/after **log-odds** comparison. Keep them in the model: they still set the baseline probability and therefore the probability response to an edit. Prompt–document interactions remain variable and belong in the editing analysis.

`logit P = intercept + prompt contribution + doc contribution + promptXdoc contribution`

`Δlogit = Σ β_j [z_j(edited HTML, fixed prompt) − z_j(original HTML, fixed prompt)]`

Here `z` includes the fitted imputer, missing indicators and training scaler. Pure prompt and URL terms have exactly zero delta. Probability change is `sigmoid(original logit + Δlogit) − sigmoid(original logit)`; feature contributions are additive in log odds, not probability points.

The modeled probability is the sampled within-host high class **among already-cited pages**, not the probability of being cited at all.

## 1. Primary view: coherent document edits

We use the first 40 hash-sorted validation HTML snapshots, selected without label or score-gain filtering. The same prompt and URL are supplied before and after every edit; the aggregate combines different fixed-query pairs, not one shared query. All features are recomputed from the edited HTML. Every applicable edit preserves the visible body word multiset; edits insert no new factual assertions or query stuffing. This does not guarantee unchanged semantics or better editorial quality—moving a paragraph can disrupt context, and the existing H1 may make a poor title.

![Fixed-prompt edit effects](edit_effects.svg)

| Edit | Applicable / sampled | Hosts | Mean Δ probability | Median Δ probability | Observed range |
|---|---:|---:|---:|---:|---:|
| Title ← existing H1 | 26 / 40 | 22 | -0.93 pp | -0.03 pp | [-7.57, +6.72] pp |
| Move relevant paragraph earlier | 21 / 40 | 20 | +0.11 pp | +0.00 pp | [-1.79, +2.33] pp |
| Split a long paragraph | 4 / 40 | 4 | +0.02 pp | -0.01 pp | [-0.06, +0.15] pp |

Non-applicable edits are recorded, not counted as zero effects. Confidence intervals resample host clusters (1,000 replicates) when at least five hosts are available; they are descriptive for this small development sample and frozen model. Maximum absolute serialization-only probability change was **0.000000 pp**; each record also stores edit-versus-serialization change.

## 2. Exact explanation of one edit

First applicable edit with a changed model contribution: **Title ← existing H1**. This example was not chosen for maximum gain.

Prompt: Best free PDF editor

Record: `000cb33fe83f9e6f903c2221fc7debe9e475ae5fc2baa1a975750b344509ecbe`. Predicted score: **0.7779 → 0.7054**; Δlogit **-0.38034**.

![Exact paired contribution](local_contrast.svg)

All changed transformed-feature contributions, including missingness effects, are stored in analysis.json and verified to sum to the model logit difference. Fixed prompt and URL contributions are checked to be zero for every edit.

## 3. Replotted global importance by input dependency

Three panels separate prompt, doc, and promptXdoc dependencies. Document includes URL, content, metadata and parser diagnostics. Dependency is distinct from editability: path_homepage is doc; path_query_precision is promptXdoc, but both stay fixed during HTML-only edits. Supported path-match features also use body support and may change. Bracket annotations identify fixed-URL and diagnostic signals; diagnostics are not optimization targets.

![Separated coefficients](separated_coefficients.svg)

![Document and interaction predictive importance](document_permutation.svg)

**This permutation plot is still across-query predictive importance**, copied from the original validation audit and filtered by dependency. Hiding prompt-only bars does not make it conditional importance, and it does not estimate an edit’s effect. A standardized coefficient describes a fitted slope; a permutation drop describes predictive reliance. Neither is a causal citation recommendation. A negative coefficient on a coverage feature can arise while related coverage inputs carry positive coefficients; it is not a recommendation to remove relevant text. Recompute the full feature vector for a coherent edit instead.

## 4. Why we do not claim reliable within-query ranking importance

Validation has only **1 same-prompt/same-host group with both labels (2 rows)**. It has 12 repeated groups total (25 rows). Exact-query groups across hosts contain only 1 mixed-label group too. A within-query ranking AUC or label-based conditional permutation estimate would be far too fragile here. We report the support count instead of a misleading near-zero importance estimate.

## Better computation and interpretation going forward

| Question | Preferred computation / plot | Interpretation and limits |
|---|---|---|
| What can change this page’s score for this query? | Real HTML edit → reparse → recompute all features; paired Δprobability with exact Δlogit attribution. | Best editing-oriented view. Keep query, URL and factual content fixed; inspect interactions and all side effects. Score increase is not demonstrated citation uplift. |
| Which signals distinguish documents for the same query? | Within-query (preferably within-host) ranking metrics and grouped conditional permutation on a substantially larger matched dataset. | Keep pure-query features constant. Report effective groups/rows; avoid estimates driven by one pair. |
| Which correlated feature families matter? | Joint family permutation on appropriately matched donors, or predeclared family ablation refits. | Shuffling one correlated feature may understate reliance; unrelated donors can create impossible feature combinations. Fit/refit only development data. |
| Is an effect stable across pages? | Paired edit distributions, applicability counts, host-bootstrap intervals and per-query slices. | Do not show only mean gain or cherry-pick winners. Include negative edits, failed cases, serialization controls and manipulation probes. |
| Should we use SHAP, PDP or ALE? | For LR edits, exact paired logit contributions already solve the attribution problem. If adding SHAP, use a query-conditioned background and correlated groups; use feasible fixed-query ICE/ALE ranges only. | Generic backgrounds can assign query/context effects to apparent editing levers. One-feature interventions can violate feature dependencies. None supplies causal evidence. |
| Will an edit increase real citations? | Grounded editorial checks followed by prospective same-query evaluation with engine/time/exposure controls. | Existing observational relative labels and score gradients cannot establish this. Retain factuality and adversarial checks before optimization. |

## Feature dependency inventory

The full audit below supersedes the dependency labels in the original fixed_prompt companion, whose five groups mixed dependency with intervention constraints. Original analysis.json and verification.json remain unchanged as provenance of that run. Numeric coefficients, permutations and edit outcomes are reused unchanged. Missing indicators inherit their source dependency. Scope: all 142 retention-based v2–v6 candidates; v1 remains a separate frozen extractor.

| Group | Raw feature count | Features |
|---|---:|---|
| prompt | 4 | log_prompt_words, prompt_question, prompt_comparison, prompt_how_to |
| doc | 41 | path_depth, path_homepage, path_editorial, path_commerce, path_support_docs, log_word_count, log_title_words, log_heading_count, log_h1_count, log_list_items, log_table_count, log_paragraph_count, log_code_count, log_ordered_steps, headings_per_1000_words, list_items_per_1000_words, has_table, has_list, has_jsonld, has_article_schema, log_source_script_count, empty_title, retained_text_fraction, needs_review, possible_error_response, sparse_body, format_html, paragraph_log_median_words, paragraph_log_p90_words, short_paragraph_fraction, unique_word_fraction, numeric_word_fraction, question_heading_fraction, duplicate_heading_fraction, log_link_count, links_per_1000_words, heading_word_fraction, paragraph_word_fraction, list_item_word_fraction, table_word_fraction, code_word_fraction |
| promptXdoc | 51 | coverage_title, coverage_headings, coverage_body, coverage_intro, coverage_h1, coverage_table_headers, best_section_coverage, mean_section_coverage, matching_section_fraction, best_section_heading_coverage, best_section_position, comparison_x_table_header_coverage, how_to_x_ordered_steps, body_query_precision, body_query_dice, body_query_saturated_tf, body_query_bigram, title_query_precision, title_query_dice, title_query_saturated_tf, title_query_bigram, description_query_precision, description_query_dice, description_query_saturated_tf, description_query_bigram, path_query_precision, path_query_dice, path_query_saturated_tf, path_query_bigram, headings_query_precision, headings_query_dice, headings_query_saturated_tf, headings_query_bigram, section_coverage_fraction_0_5, section_coverage_fraction_0_8, section_coverage_fraction_1_0, section_coverage_std, top_three_section_coverage, best_section_log_words, first_query_match_position, query_match_density, answer_best_sentence_coverage, answer_top3_sentence_coverage, answer_relevant_sentence_fraction, answer_log_relevant_sentences, answer_best_sentence_precision, answer_relevant_median_words, answer_window_10_coverage, answer_window_25_coverage, answer_window_50_coverage, answer_relevant_union_coverage |

## Every candidate: dependency and HTML-edit role

| Feature | Dependency | HTML-edit role | Selected v5 | Definition / dependency rationale | Source |
|---|---|---|---|---|---|
| `log_prompt_words` | prompt | prompt fixed | yes | Computed solely from the user prompt. | retention_features.py |
| `prompt_question` | prompt | prompt fixed | yes | Computed solely from the user prompt. | retention_features.py |
| `prompt_comparison` | prompt | prompt fixed | yes | Computed solely from the user prompt. | retention_features.py |
| `prompt_how_to` | prompt | prompt fixed | yes | Computed solely from the user prompt. | retention_features.py |
| `path_depth` | doc | URL fixed | yes | Computed solely from the document URL. | retention_features.py |
| `path_homepage` | doc | URL fixed | yes | Computed solely from the document URL. | retention_features.py |
| `path_editorial` | doc | URL fixed | yes | Computed solely from the document URL. | retention_features.py |
| `path_commerce` | doc | URL fixed | yes | Computed solely from the document URL. | retention_features.py |
| `path_support_docs` | doc | URL fixed | yes | Computed solely from the document URL. | retention_features.py |
| `coverage_title` | promptXdoc | may vary with HTML | yes | Matches prompt tokens against document text or metadata. | retention_features.py |
| `coverage_headings` | promptXdoc | may vary with HTML | yes | Matches prompt tokens against document text or metadata. | retention_features.py |
| `coverage_body` | promptXdoc | may vary with HTML | yes | Matches prompt tokens against document text or metadata. | retention_features.py |
| `coverage_intro` | promptXdoc | may vary with HTML | yes | Matches prompt tokens against document text or metadata. | retention_features.py |
| `log_word_count` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_title_words` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_heading_count` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_h1_count` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_list_items` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_table_count` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_paragraph_count` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_code_count` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `log_ordered_steps` | doc | may vary with HTML | yes | Counts retained document content, without reading the prompt. | retention_features.py |
| `headings_per_1000_words` | doc | may vary with HTML | yes | Measures document structure, without reading the prompt. | retention_features.py |
| `list_items_per_1000_words` | doc | may vary with HTML | yes | Measures document structure, without reading the prompt. | retention_features.py |
| `has_table` | doc | may vary with HTML | yes | Measures document structure, without reading the prompt. | retention_features.py |
| `has_list` | doc | may vary with HTML | yes | Measures document structure, without reading the prompt. | retention_features.py |
| `has_jsonld` | doc | may vary with HTML | yes | Reads document source metadata, without reading the prompt. | retention_features.py |
| `has_article_schema` | doc | may vary with HTML | yes | Reads document source metadata, without reading the prompt. | retention_features.py |
| `log_source_script_count` | doc | diagnostic; not an edit target | yes | Reads document source metadata, without reading the prompt. | retention_features.py |
| `empty_title` | doc | may vary with HTML | yes | Reads document source metadata, without reading the prompt. | retention_features.py |
| `retained_text_fraction` | doc | diagnostic; not an edit target | yes | Describes source format or parser retention/quality, without reading the prompt. | retention_features.py |
| `needs_review` | doc | diagnostic; not an edit target | yes | Describes source format or parser retention/quality, without reading the prompt. | retention_features.py |
| `possible_error_response` | doc | diagnostic; not an edit target | yes | Describes source format or parser retention/quality, without reading the prompt. | retention_features.py |
| `sparse_body` | doc | diagnostic; not an edit target | yes | Describes source format or parser retention/quality, without reading the prompt. | retention_features.py |
| `format_html` | doc | diagnostic; not an edit target | yes | Describes source format or parser retention/quality, without reading the prompt. | retention_features.py |
| `coverage_h1` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `coverage_table_headers` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `best_section_coverage` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `mean_section_coverage` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `matching_section_fraction` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `best_section_heading_coverage` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `best_section_position` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `comparison_x_table_header_coverage` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `how_to_x_ordered_steps` | promptXdoc | may vary with HTML | yes | Uses prompt matching, query-selected sections, or prompt intent × document structure. | retention_features.py |
| `body_query_precision` | promptXdoc | may vary with HTML | yes | How much of the distinct body vocabulary belongs to the question? | frontier_features.py |
| `body_query_dice` | promptXdoc | may vary with HTML | yes | How similar are the question and body word sets, accounting for both lengths? | frontier_features.py |
| `body_query_saturated_tf` | promptXdoc | may vary with HTML | yes | How often do question words appear in body, with diminishing credit for repeats? | frontier_features.py |
| `body_query_bigram` | promptXdoc | may vary with HTML | yes | What fraction of adjacent question-word pairs appear together in body? | frontier_features.py |
| `title_query_precision` | promptXdoc | may vary with HTML | yes | How much of the distinct title vocabulary belongs to the question? | frontier_features.py |
| `title_query_dice` | promptXdoc | may vary with HTML | yes | How similar are the question and title word sets, accounting for both lengths? | frontier_features.py |
| `title_query_saturated_tf` | promptXdoc | may vary with HTML | yes | How often do question words appear in title, with diminishing credit for repeats? | frontier_features.py |
| `title_query_bigram` | promptXdoc | may vary with HTML | yes | What fraction of adjacent question-word pairs appear together in title? | frontier_features.py |
| `description_query_precision` | promptXdoc | may vary with HTML | yes | How much of the distinct description vocabulary belongs to the question? | frontier_features.py |
| `description_query_dice` | promptXdoc | may vary with HTML | yes | How similar are the question and description word sets, accounting for both lengths? | frontier_features.py |
| `description_query_saturated_tf` | promptXdoc | may vary with HTML | yes | How often do question words appear in description, with diminishing credit for repeats? | frontier_features.py |
| `description_query_bigram` | promptXdoc | may vary with HTML | yes | What fraction of adjacent question-word pairs appear together in description? | frontier_features.py |
| `path_query_precision` | promptXdoc | URL fixed | yes | How much of the distinct path vocabulary belongs to the question? | frontier_features.py |
| `path_query_dice` | promptXdoc | URL fixed | yes | How similar are the question and path word sets, accounting for both lengths? | frontier_features.py |
| `path_query_saturated_tf` | promptXdoc | URL fixed | yes | How often do question words appear in path, with diminishing credit for repeats? | frontier_features.py |
| `path_query_bigram` | promptXdoc | URL fixed | yes | What fraction of adjacent question-word pairs appear together in path? | frontier_features.py |
| `headings_query_precision` | promptXdoc | may vary with HTML | yes | How much of the distinct headings vocabulary belongs to the question? | frontier_features.py |
| `headings_query_dice` | promptXdoc | may vary with HTML | yes | How similar are the question and headings word sets, accounting for both lengths? | frontier_features.py |
| `headings_query_saturated_tf` | promptXdoc | may vary with HTML | yes | How often do question words appear in headings, with diminishing credit for repeats? | frontier_features.py |
| `headings_query_bigram` | promptXdoc | may vary with HTML | yes | What fraction of adjacent question-word pairs appear together in headings? | frontier_features.py |
| `section_coverage_fraction_0_5` | promptXdoc | may vary with HTML | yes | What fraction of sections cover at least 50% of question words? | frontier_features.py |
| `section_coverage_fraction_0_8` | promptXdoc | may vary with HTML | yes | What fraction of sections cover at least 80% of question words? | frontier_features.py |
| `section_coverage_fraction_1_0` | promptXdoc | may vary with HTML | yes | What fraction of sections cover at least 100% of question words? | frontier_features.py |
| `section_coverage_std` | promptXdoc | may vary with HTML | yes | Is question coverage spread evenly across sections or concentrated in a few? | frontier_features.py |
| `top_three_section_coverage` | promptXdoc | may vary with HTML | yes | How well do the three best sections cover the question? | frontier_features.py |
| `best_section_log_words` | promptXdoc | may vary with HTML | yes | How long is the section that best matches the question? The section is selected by prompt coverage. | frontier_features.py |
| `first_query_match_position` | promptXdoc | may vary with HTML | yes | How far into the page is the first question word? | frontier_features.py |
| `query_match_density` | promptXdoc | may vary with HTML | yes | What fraction of page words match the question? | frontier_features.py |
| `paragraph_log_median_words` | doc | may vary with HTML | yes | How long is a typical paragraph? | frontier_features.py |
| `paragraph_log_p90_words` | doc | may vary with HTML | yes | How long are the longer paragraphs? | frontier_features.py |
| `short_paragraph_fraction` | doc | may vary with HTML | yes | How many paragraphs are short, readable chunks of 10 to 60 words? | frontier_features.py |
| `unique_word_fraction` | doc | may vary with HTML | yes | How much vocabulary variety does the page have? This also depends on length. | frontier_features.py |
| `numeric_word_fraction` | doc | may vary with HTML | yes | How often does the page include numbers? | frontier_features.py |
| `question_heading_fraction` | doc | may vary with HTML | yes | How many headings are written as questions? | frontier_features.py |
| `duplicate_heading_fraction` | doc | may vary with HTML | yes | How often are headings repeated? | frontier_features.py |
| `log_link_count` | doc | may vary with HTML | yes | How many links appear in retained blocks? | frontier_features.py |
| `links_per_1000_words` | doc | may vary with HTML | yes | How link-heavy is the page relative to its length? | frontier_features.py |
| `heading_word_fraction` | doc | may vary with HTML | yes | How much retained text is inside heading blocks? | frontier_features.py |
| `paragraph_word_fraction` | doc | may vary with HTML | yes | How much retained text is inside paragraph blocks? | frontier_features.py |
| `list_item_word_fraction` | doc | may vary with HTML | yes | How much retained text is inside list item blocks? | frontier_features.py |
| `table_word_fraction` | doc | may vary with HTML | yes | How much retained text is inside table blocks? | frontier_features.py |
| `code_word_fraction` | doc | may vary with HTML | yes | How much retained text is inside code blocks? | frontier_features.py |
| `answer_best_sentence_coverage` | promptXdoc | may vary with HTML | yes | How much of the question appears together in one 6–80-word sentence? | evidence_features.py |
| `answer_top3_sentence_coverage` | promptXdoc | may vary with HTML | yes | How much question coverage do the three best distinct sentences provide? | evidence_features.py |
| `answer_relevant_sentence_fraction` | promptXdoc | may vary with HTML | yes | What fraction of distinct sentences cover at least half the meaningful question words? | evidence_features.py |
| `answer_log_relevant_sentences` | promptXdoc | may vary with HTML | yes | How many distinct question-relevant sentences are available? Large counts are squeezed. | evidence_features.py |
| `answer_best_sentence_precision` | promptXdoc | may vary with HTML | yes | How focused is the most question-dense sentence? | evidence_features.py |
| `answer_relevant_median_words` | promptXdoc | may vary with HTML | yes | How long is a typical relevant sentence? | evidence_features.py |
| `answer_window_10_coverage` | promptXdoc | may vary with HTML | yes | How much of the question occurs within a 10-word prose window? | evidence_features.py |
| `answer_window_25_coverage` | promptXdoc | may vary with HTML | yes | How much of the question occurs within a 25-word prose window? | evidence_features.py |
| `answer_window_50_coverage` | promptXdoc | may vary with HTML | yes | How much of the question occurs within a 50-word prose window? | evidence_features.py |
| `answer_relevant_union_coverage` | promptXdoc | may vary with HTML | yes | Together, how much of the question do relevant distinct sentences cover? | evidence_features.py |
| `evidence_number_fraction` | promptXdoc | may vary with HTML | no | What fraction of relevant sentences contain a number cue? This does not verify truth. Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_number_coverage` | promptXdoc | may vary with HTML | no | How well does the best relevant sentence with a number cue cover the question? Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_unit_fraction` | promptXdoc | may vary with HTML | no | What fraction of relevant sentences contain a unit cue? This does not verify truth. Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_unit_coverage` | promptXdoc | may vary with HTML | no | How well does the best relevant sentence with a unit cue cover the question? Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_definition_fraction` | promptXdoc | may vary with HTML | no | What fraction of relevant sentences contain a definition cue? This does not verify truth. Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_definition_coverage` | promptXdoc | may vary with HTML | no | How well does the best relevant sentence with a definition cue cover the question? Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_linked_fraction` | promptXdoc | may vary with HTML | no | How often are relevant sentences inside a block with a link? A link need not be a trustworthy citation. Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_numeric_intent_alignment` | promptXdoc | may vary with HTML | no | For a numeric question, does a relevant sentence contain a number? Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `evidence_definition_intent_alignment` | promptXdoc | may vary with HTML | no | For a definition or explanation question, does relevant prose use an explanation cue? Relevant sentences are selected using the prompt, so this is a joint feature. | evidence_features.py |
| `table_best_value_row_coverage` | promptXdoc | may vary with HTML | no | How well does one table data row cover the question, excluding header cells? | evidence_features.py |
| `table_top3_value_row_coverage` | promptXdoc | may vary with HTML | no | How well do the three best distinct table data rows match? | evidence_features.py |
| `table_relevant_row_fraction` | promptXdoc | may vary with HTML | no | What fraction of distinct table data rows cover half the question? | evidence_features.py |
| `table_numeric_row_coverage` | promptXdoc | may vary with HTML | no | How well does a table data row containing numbers match the question? | evidence_features.py |
| `table_header_best_coverage` | promptXdoc | may vary with HTML | no | What is the best question match within the headers of one table? | evidence_features.py |
| `table_numeric_intent_alignment` | promptXdoc | may vary with HTML | no | For numeric questions, how relevant is the best numeric table row? | evidence_features.py |
| `steps_best_coverage` | promptXdoc | may vary with HTML | no | How well does one distinct numbered step match the question? | evidence_features.py |
| `steps_relevant_fraction` | promptXdoc | may vary with HTML | no | What fraction of distinct numbered steps cover half the question? | evidence_features.py |
| `steps_howto_alignment` | promptXdoc | may vary with HTML | no | For how-to questions, is there a matching numbered step? | evidence_features.py |
| `supported_coverage_title` | promptXdoc | may vary with HTML | no | coverage_title multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_title_query_precision` | promptXdoc | may vary with HTML | no | title_query_precision multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_title_query_dice` | promptXdoc | may vary with HTML | no | title_query_dice multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_title_query_saturated_tf` | promptXdoc | may vary with HTML | no | title_query_saturated_tf multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_title_query_bigram` | promptXdoc | may vary with HTML | no | title_query_bigram multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_path_query_precision` | promptXdoc | may vary with HTML | no | path_query_precision multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_path_query_dice` | promptXdoc | may vary with HTML | no | path_query_dice multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_path_query_saturated_tf` | promptXdoc | may vary with HTML | no | path_query_saturated_tf multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_path_query_bigram` | promptXdoc | may vary with HTML | no | path_query_bigram multiplied by best answer-sentence coverage: metadata gets lexical credit only when prose also matches. Body support may change even when the URL stays fixed. | control_features.py |
| `long_window_10_best` | promptXdoc | may vary with HTML | no | Best question coverage inside a 10-word window in prose segments longer than 80 tokens. | control_features.py |
| `long_window_10_mean` | promptXdoc | may vary with HTML | no | Average best 10-word question coverage across distinct long prose segments; exact repetition receives no extra count. | control_features.py |
| `long_window_25_best` | promptXdoc | may vary with HTML | no | Best question coverage inside a 25-word window in prose segments longer than 80 tokens. | control_features.py |
| `long_window_25_mean` | promptXdoc | may vary with HTML | no | Average best 25-word question coverage across distinct long prose segments; exact repetition receives no extra count. | control_features.py |
| `long_window_50_best` | promptXdoc | may vary with HTML | no | Best question coverage inside a 50-word window in prose segments longer than 80 tokens. | control_features.py |
| `long_window_50_mean` | promptXdoc | may vary with HTML | no | Average best 50-word question coverage across distinct long prose segments; exact repetition receives no extra count. | control_features.py |
| `normalized_title_coverage` | promptXdoc | may vary with HTML | no | Question-word coverage in title after fixed plural, spelling, unit and number normalization. | control_features.py |
| `normalized_title_gain` | promptXdoc | may vary with HTML | no | Change in title coverage from lexical normalization; may be negative when normalization changes token sets. | control_features.py |
| `normalized_path_coverage` | promptXdoc | URL fixed | no | Question-word coverage in path after fixed plural, spelling, unit and number normalization. | control_features.py |
| `normalized_path_gain` | promptXdoc | URL fixed | no | Change in path coverage from lexical normalization; may be negative when normalization changes token sets. | control_features.py |
| `normalized_body_coverage` | promptXdoc | may vary with HTML | no | Question-word coverage in body after fixed plural, spelling, unit and number normalization. | control_features.py |
| `normalized_body_gain` | promptXdoc | may vary with HTML | no | Change in body coverage from lexical normalization; may be negative when normalization changes token sets. | control_features.py |
| `normalized_prose_window_10` | promptXdoc | may vary with HTML | no | Best 10-word prose coverage after normalization, using the same 6–80-token sentence eligibility as v5. | control_features.py |
| `normalized_prose_window_25` | promptXdoc | may vary with HTML | no | Best 25-word prose coverage after normalization, using the same 6–80-token sentence eligibility as v5. | control_features.py |
| `normalized_number_coverage` | promptXdoc | may vary with HTML | no | Do the explicit numbers in the question appear in the body after numeric-format normalization? Units are not converted. | control_features.py |
| `supported_normalized_title_coverage` | promptXdoc | may vary with HTML | no | normalized_title_coverage multiplied by prose support, keeping combined metadata corroboration intact. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_normalized_title_gain` | promptXdoc | may vary with HTML | no | normalized_title_gain multiplied by prose support, keeping combined metadata corroboration intact. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_normalized_path_coverage` | promptXdoc | may vary with HTML | no | normalized_path_coverage multiplied by prose support, keeping combined metadata corroboration intact. Body support may change even when the URL stays fixed. | control_features.py |
| `supported_normalized_path_gain` | promptXdoc | may vary with HTML | no | normalized_path_gain multiplied by prose support, keeping combined metadata corroboration intact. Body support may change even when the URL stays fixed. | control_features.py |

## Reproduction

```sh
uv run python -m trad_ml_scorer.analyze_fixed_prompt --input-dir data/raw
uv run python -m trad_ml_scorer.build_fixed_prompt_report
```

The analysis command refuses to overwrite frozen results. The plotting command writes corrected visuals to interpretation/dependency_audit from the original fixed_prompt/analysis.json. Input snapshots are read locally; no pages are fetched, no embeddings are generated, and no model/default is changed.
