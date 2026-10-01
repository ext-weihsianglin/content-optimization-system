"""Bounded ROC-AUC search with host-grouped training CV and concentration gates."""
import hashlib
import json
import argparse
from pathlib import Path
import warnings
import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from trad_ml_scorer.train_lr import pipeline
from trad_ml_scorer.lr_evaluation import metrics


def concentration(model):
    weights = np.abs(model[-1].coef_[0])
    weights /= max(weights.sum(), 1e-15)
    return {'top1_share': float(weights.max()), 'top5_share': float(np.sort(weights)[-5:].sum())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v3", "v4"), default="v3")
    version = parser.parse_args().version
    warnings.filterwarnings('error', category=ConvergenceWarning)
    source = Path('data/trad_ml_scorer') / version
    output = Path('trad_ml_scorer') / version
    output.mkdir(exist_ok=True)
    if (output/'search.json').exists():
        raise FileExistsError('Search already frozen; use a new version for further experiments')
    manifest = json.loads((source/'manifest.json').read_text())
    assert hashlib.sha256((source/'features.npz').read_bytes()).hexdigest() == manifest['features_sha256']
    data = dict(np.load(source/'features.npz'))
    # Test rows never enter fitting, candidate scoring, or selection.
    train, val = data['splits'] == 'train', data['splits'] == 'validation'
    x, y, hosts = data['X'][train], data['y'][train], data['hosts'][train]
    names = manifest['feature_names']
    base = manifest['base_names']
    families = manifest['families']
    variants = {'v2_auc': base, 'lexical': base + families['lexical'] + families['relevance'],
                'composition': base + families['composition'], 'all': names,
                'content_only': [n for n in names if not n.startswith(('path_', 'format_', 'needs_review', 'possible_error', 'sparse_body', 'has_jsonld', 'has_article_schema', 'log_source_script', 'retained_text_fraction'))]}
    folds = list(StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=137).split(x,y,hosts))
    for a,b in folds:
        assert not set(hosts[a]) & set(hosts[b])
    candidates, finalists = [], []
    for variant, selected_names in variants.items():
        columns = [names.index(n) for n in selected_names]
        matrix = x[:, columns]
        rows = []
        for c in (.001, .01, .1, 1., 10.):
            scores = []
            for a,b in folds:
                model = pipeline(c).fit(matrix[a],y[a])
                scores.append(roc_auc_score(y[b],model.predict_proba(matrix[b])[:,1]))
            model = pipeline(c).fit(matrix,y)
            shares = concentration(model)
            row = {'variant':variant, 'C':c, 'cv_auc':float(np.mean(scores)), 'fold_auc':scores, **shares,
                   'coefficient_gate': shares['top1_share'] <= .20 and shares['top5_share'] <= .60}
            rows.append(row)
            print(json.dumps(row), flush=True)
        candidates.extend(rows)
        eligible = [r for r in rows if r['coefficient_gate']]
        if not eligible:
            continue
        best = max(eligible,key=lambda r:r['cv_auc'])
        model = pipeline(best['C']).fit(matrix,y)
        xv = data['X'][val][:,columns]
        best = {**best, 'validation':metrics(data['y'][val], model.predict_proba(xv)[:,1], data['hosts'][val]), 'feature_names':selected_names}
        joblib.dump({'pipeline':model,'feature_names':selected_names,'feature_version':manifest['version'],'selection':best,'extractor_sha256':manifest['extractor_sha256'],'dataset_sha256':manifest['features_sha256']}, source/f'{variant}.joblib')
        finalists.append(best)
    result = {'rule':'Within each predeclared variant choose C by 4-fold hostname-grouped training ROC-AUC subject to coefficient gates. Compare finalists on validation ROC-AUC; permutation and manipulation audit required before final freeze/test.',
              'coefficient_gate':{'top1_max':.20,'top5_max':.60}, 'seed':137, 'folds':4,
              'candidates':candidates, 'finalists':finalists, 'test_accessed':False,
              'manifest':manifest}
    (output/'search.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Finalists:', json.dumps([{k:r[k] for k in ('variant','C','cv_auc','validation')} for r in finalists],indent=2))

if __name__ == '__main__':
    main()
