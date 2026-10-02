"""Rebuild and refit fixed v7 using the immutable Markdownify corpus, offline."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from importlib.metadata import version
import gzip
import json
from pathlib import Path
import warnings
import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from preprocessing.corpus import validate_document
from trad_ml_scorer.markdownify_context import VERSION, FEATURE_ORDER, CONTEXT_NAMES, feature_row
from trad_ml_scorer.prepare_semantic import digest
from trad_ml_scorer.semantic_features import NAMES, validate_join
from trad_ml_scorer.semantic_experiment import paired_auc_interval
from trad_ml_scorer.lr_evaluation import metrics
from trad_ml_scorer.train_lr import pipeline

DATA = Path('/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system')
CORPUS = DATA/'processed/markdownify-corpus-v1-complete'
OUTPUT = DATA/'trad_ml_scorer/v7.1'
REPORT = Path('trad_ml_scorer/v7.1')
CODE = ['trad_ml_scorer/markdownify_context.py','trad_ml_scorer/robust_features.py',
        'trad_ml_scorer/frontier_features.py','trad_ml_scorer/retention_features.py',
        'scripts/analyze_content.py','scripts/analyze_quality.py']


def build_one(task):
    record, path, expected_sha, run_identity, semantic = task
    if digest(path) != expected_sha:
        raise ValueError('Document bytes differ from corpus manifest: '+record['snapshot_id'])
    with gzip.open(path, 'rt') as stream:
        doc = json.load(stream)
    validate_document(doc,record['snapshot_id'],record['html_sha256'],run_identity)
    if doc['source']['href'] != record['href']:
        raise ValueError('Document URL mismatch')
    values = feature_row(record['prompt'],doc,dict(zip(NAMES,semantic)))
    return values, {'record_id':record['record_id'],'snapshot_id':record['snapshot_id'],
                    'source_file_hash':record['source_file_hash'],'source_row':record['source_row'],
                    'document_sha256':expected_sha,'document_content_hash':doc['extraction']['content_hash']}


def prepare(args):
    baseline = DATA/'trad_ml_scorer/v7'
    manifest = json.loads((baseline/'manifest.json').read_text())
    semantic = dict(np.load(baseline/'features.npz'))
    assert digest(baseline/'features.npz') == manifest['features_sha256']
    assert digest(baseline/'joined_records.jsonl') == manifest['joined_records_sha256']
    corpus_manifest = json.loads((CORPUS/'manifest.json').read_text())
    assert corpus_manifest['status']=='complete'
    assert json.loads((CORPUS/'run_identity.json').read_text())['pipeline_version']=='retention-markdownify-corpus-v1'
    for name,sha in manifest['corpus_hashes'].items():
        assert digest(CORPUS/name)==sha,name
    # The upstream embedding run records every compressed source document hash.
    upstream_path = Path(manifest['run'])/'manifest.json'
    upstream = json.loads(upstream_path.read_text())
    with open(DATA/'trad_ml_scorer/v2/records.jsonl') as stream:
        records={r['record_id']:r for r in map(json.loads,stream)}
    with open(baseline/'joined_records.jsonl') as stream:
        joins={r['record_id']:r for r in map(json.loads,stream)}
    import duckdb
    con=duckdb.connect()
    cursor=con.execute('SELECT * FROM read_parquet(?)',[str(Path(manifest['run'])/'associations.parquet')])
    keys=[d[0] for d in cursor.description]
    associations={ (r['source_file_hash'],r['source_row']):r for r in (dict(zip(keys,row)) for row in cursor.fetchall())}
    assert digest(Path(manifest['run'])/'associations.parquet') == manifest['source_hashes']['associations.parquet']
    tasks=[]
    for i,identity in enumerate(semantic['ids']):
        record=records[str(identity)]
        association=associations[record['source_file_hash'],record['source_row']]
        validate_join(record,association)
        assert joins[str(identity)]['snapshot_id']==record['snapshot_id']
        assert joins[str(identity)]['extraction_id']==association['extraction_id']
        assert record['split']==semantic['splits'][i] and record['is_cited_high']==semantic['y'][i] and record['hostname']==semantic['hosts'][i]
        relative='documents/'+record['snapshot_id']+'.json.gz'
        tasks.append((record,CORPUS/relative,upstream['upstream']['hashes'][relative],corpus_manifest['run_identity'],semantic['X'][i]))
    if (OUTPUT/'manifest.json').exists():
        raise FileExistsError('Corrected feature cache already exists; use --reuse-features')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    # Per-row checkpoints permit interruption recovery without repeating completed work.
    checkpoints=OUTPUT/'context_checkpoints';checkpoints.mkdir(exist_ok=True)
    identity={'version':VERSION,'corpus_manifest_sha256':digest(CORPUS/'manifest.json'),
              'baseline_features_sha256':manifest['features_sha256'],'code_hashes':{p:digest(p) for p in CODE},
              'preparation_code_sha256':digest(__file__)}
    identity_path=OUTPUT/'preparation_identity.json'
    if identity_path.exists():
        assert json.loads(identity_path.read_text())==identity,'Checkpoint identity changed; use a new version'
    else:identity_path.write_text(json.dumps(identity,indent=2)+'\n')
    values=[None]*len(tasks);provenance=[None]*len(tasks);pending=[]
    for i,task in enumerate(tasks):
        p=checkpoints/(str(semantic['ids'][i])+'.json')
        if p.exists():
            cached=json.loads(p.read_text());values[i]=cached['values'];provenance[i]=cached['provenance']
            assert cached['provenance']['document_sha256']==task[2]
        else:pending.append(i)
    print('Context records pending:',len(pending),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for count,(i,result) in enumerate(zip(pending,pool.map(build_one,(tasks[i] for i in pending),chunksize=4)),1):
            row,meta=result;values[i]=row.tolist();provenance[i]=meta
            p=checkpoints/(str(semantic['ids'][i])+'.json')
            temp=p.with_suffix('.tmp');temp.write_text(json.dumps({'values':values[i],'provenance':meta})+'\n');temp.replace(p)
            if count%250==0:print('Rebuilt',count,'/',len(pending),flush=True)
    matrix=np.asarray(values,dtype=float)
    np.testing.assert_array_equal(matrix[:,:10],semantic['X'])
    model=joblib.load(baseline/'semantic_context.joblib');assert FEATURE_ORDER==model['feature_names']
    source=np.load(DATA/'trad_ml_scorer/v5/features.npz')
    sm=json.loads((DATA/'trad_ml_scorer/v5/manifest.json').read_text())
    assert digest(DATA/'trad_ml_scorer/v5/features.npz')==manifest['base_features_sha256']
    np.testing.assert_array_equal(source['ids'],semantic['ids'])
    old_context=source['X'][:,[sm['feature_names'].index(n) for n in CONTEXT_NAMES]]
    old_matrix=np.column_stack([semantic['X'],old_context])
    development=semantic['splits']!='test'
    drift=[]
    for j,name in enumerate(CONTEXT_NAMES):
        old,new=old_context[development,j],matrix[development,10+j]
        changed=~np.isclose(old,new,atol=1e-12,rtol=0,equal_nan=True)
        both=np.isfinite(old)&np.isfinite(new)
        drift.append({'feature':name,'changed_development_rows':int(changed.sum()),
                      'max_absolute_delta':float(np.max(np.abs(new[both]-old[both]))) if both.any() else None,
                      'old_missing':int(np.isnan(old).sum()),'new_missing':int(np.isnan(new).sum())})
    np.savez_compressed(OUTPUT/'features.npz',X=matrix,old_X=old_matrix,**{k:semantic[k] for k in ('ids','y','hosts','splits')})
    with (OUTPUT/'joined_records.jsonl').open('w') as stream:
        for row in provenance:stream.write(json.dumps(row)+'\n')
    prepared={**identity,'feature_names':FEATURE_ORDER,'context_names':CONTEXT_NAMES,'rows':len(matrix),
              'splits':{s:int(sum(semantic['splits']==s)) for s in np.unique(semantic['splits'])},
              'additional_exclusions':0,'semantic_columns_unchanged':True,'drift':drift,
              'corpus':str(CORPUS),'corpus_run_identity':corpus_manifest['run_identity'],
              'embedding_run':manifest['run'],'embedding_model':model['embedding_model'],
              'serializer_version':model['serializer_version'],'source_hashes':manifest['source_hashes'],
              'features_sha256':digest(OUTPUT/'features.npz'),'joined_records_sha256':digest(OUTPUT/'joined_records.jsonl'),
              'upstream_manifest_sha256':digest(upstream_path),'baseline_model_sha256':digest(baseline/'semantic_context.joblib'),
              'dependencies':{n:version(n) for n in ('numpy','scikit-learn','markdownify','beautifulsoup4','lxml')}}
    (OUTPUT/'manifest.json').write_text(json.dumps(prepared,indent=2)+'\n')
    return prepared


def train():
    if (REPORT/'results.json').exists():raise FileExistsError('Results already frozen')
    m=json.loads((OUTPUT/'manifest.json').read_text())
    assert digest(OUTPUT/'features.npz')==m['features_sha256']
    assert {p:digest(p) for p in CODE}==m['code_hashes']
    data=np.load(OUTPUT/'features.npz');x,y,h=data['X'],data['y'],data['hosts']
    tr=np.flatnonzero(data['splits']=='train');va=np.flatnonzero(data['splits']=='validation')
    te=np.flatnonzero(data['splits']=='test')
    assert not (set(h[tr])&set(h[va]) or set(h[tr])&set(h[te]) or set(h[va])&set(h[te]))
    folds=list(StratifiedGroupKFold(n_splits=4,shuffle=True,random_state=137).split(x[tr],y[tr],h[tr]))
    cv=[]
    for a,b in folds:
        assert not set(h[tr[a]])&set(h[tr[b]])
        model=pipeline(.001).fit(x[tr[a]],y[tr[a]])
        cv.append(float(roc_auc_score(y[tr[b]],model.predict_proba(x[tr[b]])[:,1])))
    model=pipeline(.001).fit(x[tr],y[tr])
    old_path=DATA/'trad_ml_scorer/v7/semantic_context.joblib'
    assert digest(old_path)==m['baseline_model_sha256']
    old=joblib.load(old_path)
    prediction={'original_v7':old['pipeline'].predict_proba(data['old_X'][va])[:,1],
                'old_model_markdownify_inputs':old['pipeline'].predict_proba(x[va])[:,1],
                'retrained_markdownify':model.predict_proba(x[va])[:,1]}
    # Verify the frozen baseline before comparing the changed parser contract.
    prior=json.loads(Path('trad_ml_scorer/v7/validation_predictions.json').read_text())
    expected={r['record_id']:r['semantic_context'] for r in prior}
    np.testing.assert_allclose(prediction['original_v7'],[expected[str(i)] for i in data['ids'][va]],atol=1e-12,rtol=0)
    artifact={'pipeline':model,'version':VERSION,'variant':'semantic_context','feature_names':FEATURE_ORDER,
              'selection':{'C':.001,'rule':'Fixed adopted v7 recipe; only context parser corrected','cv_auc':float(np.mean(cv))},
              'input_contract':{'context_serializer':'markdownify-structured-v1','block_schema':'dom-blocks-v3',
                                'assembly_function':'trad_ml_scorer.markdownify_context.feature_row',
                                'source_inventory_required':True,'semantic_scores_must_match_current_prompt_and_document':True},
              'provenance':m,'code_hashes':m['code_hashes'],'embedding_model':m['embedding_model'],
              'serializer_version':m['serializer_version'],'embedding_run':m['embedding_run']}
    if (OUTPUT/'model.joblib').exists():raise FileExistsError('Model already exists')
    joblib.dump(artifact,OUTPUT/'model.joblib')
    restored=joblib.load(OUTPUT/'model.joblib')
    np.testing.assert_array_equal(restored['pipeline'].predict_proba(x[va])[:,1],prediction['retrained_markdownify'])
    results={'version':VERSION,'C':.001,'cv_auc':float(np.mean(cv)),'fold_auc':cv,
             'validation':{name:metrics(y[va],p,h[va]) for name,p in prediction.items()},
             'paired_validation_delta':{name:paired_auc_interval(y[va],p,prediction['original_v7'],h[va]) for name,p in prediction.items() if name!='original_v7'},
             'model_path':str(OUTPUT/'model.joblib'),'model_sha256':digest(OUTPUT/'model.joblib'),
             'test_evaluated':False,'manifest':m,'plan_sha256':digest(REPORT/'plan.md'),
             'training_code_sha256':digest(__file__)}
    REPORT.mkdir(exist_ok=True)
    (REPORT/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    rows=[{'record_id':str(data['ids'][i]),'hostname':str(h[i]),'label':int(y[i]),**{n:float(p[j]) for n,p in prediction.items()}} for j,i in enumerate(va)]
    (REPORT/'validation_predictions.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps({k:results[k] for k in ('cv_auc','validation','paired_validation_delta')},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--reuse-features',action='store_true')
    args=parser.parse_args()
    warnings.filterwarnings('error',category=ConvergenceWarning)
    if not args.reuse_features:prepare(args)
    train()

if __name__=='__main__':main()
