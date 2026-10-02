"""Two-parameter Platt scaling of LR logits, without base-model regularization."""
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

VERSION = 'lr-semantic-v8-platt'


def calibrate(logits, slope, intercept):
    logits = np.asarray(logits, dtype=float)
    if not np.isfinite(logits).all() or not np.isfinite([slope, intercept]).all() or slope <= 0:
        raise ValueError('Expected finite logits/parameters and a positive calibration slope')
    # Float overflow at extreme finite inputs should saturate sigmoid, not emit NaNs.
    with np.errstate(over='ignore'):
        return expit(slope * logits + intercept)


def fit_platt(logits, labels):
    scores, y = np.asarray(logits, dtype=float), np.asarray(labels)
    if scores.ndim != 1 or y.shape != scores.shape or not np.isfinite(scores).all():
        raise ValueError('Expected aligned finite one-dimensional logits/labels')
    if set(np.unique(y)) != {0, 1} or np.ptp(scores) == 0:
        raise ValueError('Both classes and nonconstant scores are required')
    positives, negatives = int(y.sum()), int((1-y).sum())
    targets = np.where(y == 1, (positives+1)/(positives+2), 1/(negatives+2))
    def objective(theta):
        z = theta[0]*scores + theta[1]
        residual = expit(z)-targets
        return float(np.mean(np.logaddexp(0,z)-targets*z)), np.array([np.mean(residual*scores),np.mean(residual)])
    result = minimize(objective, np.array([1.,0.]), method='L-BFGS-B', jac=True,
                      options={'maxiter':1000,'ftol':1e-14,'gtol':1e-10})
    if not result.success or not np.isfinite(result.x).all() or result.x[0] <= 0:
        raise ValueError('Calibration fit failed or would reverse ranking: '+str(result.message))
    return {'slope':float(result.x[0]),'intercept':float(result.x[1]),
            'positive_target':float((positives+1)/(positives+2)), 'negative_target':float(1/(negatives+2)),
            'positives':positives,'negatives':negatives,'objective':float(result.fun),
            'optimizer':'L-BFGS-B','iterations':int(result.nit),'converged':bool(result.success),
            'target_smoothing':'Platt class-count smoothing','regularization':None,'sample_weighting':'uniform'}


def reliability(labels, probabilities, bins=10):
    y, p = np.asarray(labels), np.asarray(probabilities,dtype=float)
    if y.ndim != 1 or y.shape != p.shape or len(y)==0 or not np.isfinite(p).all() or ((p<0)|(p>1)).any():
        raise ValueError('Expected nonempty aligned labels and probabilities in [0,1]')
    indices = np.minimum((p*bins).astype(int),bins-1)
    rows=[];ece=0.
    for b in range(bins):
        mask=indices==b;count=int(mask.sum())
        confidence=float(p[mask].mean()) if count else None
        observed=float(y[mask].mean()) if count else None
        rows.append({'lower':b/bins,'upper':(b+1)/bins,'count':count,'mean_probability':confidence,'observed_positive_fraction':observed})
        if count:ece += count/len(y)*abs(confidence-observed)
    return {'ece':float(ece),'bin_policy':f'{bins} fixed equal-width bins, left-closed/right-open except final includes 1','bins':rows}


def assign_oof_scores(output, assigned, fit_rows, held_rows, hosts, scores):
    """Fail on host overlap, repeated scoring, or incomplete/nonfinite predictions."""
    if set(hosts[fit_rows]) & set(hosts[held_rows]):
        raise ValueError('Host leakage in OOF fold')
    if len(np.unique(held_rows)) != len(held_rows) or assigned[held_rows].any():
        raise ValueError('OOF row scored more than once')
    if np.asarray(scores).shape != (len(held_rows),) or not np.isfinite(scores).all():
        raise ValueError('Invalid OOF scores')
    output[held_rows]=scores
    assigned[held_rows]=True
