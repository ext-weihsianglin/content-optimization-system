"""Freeze development selection; evaluate the reused benchmark in a separate invocation."""
import argparse
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.metrics import roc_auc_score
from trad_ml_scorer.lr_evaluation import metrics, host_bootstrap


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluate',action='store_true')
    args = parser.parse_args()
    root, cache = Path('trad_ml_scorer/v4'), Path('data/trad_ml_scorer/v4')
    data = dict(np.load(cache/'features.npz'))
    manifest = json.loads((cache/'manifest.json').read_text())
    assert sha(cache/'features.npz') == manifest['features_sha256']
    if not args.evaluate:
        if (root/'selection.json').exists():
            raise FileExistsError('Selection already frozen')
        search = json.loads((root/'search.json').read_text())
        audit = json.loads((root/'audit.json').read_text())
        stress = json.loads((root/'stress.json').read_text())
        eligible = []
        for candidate in search['finalists']:
            a = next(r for r in audit['audits'] if r['variant']==candidate['variant'])
            attacks = stress['variants'][candidate['variant']]
            # Thresholds specified before inspecting v4 stress results.
            robust = all(r['mean_delta'] <= .03 and r['p95_increase'] <= .08 for r in attacks.values())
            if candidate['coefficient_gate'] and a['permutation_gate'] and robust:
                eligible.append(candidate)
        if not eligible:
            raise ValueError('No candidate passes concentration and manipulation gates; continue development')
        chosen = max(eligible,key=lambda r:r['validation']['roc_auc'])
        path = cache/(chosen['variant']+'.joblib')
        bundle = joblib.load(path)
        dependencies = ['trad_ml_scorer/robust_features.py','trad_ml_scorer/frontier_features.py','trad_ml_scorer/retention_features.py','scripts/analyze_content.py','scripts/analyze_quality.py']
        dependencies += list(json.loads(Path('data/trad_ml_scorer/v2/manifest.json').read_text())['code_hashes'])
        hashes = {name:sha(name) for name in sorted(set(dependencies))}
        bundle['code_hashes'] = hashes
        bundle['parser_policy'] = 'retention-first-v1'
        joblib.dump(bundle,cache/'model.joblib')
        selection = {'selected':chosen,'model_sha256':sha(cache/'model.joblib'),'dataset_sha256':manifest['features_sha256'],
                     'code_hashes':hashes,'eligible_variants':[r['variant'] for r in eligible],
                     'rule':'Max validation ROC-AUC among CV-selected finalists passing coefficient, permutation, and stress gates.',
                     'stress_gates':{'mean_increase_max':.03,'p95_increase_max':.08}, 'test_accessed':False,
                     'limitation':'Repeated development comparisons; test is a reused historical benchmark, not independent confirmation.'}
        (root/'selection.json').write_text(json.dumps(selection,indent=2)+'\n')
        print(json.dumps(chosen,indent=2))
        return
    if (root/'test_metrics.json').exists():
        raise FileExistsError('Benchmark already evaluated; do not retune against it')
    selection = json.loads((root/'selection.json').read_text())
    assert sha(cache/'model.joblib') == selection['model_sha256']
    assert all(sha(p)==h for p,h in selection['code_hashes'].items())
    bundle = joblib.load(cache/'model.joblib')
    mask = data['splits']=='test'
    columns = [manifest['feature_names'].index(n) for n in bundle['feature_names']]
    probability = bundle['pipeline'].predict_proba(data['X'][mask][:,columns])[:,1]
    old = dict(np.load('data/trad_ml_scorer/v2/features.npz'))
    for key in ('ids','y','hosts','splits'):
        np.testing.assert_array_equal(data[key],old[key])
    baseline = joblib.load('data/trad_ml_scorer/v2/model.joblib')['pipeline'].predict_proba(old['X'][mask])[:,1]
    y, hosts = data['y'][mask], data['hosts'][mask]
    unique = np.unique(hosts)
    groups = [np.flatnonzero(hosts==h) for h in unique]
    rng = np.random.default_rng(142)
    deltas = []
    for _ in range(1000):
        rows = np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
        if len(np.unique(y[rows]))==2:
            deltas.append(roc_auc_score(y[rows],probability[rows])-roc_auc_score(y[rows],baseline[rows]))
    result = {'benchmark_status':selection['limitation'],'selected':metrics(y,probability,hosts),
              'v2_same_rows':metrics(y,baseline,hosts),'host_bootstrap_95_percent':host_bootstrap(y,probability,hosts,repeats=1000),
              'paired_auc_delta':{'estimate':float(roc_auc_score(y,probability)-roc_auc_score(y,baseline)),
                                  'low':float(np.quantile(deltas,.025)),'high':float(np.quantile(deltas,.975)),'replicates':len(deltas)},
              'model_sha256':selection['model_sha256']}
    (root/'test_metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    predictions = [{'record_id':str(i),'hostname':str(h),'is_cited_high':int(label),'probability':float(p),'v2_probability':float(b)} for i,h,label,p,b in zip(data['ids'][mask],hosts,y,probability,baseline)]
    (root/'test_predictions.json').write_text(json.dumps(predictions,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
