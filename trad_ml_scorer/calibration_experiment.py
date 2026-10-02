"""Train-only OOF Platt fit over v7.1; evaluate only reused validation hosts."""
from pathlib import Path
import json
import warnings
import joblib
import numpy as np
from scipy.special import expit
from sklearn.exceptions import ConvergenceWarning
from sklearn.model_selection import StratifiedGroupKFold
from trad_ml_scorer.platt_calibration import VERSION, fit_platt, calibrate, reliability, assign_oof_scores
from trad_ml_scorer.prepare_semantic import digest
from trad_ml_scorer.predict_markdownify import load_model
from trad_ml_scorer.predict_platt import load_calibrated_model, scores_from_logit
from trad_ml_scorer.train_lr import pipeline
from trad_ml_scorer.lr_evaluation import metrics

ROOT=Path('trad_ml_scorer/v8')
DATA=Path('/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/trad_ml_scorer')
OUTPUT=DATA/'v8'
BASE=DATA/'v7.1'


def paired_differences(y,raw,calibrated,hosts,repeats=1000):
    groups=[np.flatnonzero(hosts==h) for h in np.unique(hosts)]
    rng=np.random.default_rng(142)
    samples={k:[] for k in ('log_loss','brier_score','ece')}
    def losses(p):
        p=np.clip(p,np.finfo(float).eps,1-np.finfo(float).eps)
        return -(y*np.log(p)+(1-y)*np.log1p(-p))
    log_delta=losses(calibrated)-losses(raw)
    brier_delta=(calibrated-y)**2-(raw-y)**2
    for _ in range(repeats):
        ix=np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
        samples['log_loss'].append(float(log_delta[ix].mean()))
        samples['brier_score'].append(float(brier_delta[ix].mean()))
        samples['ece'].append(reliability(y[ix],calibrated[ix])['ece']-reliability(y[ix],raw[ix])['ece'])
    points={'log_loss':float(log_delta.mean()),'brier_score':float(brier_delta.mean()),'ece':reliability(y,calibrated)['ece']-reliability(y,raw)['ece']}
    return {k:{'delta':points[k],'low':float(np.quantile(v,.025)),'high':float(np.quantile(v,.975)),'replicates':len(v)} for k,v in samples.items()}


def main():
    warnings.filterwarnings('error',category=ConvergenceWarning)
    if (ROOT/'results.json').exists() or (OUTPUT/'calibration.joblib').exists():
        raise FileExistsError('V8 calibration already frozen; do not overwrite')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((BASE/'manifest.json').read_text())
    assert digest(BASE/'features.npz')==manifest['features_sha256']
    base=load_model(BASE/'model.joblib')
    prior=json.loads(Path('trad_ml_scorer/v7.1/results.json').read_text())
    assert digest(BASE/'model.joblib')==prior['model_sha256']
    d=np.load(BASE/'features.npz')
    train=np.flatnonzero(d['splits']=='train');val=np.flatnonzero(d['splits']=='validation')
    # Test arrays are not used for score fitting, predictions, or metric computation.
    x,y,h=d['X'][train],d['y'][train],d['hosts'][train]
    assert not set(h)&set(d['hosts'][val])
    oof=np.full(len(train),np.nan);assigned=np.zeros(len(train),dtype=bool)
    folds=np.full(len(train),-1,dtype=int);audit=[]
    for i,(a,b) in enumerate(StratifiedGroupKFold(n_splits=4,shuffle=True,random_state=137).split(x,y,h)):
        fitted=pipeline(.001).fit(x[a],y[a])
        z=fitted.decision_function(x[b])
        assign_oof_scores(oof,assigned,a,b,h,z);folds[b]=i
        audit.append({'fold':i,'fit_rows':len(a),'score_rows':len(b),'fit_hosts':sorted(set(h[a])),'score_hosts':sorted(set(h[b])),'host_overlap':0})
    assert assigned.all() and np.isfinite(oof).all() and (folds>=0).all()
    params=fit_platt(oof,y)
    # From here onward fitting is complete. Validation is evaluation only.
    z=base['pipeline'].decision_function(d['X'][val]);raw=expit(z)
    calibrated=calibrate(z,params['slope'],params['intercept'])
    np.testing.assert_allclose(raw,base['pipeline'].predict_proba(d['X'][val])[:,1],atol=1e-15,rtol=0)
    expected={r['record_id']:r['retrained_markdownify'] for r in json.loads(Path('trad_ml_scorer/v7.1/validation_predictions.json').read_text())}
    np.testing.assert_allclose(raw,[expected[str(i)] for i in d['ids'][val]],atol=1e-12,rtol=0)
    evaluated={name:{**metrics(d['y'][val],p,d['hosts'][val]),**reliability(d['y'][val],p)} for name,p in [('v7.1',raw),('v8',calibrated)]}
    differences=paired_differences(d['y'][val],raw,calibrated,d['hosts'][val])
    order=np.argsort(z,kind='stable')
    rank_inversions=int(np.sum(np.diff(calibrated[order])<0))
    new_ties=int(np.sum((np.diff(z[order])>0)&(np.diff(calibrated[order])==0)))
    saturation=int(np.sum((calibrated==0)|(calibrated==1)))
    ranking_ok=all(abs(evaluated['v7.1'][k]-evaluated['v8'][k])<=1e-12 for k in ('roc_auc','mean_within_host_auc'))
    gates={'positive_slope':params['slope']>0,'no_saturation':saturation==0,'no_new_ties':new_ties==0,
           'ranking_preserved':ranking_ok and rank_inversions==0,
           'log_loss_improves':differences['log_loss']['delta']<0,'brier_improves':differences['brier_score']['delta']<0,
           'log_loss_interval_below_zero':differences['log_loss']['high']<0}
    recommend=all(gates.values())
    decision='Recommend v8 for further confirmation; no automatic rollout.' if recommend else 'Retain v7.1 default; v8 calibration remains experimental.'
    np.savez_compressed(OUTPUT/'training_oof.npz',logits=oof,labels=y,hosts=h,record_ids=d['ids'][train],fold=folds)
    provenance={'base_model_path':str(BASE/'model.joblib'),'base_model_sha256':digest(BASE/'model.joblib'),
                'feature_cache_sha256':manifest['features_sha256'],'training_oof_sha256':digest(OUTPUT/'training_oof.npz'),
                'base_feature_code_hashes':base['code_hashes'],'plan_sha256':digest(ROOT/'plan.md'),
                'training_code_sha256':digest(__file__),'training_records':len(train),'training_hosts':len(set(h)),
                'fold_seed':137,'folds':audit,'validation_used_for_calibration_fit':False,'test_evaluated':False}
    artifact={'version':VERSION,'parameters':params,'feature_names':base['feature_names'],
              'base_model_path':provenance['base_model_path'],'base_model_sha256':provenance['base_model_sha256'],
              'provenance':provenance,'inference_code_hashes':{p:digest(p) for p in ('trad_ml_scorer/platt_calibration.py','trad_ml_scorer/predict_platt.py')},
              'decision':decision,'target':'High/low class under balanced host-relative sampling; not citation-event probability'}
    joblib.dump(artifact,OUTPUT/'calibration.joblib')
    restored=load_calibrated_model(OUTPUT/'calibration.joblib')
    reloaded=np.array([scores_from_logit(restored['calibration'],score)['calibrated_high_class_probability'] for score in z])
    np.testing.assert_array_equal(reloaded,calibrated)
    validation=[{'record_id':str(d['ids'][idx]),'hostname':str(d['hosts'][idx]),'label':int(d['y'][idx]),'raw_logit':float(z[i]),'v7_1_probability':float(raw[i]),'v8_probability':float(calibrated[i])} for i,idx in enumerate(val)]
    result={'version':VERSION,'parameters':params,'validation':evaluated,'paired_differences':differences,'gates':gates,
            'decision':decision,'provenance':provenance,'calibration_path':str(OUTPUT/'calibration.joblib'),
            'calibration_sha256':digest(OUTPUT/'calibration.joblib'),
            'diagnostics':{'rank_inversions':rank_inversions,'new_ties':new_ties,'saturation':saturation,
                           'raw_logit_range':[float(z.min()),float(z.max())],
                           'missing_training_features':int(np.isnan(x).sum()),'missing_validation_features':int(np.isnan(d['X'][val]).sum()),
                           'exclusions_added':0,'save_reload_exact_parity':True}}
    (ROOT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    (ROOT/'validation_predictions.json').write_text(json.dumps(validation,indent=2)+'\n')
    print(json.dumps({'parameters':params,'metrics':{k:{n:v[n] for n in ('roc_auc','log_loss','brier_score','ece')} for k,v in evaluated.items()},'paired':differences,'gates':gates,'decision':decision},indent=2))

if __name__=='__main__':main()
