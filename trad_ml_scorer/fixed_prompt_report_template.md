# What happens when we edit a page?

**Keep the reader’s question and the webpage address the same. Make one small change to the page. Does our model’s score move—and what explains the change?**

Imagine editing a school essay while keeping the teacher’s question fixed. We want to know whether a particular revision helps. Looking at what good essays tend to have gives us clues; actually revising an essay and scoring it again answers a more specific question.

That is the purpose of this report. We use our existing **v5 model, which v6 retained**, to try small page edits. We have not retrained it or run another test-set evaluation.

> **What we learned:** These three edits did not show a convincing, consistent benefit in this small sample. Changing the title sometimes helped and sometimes hurt. Moving a relevant paragraph earlier barely moved the average. Splitting a paragraph was tried on too few pages to draw much from it. We have a way to explain the model’s reactions, but no reliable editing recipe yet.

## First, what does “score” mean?

The model estimates whether a page belongs to the **higher-citation group within its website**, using the question and the page. Our dataset compares higher- and lower-performing records that have already been cited. A score of 60% means the model assigns a 60% probability to that higher group in this sampled setting. It does **not** mean a 60% chance that an answer engine will cite the page.

Throughout this report, a change from 60% to 61% is **+1 percentage point**. All before/after changes describe the model’s prediction. To find out whether an edit increases real citations, we would still need to try it and observe answer-engine outcomes.

## 1. Try a real edit, then score the page again

This is what the earlier report called “coherent document edits.” It means **make an actual HTML change and recalculate every page measurement it affects**. Moving a paragraph, for example, can change where relevant text first appears and how sections are grouped. We let those measurements change together.

For each page, we keep its question and address fixed. Different pages can have different questions. We tried three simple edits:

| Edit | What we actually change | Why try it? |
|---|---|---|
| Use the main heading as the title | Copy an existing main heading (H1) into the page’s title. Keep the body wording. | See whether making these two descriptions agree helps the model. The existing heading is not guaranteed to be a better title. |
| Move a relevant paragraph earlier | Move an existing paragraph that matches more question words ahead of an earlier paragraph in the same container. | See whether making relevant information easier to find changes the score. “Relevant” here means word overlap, not verified answer quality. |
| Split a long paragraph | Break one long paragraph into two at an existing sentence boundary. Keep its words and their order. | See whether smaller text blocks change the score. |

We selected **40 validation HTML snapshots** in a fixed order based on their identifiers, without choosing pages because of their labels or potential score gains. An edit only runs when the page has the necessary structure: for example, a page without a suitable long paragraph cannot take the third edit. Those skipped cases are not counted as zero-change results.

### Read this chart like a before-and-after scorecard

- **Each dot is one page** where that edit could be applied. Left of zero means the model’s score went down; right means it went up.
- **The diamond is the average** of those page changes.
- **The horizontal line shows uncertainty around that average**, estimated by repeatedly resampling whole websites. If it crosses zero, the small sample does not give a clear direction for the average response.
- **No line for paragraph splitting:** only four websites contributed. That is too little support for the interval we report for the other edits.

![How the model reacts to three small page edits](edit_effects.svg)

{{edit_table}}

“Middle change” is the median: half the observed changes lie on either side. “Range” shows the smallest and largest changes we saw; it is not a guarantee for another page.

**What to take away:** Replacing the title with the existing main heading lowered the average score by about **0.93 points**, but individual pages moved in both directions. Moving a matching paragraph earlier increased the average by only **0.11 points**. Splitting a paragraph increased it by **0.02 points**, based on just four pages. The uncertainty lines for the first two edits cross zero. None is an established improvement to apply everywhere.

We checked that every applied edit kept the same body words and word counts. That prevents adding new claims or stuffing in question words, but it does not guarantee good writing: moving a paragraph can still break its context. Simply loading and saving the original HTML changed the score by **{{serialization_change}} points**, so these observed changes were not caused by that formatting step alone.

## 2. Follow one edit to see why its score changed

An overall score change is easier to understand when we show the pieces behind it. Here we use the **first applicable edit with a nonzero feature contribution**, rather than picking the biggest improvement.

**Edit:** {{example_action}}.

**Reader’s question:** {{example_prompt}}

**Model score: {{before_score}} → {{after_score}} ({{example_delta}} percentage points).**

Think of the bars below as entries on a receipt. Each entry explains one part of the model’s reaction to this edit. A bar to the right pushes the internal score up; a bar to the left pushes it down. A bigger bar explains more of the movement. Teal means a page-only measurement; orange means a question–page match. If present, “Other changed features” combines the remaining smaller entries.

![The pieces behind one page’s score change](local_contrast.svg)

The receipt adds up exactly on the model’s internal scale, called **log odds**. That scale is converted to the percentage score afterward, so the bars are **not percentage-point changes**. The question and URL-only measurements contribute zero to this before/after difference because we did not change them.

**How this helps editing:** Look at which measurements actually changed together. A negative bar for a matching feature does not mean we should remove useful text. Several related measurements can share the same information, and the model has learned their weights together.

## 3. Separate the question, the page, and their match

A “feature” is simply a measurement the model uses. We audited which inputs determine every feature. The retained model has **96 raw measurements**:

| Kind | Plain-language meaning | Example | Count |
|---|---|---|---:|
| **prompt** | Something about the reader’s question alone. | Is the question asking how to do something? | 4 |
| **doc** | Something about the page alone, including its address and metadata. | Is it the homepage? How many headings does it have? | 41 |
| **promptXdoc** | Something about how this question and this page fit together. | How many question words appear in the title? | 51 |

Here **X means “uses both inputs.”** It does not mean every feature literally multiplies two numbers.

The distinction matters for editing. `path_homepage` belongs to **doc** because the page address alone determines it. `path_query_precision` belongs to **promptXdoc** because it compares question words with the address. Both stay fixed when we edit only the HTML. Some newer candidates also check whether the page’s body supports that address match; those can change when the body changes.

Likewise, “length of the best-matching section” uses both inputs: the question decides **which section** we measure. By contrast, “fraction of headings written as questions” describes the page alone.

### Chart A: Which measurements have larger model weights?

These panels show the strongest weights in each of the three groups. **Right means a positive weight; left means a negative weight.** Longer bars mean larger weights after accounting for each measurement’s spread in the training data. We show up to 20 per group, not every feature.

![Model weights grouped by what each feature measures](separated_coefficients.svg)

`[URL fixed]` marks measurements that cannot move during our HTML-only edits. `[diagnostic]` marks signals about source format or parsing quality; they are context to inspect, not editing goals. Pure-question features still help set the starting score, even though their own contributions do not change when the question stays fixed.

**Read this as a description of the model, not a to-do list.** A large homepage weight, for example, does not tell us to turn every page into a homepage. A weight also cannot tell us what happens when one real edit changes several measurements at once. That is why we start with actual before/after edits.

### Chart B: Which measurements does the model rely on for ranking?

Here we scramble one measurement across validation records and ask: **Does the model become worse at sorting higher- and lower-performing records?** A larger drop means it relied more on that measurement in this check. The ranking measure is ROC-AUC: roughly, how often a randomly chosen higher-group record gets a higher score than a lower-group record.

![How much ranking performance drops when a measurement is scrambled](document_permutation.svg)

The short lines show variation across repeated shuffles, not uncertainty about real citation improvement. Measurements that overlap in meaning can cover for each other, making one look less important on its own. Shuffling can also create combinations that would not occur in a real page.

**This chart mixes records with different questions.** Showing only doc and promptXdoc bars does not turn it into a same-question comparison. It tells us about predictive reliance across this dataset, not how much a specific HTML edit would help.

## 4. What evidence is still missing?

Ideally, we would compare many pages answering **the same question on the same website**, with both higher- and lower-performing examples. That would help separate page differences from question differences.

Our validation data has only **{{mixed_groups}} such group, containing {{mixed_rows}} records**. There are {{repeated_groups}} repeated question/website groups overall ({{repeated_rows}} records), but most do not contain both outcomes. Even when we allow different websites, there is only {{cross_host_groups}} exact-question group with both outcomes. That is too little evidence for a reliable same-question ranking analysis.

The page-edit probes let us inspect the model’s behavior today. They cannot fill that gap in observed outcomes.

## 5. How to make the next report more useful

| Next step | What it would tell us |
|---|---|
| Try a specific, sensible revision; then show every changed measurement and the score difference. | Why the model likes or dislikes that exact edit. Check the text still reads well and remains factual. |
| Show results across more pages, including negative changes and cases where the edit cannot apply. | Whether a result is repeatable or driven by a few examples. Keep uncertainty grouped by website. |
| Collect more pages for the same question and website, with both outcomes. | Which page differences help distinguish higher- from lower-performing examples while the question stays fixed. |
| Test related feature families together. | Whether several overlapping measurements matter collectively, even if one-at-a-time checks look small. |
| Evaluate approved edits against real answer-engine outcomes over time. | Whether model-score changes translate into actual citation improvement, with question, engine and exposure accounted for. |

More explanation tools are not automatically better. **SHAP** assigns credit relative to a reference set of records; **PDP/ALE** summarize score responses as measurements vary. If those references mix unrelated questions or impossible page measurements, their plots can mislead an editor. For this linear model, the exact before/after receipt already explains a concrete edit. If we add other views, their comparisons should respect the fixed question and realistic page changes.

## Technical appendix

The reading above is the main story. The following details make the results reproducible and let you inspect each feature.

### How the exact explanation is calculated

`logit P = intercept + prompt contribution + doc contribution + promptXdoc contribution`

`change in logit = sum of weight × (edited measurement − original measurement)`

Here measurements have already passed through the fitted missing-value handling and training-data scaling. Missingness indicators—extra flags saying a value was absent—are included. The terms sum exactly to the model’s log-odds difference. Probability change is `sigmoid(original logit + change in logit) − sigmoid(original logit)`.

Example record: `{{example_record}}`. Its log-odds change is `{{example_logit}}`. Every changed contribution is stored in the original `interpretation/fixed_prompt/analysis.json`.

Average-effect intervals use 1,000 resamples of website clusters and require at least five websites. These are descriptive 95% bootstrap intervals for the sampled pages and frozen model. They do not include model-training uncertainty or establish causal citation uplift.

### Scope and provenance

This inventory covers **all 142 retention-based v2–v6 candidates**, including rejected candidates: 4 prompt, 41 doc and 97 promptXdoc. The selected model uses 96 of them. Its transformed input has 104 columns after adding missingness indicators; those indicators inherit their underlying feature’s dependency. V1 remains a separate frozen extractor.

The three-way audit supersedes the original companion’s five groups, which mixed input dependency with editing constraints. Original `analysis.json`, `verification.json` and experiment results remain unchanged. All coefficients, shuffle results and edit outcomes in this report reuse that evidence. This rewrite changes presentation only.

### Every feature, with its dependency and editing role

“May vary with HTML” means a suitable edit could change the measurement, not that every edit does. “Selected v5: no” means the candidate is in the audit but is not part of the retained model. Diagnostic flags describe the parser/source; their presence is not a recommendation to optimize them.

{{feature_table}}

### Rebuild the report

From the repository root:

```sh
uv run python -m trad_ml_scorer.build_fixed_prompt_report
```

This rebuilds Markdown, standalone HTML and plots from the saved analysis. It does not redo data preparation, fit a model, or evaluate the test set. All images are embedded in the HTML.

The original edit-analysis command is `uv run python -m trad_ml_scorer.analyze_fixed_prompt --input-dir data/raw`. It reads local snapshots and refuses to overwrite existing results. It is not needed for this presentation update.
