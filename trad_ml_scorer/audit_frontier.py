"""Audit validation-only permutation concentration before freezing a v3 winner."""
import hashlib
import json
import argparse
from pathlib import Path
import joblib
import numpy as np
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score
from trad_ml_scorer.retention_features import FAMILIES as BASE_FAMILIES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v3", "v4", "v5", "v6"), default="v3")
    version = parser.parse_args().version
    root = Path('trad_ml_scorer') / version
    cache = Path('data/trad_ml_scorer') / version
    if (root/'audit.json').exists():
        raise FileExistsError('Audit already frozen')
    search = json.loads((root/'search.json').read_text())
    data = dict(np.load(cache/'features.npz'))
    val = data['splits'] == 'validation'
    names = search['manifest']['feature_names']
    families = {**BASE_FAMILIES, **search['manifest']['families']}
    audits = []
    for candidate in search['finalists']:
        variant = candidate['variant']
        bundle = joblib.load(cache/f'{variant}.joblib')
        selected = bundle['feature_names']
        x = data['X'][val][:,[names.index(n) for n in selected]]
        y = data['y'][val]
        model = bundle['pipeline']
        result = permutation_importance(model,x,y,scoring='roc_auc',n_repeats=20,random_state=137)
        positive = np.maximum(result.importances_mean,0)
        share = float(positive.max()/positive.sum()) if positive.sum() else 1.
        permutation = [{'feature':n,'auc_drop':float(m),'std':float(s)} for n,m,s in zip(selected,result.importances_mean,result.importances_std)]
        rng = np.random.default_rng(137)
        base = roc_auc_score(y,model.predict_proba(x)[:,1])
        grouped = []
        for family, members in families.items():
            indices = [selected.index(n) for n in members if n in selected]
            if not indices:
                continue
            drops = []
            for _ in range(20):
                shuffled = x.copy()
                order = rng.permutation(len(x))
                shuffled[:,indices] = x[order][:,indices]
                drops.append(base-roc_auc_score(y,model.predict_proba(shuffled)[:,1]))
            grouped.append({'family':family,'auc_drop':float(np.mean(drops)),'std':float(np.std(drops))})
        audits.append({'variant':variant,'positive_permutation_top1_share':share,'permutation_gate':share<=.45,
                       'permutation':permutation,'family_permutation':grouped})
        print(variant,share,flush=True)
    eligible = [r for r in search['finalists'] if next(a for a in audits if a['variant']==r['variant'])['permutation_gate']]
    chosen = max(eligible,key=lambda r:r['validation']['roc_auc']) if eligible else None
    report = {'audits':audits,'selected':chosen,'test_accessed':False,'status':'Permutation screen complete; manipulation audit pending'}
    (root/'audit.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__ == '__main__':
    main()
