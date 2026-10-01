## Every handcrafted feature, explained simply

Think of the model as a reader with a 35-question checklist. Some questions ask whether the page talks about what you searched for; others describe how the page is organized. These measurements help predict the dataset’s top/bottom label. A bigger value is not automatically better.

In names beginning with “log”, we squeeze big counts onto a smaller scale: going from 10 to 100 words matters more than adding another 90 words to a huge page. A yes/no feature uses 1 for yes and 0 for no. “Coverage” asks what fraction of the question’s different meaningful word tokens appear in a place on the page; repeated words do not earn extra points. It matches words, not meaning.

### Does the page match the question?

| Feature | ELI5 explanation | Example or detail |
| --- | --- | --- |
| coverage_title | Does the browser-tab title contain the words you asked about? | For “running shoes”, a title containing “shoes” but not “running” gets 1 of 2 words: 0.5. |
| coverage_headings | Do the page’s section labels mention your question’s words? | Looks across all extracted headings together, not just the biggest heading. |
| coverage_body | Does the main reading text mention your question’s words anywhere? | Words in unrelated paragraphs can still count; this does not prove the page answers the question. |
| coverage_intro | Does the page get to your topic near the beginning? | Checks only the first 200 word tokens of the extracted reading text. |
| coverage_url_path | Do the words after the website name in its address match your question? | In example.com/guides/running-shoes, it checks the path, not “example.com”. |

### What kind of question is it?

| Feature | ELI5 explanation | Example or detail |
| --- | --- | --- |
| log_prompt_words | How long is the question, with very long questions squeezed down? | “Shoes” is shorter than “Which running shoes work best for long-distance training?” |
| prompt_question | Does the wording look like a question? | Starts with an English question word or contains ? or ？. It is a simple clue, not a language-understanding test. |
| prompt_comparison | Does the question sound like someone is choosing or comparing things? | Looks for words such as “best”, “compare”, “versus”, or “cheapest”. |
| prompt_how_to | Is the person asking how to do something? | Looks for the English phrase “how to”. |

### How much content and structure does the page have?

| Feature | ELI5 explanation | Example or detail |
| --- | --- | --- |
| log_word_count | How much main reading text is there? | Counts extracted word tokens, then squeezes large counts. |
| log_title_words | How long is the browser-tab title? | Counts words in the HTML title, which can differ from the big title shown on the page. |
| log_heading_count | How many section labels break up the reading text? | Counts H1 through H6 headings, then squeezes large counts. |
| log_h1_count | How many top-level headings are in the reading area? | Counts H1 tags; these usually mark major titles. |
| log_list_items | How many bullet points or numbered items are there? | Counts individual list items, including nested ones, then squeezes large counts. |
| log_table_count | How many tables are in the reading area? | Counts HTML tables, not whether their contents are useful. |
| headings_per_1000_words | How often does a heading interrupt the text? | Five headings in 1,000 words gives 5; five in 500 gives 10. |
| list_items_per_1000_words | How packed with bullet points is the page? | Ten list items in 500 words gives 20 per 1,000 words. |
| has_table | Is there at least one table in the reading area? | A yes/no flag, regardless of table count. |
| has_list | Is there at least one bulleted or numbered list? | Looks for UL or OL tags in the reading area. |

### What clues did the page builder leave in the HTML?

| Feature | ELI5 explanation | Example or detail |
| --- | --- | --- |
| has_main | Did the page builder label a place as the main content? | Looks for a main tag or role="main" anywhere in the original HTML. |
| has_article | Did the builder label a place as an article? | Looks for an article tag; this does not guarantee good writing or even an editorial article. |
| has_jsonld | Is there a machine-readable description attached to the page? | Detects JSON-LD scripts; presence does not mean the description is correct. |
| has_article_schema | Does that machine-readable description call the content an article-like item? | Recognizes the extractor’s Article-family labels, including NewsArticle and BlogPosting. It does not verify the claims. |

### How much page clutter or extraction trouble is there?

| Feature | ELI5 explanation | Example or detail |
| --- | --- | --- |
| removed_text_fraction | How much body text did the cleaner throw away as surrounding clutter? | If 300 of 1,000 raw-body tokens disappear during boilerplate cleaning, this is about 0.3. |
| focus_text_fraction | How much of the original body text ended up in the selected reading area? | If the chosen article holds 600 of 1,000 raw-body tokens, this is about 0.6. |
| script_char_ratio | How much of the saved HTML is made of script tags? | Roughly measures code bulk, not reading text or actual browser speed. |
| empty_title | Is the browser-tab title missing or blank? | A missing title is a clue about the snapshot, not proof of low-quality content. |
| sparse_body | Did the quality checker find almost no body text? | Yes when its broader body-text count is 30 tokens or fewer. |
| failure_page | Does the saved page look broken, blocked, or empty? | Heuristics look for things such as “access denied”, error titles, or a short request to enable JavaScript. |
| recognized_html | Does the saved content look like HTML to the checker? | Looks for common tags. Plain text, Markdown, or unusual fragments may fail this simple check. |

### What does the page address suggest?

| Feature | ELI5 explanation | Example or detail |
| --- | --- | --- |
| path_depth | How many pieces are in the address after the website name? | /guides/shoes/running has depth 3. It is not the number of clicks needed to reach the page. |
| path_homepage | Does the address point to the website’s front door? | The path is empty or just /. |
| path_editorial | Does the address look like a blog, guide, or article section? | Paths containing /blog/, /guides/, or similar fixed patterns are clues, not verified page types. |
| path_commerce | Does the address look like a shopping or pricing page? | Looks for fixed patterns such as /products/, /shop/, or /pricing/. |
| path_support_docs | Does the address look like help or documentation? | Looks for fixed patterns such as /help/, /docs/, or /faq/. |

### What happens when a measurement is missing?

A missing value means “we could not measure this”, which differs from measuring zero. The pipeline fills it with the middle training value and, for columns that were missing during training, adds a small “this was missing” flag. This fitted model has four such flags: heading density, list-item density, removed-text fraction, and focus-text fraction. These flags are extra bookkeeping, not four additional handcrafted features. The pipeline then puts measurements on comparable scales before combining them into a score.

## Interesting and promising features for the next round

The most useful current clues on validation were title/query overlap, heading count, and homepage status: shuffling each increased log loss by about 0.0158, 0.0132, and 0.0096, respectively. Comparison wording also mattered (about 0.0050). Removing the alignment family hurt validation loss most among the tested family removals. These results suggest the hypotheses below; none of these new features has been evaluated yet.

### First priority: make query matching more specific

| Candidate | Simple idea and possible implementation | Why it is promising |
| --- | --- | --- |
| Title phrase and H1 alignment | Check whether adjacent question words stay together in the title; compute coverage for H1 separately and measure agreement between title and H1. | Title overlap is the strongest current permutation signal. Phrase matching could distinguish a coherent topic match from scattered words. |
| Best matching section | Split text by headings; compute the best question coverage in any one section, the number of matching sections, and coverage in that section’s heading. | Whole-page coverage can reward long pages that scatter the right words without answering in one place. The heading-count signal motivates testing whether relevant organization matters more than raw count. |
| Answer proximity | Measure how early a compact paragraph containing the question’s key terms appears, and how tightly those terms occur together. | The current first-200-token feature is coarse. A nearby, concentrated match could better identify a direct answer, although lexical proximity still cannot verify correctness. |

### Second priority: connect the question to the right page shape

| Candidate | Simple idea and possible implementation | Why it is promising |
| --- | --- | --- |
| Intent × structure interactions | Add products such as comparison-question × table-present, how-to-question × numbered-step-count, or question-marker × matching-heading coverage. | Plain LR adds separate effects. An interaction lets a table matter differently for a comparison question than for a how-to request. Start with a small, predefined set. |
| Page-purpose compatibility | Match navigational or brand-seeking questions to homepage-like pages, and instruction-seeking questions to documentation-like pages. Infer purpose from the prompt, title, and path without encoding hostname identity. | Homepage status and URL features carry signal. Compatibility may explain when that association is useful rather than treating every homepage as a good answer. |
| Main-text and navigation separation | Measure link-text share, repeated navigation text, and heading coverage inside versus outside the selected reading area. | Focus-text fraction contributes predictive information. Better content separation could reduce reliance on site templates and extraction quirks. |

### Exploratory follow-ups

| Candidate | Simple idea and possible implementation | What to watch |
| --- | --- | --- |
| Diminishing returns and thresholds | Add a few training-defined ranges for heading counts or title coverage, instead of assuming one slope on the transformed scale. | The response plots reflect the LR formula; they do not prove that each extra heading helps equally. Extra flexibility must earn its place on validation. |
| Evidence and specificity | Count cited-source links inside the main text, numeric measurements with units, and explicit comparison attributes such as prices or specifications. | These might help identify concrete answers, but can also reflect commerce, page length, or boilerplate. Treat them as lower-priority hypotheses, not established trustworthiness measures. |
| Language-aware lexical matching | Improve handling of inflections, punctuation, and language-specific word boundaries while keeping extraction deterministic. | The present English-oriented rules can miss useful matches in other languages. Any language detector or learned vocabulary needs its own documented provenance and fitting boundary. |

The first small experiment should add phrase/H1 alignment, best-section coverage, and a few intent–structure interactions, then compare each family with the frozen baseline. Keep the feature budget small and select using host-grouped validation or cross-validation confined to the development data. Learn thresholds, vocabularies, and any corpus statistics from training folds only.

The current test results are now known. Preserve this test set as the historical v1 benchmark; repeatedly checking it while crafting features would make it part of development. A fresh, genuinely unseen set of hosts or new data is needed for an independent next-round confirmation. Any comparison on the old test set should be labeled a reused benchmark, not a new untouched test. Better classification also does not prove that editing a page to change a feature improves its citations.
