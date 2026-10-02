"""Freeze v5 development decision, then optionally evaluate a winning new candidate."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.metrics import roc_auc_score
from trad_ml_scorer.finalize_frontier import sha
from trad_ml_scorer.lr_evaluation import metrics, host_bootstrap
from trad_ml_scorer.train_lr import pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluate',action='store_true')
    parser.add_argument('--version',choices=('v5','v6'),default='v5')
    args=parser.parse_args()
    version=args.version
    previous='v4' if version=='v5' else 'v5'
    root,cache=Path('trad_ml_scorer')/version,Path('data/trad_ml_scorer')/version
    manifest=json.loads((cache/'manifest.json').read_text())
    assert sha(cache/'features.npz')==manifest['features_sha256']
    assert all(sha(p)==h for p,h in manifest['code_hashes'].items())
    data=dict(np.load(cache/'features.npz'))
    old_root=Path('data/trad_ml_scorer')/previous
    old=dict(np.load(old_root/'features.npz'))
    old_names=json.loads((old_root/'manifest.json').read_text())['feature_names']
    old_columns=[old_names.index(n) for n in manifest['base_names']]
    for key in ('ids','y','hosts','splits','clean','common'):
        np.testing.assert_array_equal(data[key],old[key])
    np.testing.assert_allclose(data['X'][:,:len(old_columns)],old['X'][:,old_columns],equal_nan=True)
    if not args.evaluate:
        if (root/'selection.json').exists():
            raise FileExistsError('Development decision already frozen')
        search=json.loads((root/'search.json').read_text())
        audit=json.loads((root/'audit.json').read_text())
        stress=json.loads((root/'stress.json').read_text())
        baseline=next(r for r in search['finalists'] if r['variant']==f'{previous}_baseline')
        raw=json.loads((root/'raw_stress.json').read_text()) if version=='v6' else None
        eligible=[]; decisions=[]
        for row in search['finalists']:
            perm=next(r for r in audit['audits'] if r['variant']==row['variant'])
            attacks=stress['variants'][row['variant']]
            gates={'coefficient':row['coefficient_gate'],'permutation':perm['permutation_gate'],
                   'stress':all(a['mean_delta']<=.03 and a['p95_increase']<=.08 for a in attacks.values()),
                   'cv_non_regression':row['cv_auc']>=baseline['cv_auc']-1e-12}
            if raw is not None:
                raw_base=raw['variants'][f'{previous}_baseline']
                gates['raw_non_regression']=all(r[metric]<=raw_base[attack][metric]+.01 for attack,r in raw['variants'][row['variant']].items() for metric in ('mean_delta','p95_increase'))
            decisions.append({'variant':row['variant'],'gates':gates})
            if all(gates.values()):
                eligible.append(row)
        if not eligible:
            raise ValueError('No eligible model including baseline; inspect gates before further work')
        chosen=max(eligible,key=lambda r:r['validation']['roc_auc'])
        promoted=chosen['variant']!=f'{previous}_baseline' and chosen['validation']['roc_auc']>baseline['validation']['roc_auc']
        if not promoted:
            chosen=baseline
        bundle=joblib.load(cache/(chosen['variant']+'.joblib'))
        bundle['code_hashes']=manifest['code_hashes']
        bundle['parser_policy']='retention-first-v1'
        # Independent training-only refit verifies that the frozen final model has no val/test fit.
        cols=[manifest['feature_names'].index(n) for n in bundle['feature_names']]
        train=data['splits']=='train'
        fitted=pipeline(chosen['C']).fit(data['X'][train][:,cols],data['y'][train])
        for a,b in ((bundle['pipeline'][0].statistics_,fitted[0].statistics_),
                    (bundle['pipeline'][1].mean_,fitted[1].mean_),
                    (bundle['pipeline'][1].scale_,fitted[1].scale_),
                    (bundle['pipeline'][-1].coef_,fitted[-1].coef_),
                    (bundle['pipeline'][-1].intercept_,fitted[-1].intercept_)):
            np.testing.assert_allclose(a,b,rtol=1e-10,atol=1e-10)
        assert bundle['pipeline'][1].n_samples_seen_==train.sum()
        for a,b in [('train','validation'),('train','test'),('validation','test')]:
            assert not set(data['hosts'][data['splits']==a]) & set(data['hosts'][data['splits']==b])
        joblib.dump(bundle,cache/'model.joblib')
        result={'selected':chosen,'baseline':baseline,'new_candidate_promoted':promoted,'decisions':decisions,
                'test_accessed':False,'model_sha256':sha(cache/'model.joblib'),'dataset_sha256':manifest['features_sha256'],
                'rule':f'CV-nonregressing finalists passing concentration and stress gates, then max validation AUC; retain {previous} if no validation improvement. V6 additionally requires raw-edit mean/p95 non-regression within .01.',
                'verification':['source/code hashes',f'exact {previous} rows/labels/host splits',f'unchanged selected {previous} feature columns','zero hostname overlap','training-only full refit parity']}
        (root/'selection.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'variant':chosen['variant'],'promoted':promoted,'decisions':decisions},indent=2))
        return
    if (root/'test_metrics.json').exists():
        raise FileExistsError('Test already evaluated')
    decision=json.loads((root/'selection.json').read_text())
    if not decision['new_candidate_promoted']:
        raise ValueError('No development winner; do not reopen the reused test')
    assert sha(cache/'model.joblib')==decision['model_sha256']
    model=joblib.load(cache/'model.joblib')
    cols=[manifest['feature_names'].index(n) for n in model['feature_names']]
    mask=data['splits']=='test'; y=data['y'][mask]; hosts=data['hosts'][mask]
    p=model['pipeline'].predict_proba(data['X'][mask][:,cols])[:,1]
    baseline=joblib.load(old_root/'model.joblib')['pipeline'].predict_proba(old['X'][mask][:,old_columns])[:,1]
    groups=[np.flatnonzero(hosts==h) for h in np.unique(hosts)]
    rng=np.random.default_rng(142); deltas=[]
    for _ in range(1000):
        rows=np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
        if len(np.unique(y[rows]))==2:
            deltas.append(roc_auc_score(y[rows],p[rows])-roc_auc_score(y[rows],baseline[rows]))
    result={'selected':metrics(y,p,hosts),f'{previous}_same_rows':metrics(y,baseline,hosts),
            'host_bootstrap_95_percent':host_bootstrap(y,p,hosts,repeats=1000),
            'paired_auc_delta':{'estimate':float(roc_auc_score(y,p)-roc_auc_score(y,baseline)),
                               'low':float(np.quantile(deltas,.025)),'high':float(np.quantile(deltas,.975)),'replicates':len(deltas)},
            'status':'Reused historical benchmark, not independent confirmation. No test-driven selection.',
            'model_sha256':decision['model_sha256']}
    (root/'test_metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    predictions=[{'record_id':str(i),'hostname':str(h),'label':int(label),'probability':float(q),f'{previous}_probability':float(b)} for i,h,label,q,b in zip(data['ids'][mask],hosts,y,p,baseline)]
    (root/'test_predictions.json').write_text(json.dumps(predictions,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
