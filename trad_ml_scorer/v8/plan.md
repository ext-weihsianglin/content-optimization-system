# V8: Platt calibration on frozen v7.1

Implement issue #16 against the corrected Markdownify v7.1 base, not the older
mixed-parser v7. Preserve its 55 features, C=.001, model weights and host splits.
No new embeddings, feature preparation, calibration search or test predictions.

Generate one decision-function score per training row using four hostname-grouped
folds (StratifiedGroupKFold seed 137). Imputation, scaling and LR fit inside each
fold. Assert every row is scored once and every scored host is absent from that
fold's fitting population. Fit one global two-parameter sigmoid on these OOF
training scores only: p = sigmoid(a * logit + b). Do not feed probabilities into it.

Use standard Platt target smoothing: positive target (Npos+1)/(Npos+2), negative
target 1/(Nneg+2), computed exclusively from training labels. Minimize unweighted
mean binary cross-entropy with stable logaddexp/expit and an analytic gradient;
no regularization or class weighting. Initialize a=1,b=0 and require optimizer
convergence, finite parameters and a>0. Never reverse ranking to improve metrics.

Apply this calibrator to the frozen full-training v7.1 model's logits. OOF base
fits use fewer training hosts than the final base model; explicitly evaluate this
transfer on validation. Existing hyperparameter choices and validation readings
have prior exposure: these are reused development results, not fresh confirmation.

Report validation log loss, Brier, AUC, within-host AUC, AP, accuracy and ECE with
10 fixed equal-width probability bins [0,.1,...,1]. Include bin counts and observed
positive rates, uncalibrated/calibrated reliability and probability histograms.
Compute paired website-bootstrap intervals for log loss/Brier/ECE differences
(1000 draws, seed142); do not use ECE alone to select the layer.

Predeclared recommendation: recommend v8 for further confirmation only if slope
is positive, no validation saturation/new ranking ties, AUC/within-host AUC agree
within 1e-12, both log loss and Brier improve, and the 95% paired interval upper
bound for log-loss difference is below zero. Otherwise retain v7.1 as the default
and archive v8 as experimental. No automatic webapp rollout in either case.

Save a versioned calibration artifact with exact base model checksum, feature
contract, training IDs/OOF fold membership, configuration and code hashes. Keep
OOF data/model outside Git in shared trad_ml_scorer/v8/. Expose raw base logit,
uncalibrated high-class probability and calibrated high-class probability through
an explicit new adapter. Reject a wrong base model, invalid slope or contract.

Calibration targets the balanced host-relative high/low class, not probability of
being cited at all or causal edit uplift. Test remains closed; fresh-host confirmation
and any population-prior correction require separately planned data and evaluation.
