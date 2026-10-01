# ROC-AUC frontier: retention LR v3

Preserve v1/v2 and derive new features from cached retention documents. Keep the
exact v2 eligible population and hostname assignments. No new parsing is needed.

## Bounded search

Five predeclared variants: existing v2 features tuned for AUC; added lexical and
section relevance features; added composition features; all features; content-only
features excluding URL-pattern and source-quality signals. Each tests C in
0.001, 0.01, 0.1, 1, 10. Choose C using four hostname-grouped folds inside training
(seed 137). Fit imputation and scaling separately within each fold. Validation
compares finalists; test remains closed until selection and audits are frozen.

## Feature ideas

Query-word precision, Dice overlap, saturated repetition counts and adjacent-word
matching distinguish focused answers from long pages that merely mention words.
Section coverage distribution measures local relevance. Paragraph lengths, text
allocation, vocabulary diversity, numbers, repeated headings and link density
measure document composition. Features never consume labels, hostname identity,
record position, source filename, or split. Metadata is limited to page inputs.
Every added feature has a plain-language description in the generated manifest.

## Concentration and manipulation guardrails

Predeclare maximum absolute standardized coefficient share: 20% for one transformed
feature and 60% for the top five. Inspect validation permutation importance at
feature and family levels too; correlated features can split importance and conceal
concentration. Treat positive permutation top-one share over 45% as a review gate,
not evidence by itself of leakage. Test repeated query text/headings and irrelevant
padding against predictions. Report observed changes rather than claiming immunity.
Do not add redundant features merely to flatten the importance plot.

## Deliverable and interpretation

Freeze the selected model before one reused-test comparison with v2. Report ROC-AUC,
host-bootstrap uncertainty, log loss, Brier score and within-host AUC; show feature
importance and sensitivity visually with ELI5 explanations. Selection favors ROC-AUC,
so calibration may worsen. Test was previously inspected: new hosts are still needed
for independent confirmation. Dominant importance is a diagnostic, and a balanced
plot does not prove absence of leakage or manipulation risk.
