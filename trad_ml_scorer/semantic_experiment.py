"""Bounded semantic-similarity LR comparison; never predicts on test rows."""
import json
from pathlib import Path
import warnings
import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from trad_ml_scorer.feature_dependencies import feature_group
from trad_ml_scorer.prepare_semantic import digest
from trad_ml_scorer.semantic_features import FIELDS, NAMES
from trad_ml_scorer.train_lr import pipeline
from trad_ml_scorer.lr_evaluation import metrics


def paired_auc_interval(y, candidate, baseline, hosts, repeats=1000):
    rng = np.random.default_rng(142)
    groups = [np.flatnonzero(hosts==h) for h in np.unique(hosts)]
    deltas = []
    for _ in range(repeats):
        selected = np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
        if len(np.unique(y[selected])) == 2:
            deltas.append(roc_auc_score(y[selected],candidate[selected])-roc_auc_score(y[selected],baseline[selected]))
    return {'delta':float(roc_auc_score(y,candidate)-roc_auc_score(y,baseline)),
            'low':float(np.quantile(deltas,.025)),'high':float(np.quantile(deltas,.975)),'replicates':len(deltas)}


def main():
    warnings.filterwarnings('error', category=ConvergenceWarning)
    source = Path('data/trad_ml_scorer/v7')
    output = Path('trad_ml_scorer/v7')
    if (output/'results.json').exists():
        raise FileExistsError('Experiment frozen; use a new version')
    manifest = json.loads((source/'manifest.json').read_text())
    assert digest(source/'features.npz') == manifest['features_sha256']
    assert digest(Path('data/trad_ml_scorer/v5/features.npz')) == manifest['base_features_sha256']
    semantic = dict(np.load(source/'features.npz'))
    sparse = dict(np.load('data/trad_ml_scorer/v5/features.npz'))
    sparse_manifest = json.loads(Path('data/trad_ml_scorer/v5/manifest.json').read_text())
    frozen = joblib.load('data/trad_ml_scorer/v5/model.joblib')
    for key in ('ids','hosts','splits','y'):
        np.testing.assert_array_equal(semantic[key],sparse[key])
    base_names = frozen['feature_names']
    base = sparse['X'][:,[sparse_manifest['feature_names'].index(n) for n in base_names]]
    context_names = [n for n in base_names if feature_group(n) in ('prompt','doc')]
    assert len(context_names) == 45
    context = base[:,[base_names.index(n) for n in context_names]]
    designs = {
        'v5_reference':(base,base_names,[.01]),
        'semantic_fields':(semantic['X'][:,:len(FIELDS)],FIELDS,[.001,.01,.1,1.,10.]),
        'semantic_sections':(semantic['X'],NAMES,[.001,.01,.1,1.,10.]),
        'semantic_context':(np.column_stack([semantic['X'],context]),NAMES+context_names,[.001,.01,.1,1.,10.]),
    }
    train = np.flatnonzero(semantic['splits']=='train')
    val = np.flatnonzero(semantic['splits']=='validation')
    y, hosts = semantic['y'], semantic['hosts']
    folds = list(StratifiedGroupKFold(n_splits=4,shuffle=True,random_state=137).split(semantic['X'][train],y[train],hosts[train]))
    fold_assignment = {}
    for fold,(a,b) in enumerate(folds):
        assert not set(hosts[train[a]]) & set(hosts[train[b]])
        for h in np.unique(hosts[train[b]]):
            assert h not in fold_assignment
            fold_assignment[str(h)] = fold
    finalists, candidates, predictions = [], [], {}
    for variant,(matrix,names,grid) in designs.items():
        entries = []
        for c in grid:
            scores = []
            for a,b in folds:
                fitted = pipeline(c).fit(matrix[train[a]],y[train[a]])
                scores.append(float(roc_auc_score(y[train[b]],fitted.predict_proba(matrix[train[b]])[:,1])))
            entry = {'variant':variant,'C':c,'cv_auc':float(np.mean(scores)),'fold_auc':scores}
            entries.append(entry);candidates.append(entry)
            print(json.dumps(entry),flush=True)
        chosen = max(entries,key=lambda r:(r['cv_auc'],-r['C']))
        fitted = pipeline(chosen['C']).fit(matrix[train],y[train])
        probabilities = fitted.predict_proba(matrix[val])[:,1]
        if variant == 'v5_reference':
            np.testing.assert_allclose(probabilities,frozen['pipeline'].predict_proba(matrix[val])[:,1],atol=1e-12,rtol=0)
        predictions[variant] = probabilities
        common = semantic['available'][val]
        finalized = {**chosen,'raw_features':len(names),'feature_names':names,
                     'validation':metrics(y[val],probabilities,hosts[val]),
                     'common_available_validation':metrics(y[val][common],probabilities[common],hosts[val][common])}
        bundle = {'pipeline':fitted,'feature_names':names,'version':'lr-semantic-v7','variant':variant,
                  'selection':chosen,'embedding_run':manifest['run'],'embedding_model':manifest['model'],
                  'serializer_version':manifest['serializer_version'],'source_hashes':manifest['source_hashes'],
                  'features_sha256':manifest['features_sha256'],'input_contract':'Precomputed original-space semantic features; semantic_context also requires unchanged v5 document/prompt context columns.'}
        joblib.dump(bundle,source/f'{variant}.joblib')
        finalized['model_sha256'] = digest(source/f'{variant}.joblib')
        finalists.append(finalized)
    selected = max([r for r in finalists if r['variant']!='v5_reference'],key=lambda r:r['cv_auc'])
    for row in finalists:
        row['validation_auc_delta_vs_v5'] = paired_auc_interval(y[val],predictions[row['variant']],predictions['v5_reference'],hosts[val])
    result = {'version':'lr-semantic-v7','plan_sha256':digest(output/'plan.md'),
              'selection_rule':'Choose C and semantic variant by training grouped CV ROC-AUC only. Validation is descriptive. No promotion or test evaluation.',
              'selected_semantic_variant':selected['variant'],'candidates':candidates,'finalists':finalists,
              'training_host_folds':fold_assignment,'test_evaluated':False,'test_metadata_audited':True,
              'manifest':manifest,'code_hashes':{str(p):digest(p) for p in map(Path,['trad_ml_scorer/semantic_experiment.py','trad_ml_scorer/train_lr.py'])}}
    (output/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    prediction_rows = [{'record_id':str(semantic['ids'][i]),'hostname':str(hosts[i]),'label':int(y[i]),
                        **{variant:float(p[j]) for variant,p in predictions.items()}} for j,i in enumerate(val)]
    (output/'validation_predictions.json').write_text(json.dumps(prediction_rows,indent=2)+'\n')
    print('Selected semantic prototype:',selected['variant'])
    print(json.dumps([{k:r[k] for k in ('variant','cv_auc','validation','validation_auc_delta_vs_v5')} for r in finalists],indent=2))

if __name__=='__main__':main()
