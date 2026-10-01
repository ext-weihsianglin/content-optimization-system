"""Fixed-prompt/document-edit interpretation of the frozen v5 LR; no fitting/test use."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import duckdb
import joblib
import numpy as np
from trad_ml_scorer.fixed_prompt_edits import contrast,make_edit,feature_group
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.robust_features import robust_features
from trad_ml_scorer.evidence_features import evidence_features

ACTIONS=('title_from_existing_h1','relevant_paragraph_first','split_long_paragraph')


def matched_support(records):
    result={}
    for scope,keys in [('prompt',('prompt_hash',)),('prompt_and_host',('hostname','prompt_hash'))]:
        groups=defaultdict(list)
        for row in records:groups[tuple(row[k] for k in keys)].append(row)
        repeated=[g for g in groups.values() if len(g)>1]
        mixed=[g for g in repeated if len({r['is_cited_high'] for r in g})>1]
        result[scope]={'repeated_groups':len(repeated),'repeated_rows':sum(map(len,repeated)),
                       'mixed_label_groups':len(mixed),'mixed_label_rows':sum(map(len,mixed))}
    return result


def bootstrap_delta(rows):
    hosts=sorted({r['hostname'] for r in rows})
    values=np.array([r['delta_probability'] for r in rows])
    result={'rows':len(rows),'hosts':len(hosts),'mean_delta':float(values.mean()),'median_delta':float(np.median(values)),
            'min_delta':float(values.min()),'max_delta':float(values.max()),'positive_fraction':float(np.mean(values>0))}
    if len(hosts)>=5:
        groups=[np.flatnonzero(np.array([r['hostname'] for r in rows])==h) for h in hosts]
        rng=np.random.default_rng(941);means=[]
        for _ in range(1000):
            indices=np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
            means.append(float(values[indices].mean()))
        result['mean_host_bootstrap_95']=[float(np.quantile(means,.025)),float(np.quantile(means,.975))]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=Path('data/raw'))
    parser.add_argument('--output-dir',type=Path,default=Path('trad_ml_scorer/interpretation/fixed_prompt'))
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    if (args.output_dir/'analysis.json').exists():raise FileExistsError('Interpretation already frozen')
    cache=Path('data/trad_ml_scorer/v5');bundle=joblib.load(cache/'model.joblib')
    selection=json.loads(Path('trad_ml_scorer/v5/selection.json').read_text())
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(cache/'model.joblib')==selection['model_sha256']
    assert all(sha(Path(p))==h for p,h in bundle['code_hashes'].items())
    manifest=json.loads((cache/'manifest.json').read_text());assert sha(cache/'features.npz')==manifest['features_sha256']
    data=dict(np.load(cache/'features.npz'));names=bundle['feature_names'];cols=[manifest['feature_names'].index(n) for n in names]
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:records={r['record_id']:r for r in map(json.loads,stream)}
    val=np.flatnonzero(data['splits']=='validation');validation_rows=[records[str(data['ids'][i])] for i in val]
    model=bundle['pipeline'];con=duckdb.connect();edits=[];skipped=[];sampled=[]
    def vector(prompt,doc):
        values={**robust_features(prompt,doc),**evidence_features(prompt,doc)}
        return np.array([values[n] for n in names])
    for i in sorted(val,key=lambda i:str(data['ids'][i])):
        row=records[str(data['ids'][i])]
        import gzip
        with gzip.open(f'data/trad_ml_scorer/v2/documents/{row["snapshot_id"]}.json.gz','rt') as f:doc=json.load(f)
        if doc['source']['format']!='html':continue
        prompt,payload,href=con.execute('SELECT prompt,html_content,href FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(args.input_dir/row['source_file']),row['source_row']]).fetchone()
        fresh=parse_snapshot(payload,href);assert fresh['snapshot_id']==row['snapshot_id']
        before=vector(prompt,fresh);np.testing.assert_allclose(before,data['X'][i,cols],equal_nan=True)
        sampled.append(row['record_id'])
        # Use a serialization-only control to separate DOM library rewriting from the edit.
        from bs4 import BeautifulSoup
        serialized=str(BeautifulSoup(payload,'html.parser'))
        control=vector(prompt,parse_snapshot(serialized,href))
        control_probability=float(model.predict_proba(control.reshape(1,-1))[0,1])
        original_probability=float(model.predict_proba(before.reshape(1,-1))[0,1])
        for action in ACTIONS:
            changed,detail=make_edit(payload,prompt,action)
            if changed is None:
                skipped.append({'record_id':row['record_id'],'action':action,'reason':detail});continue
            after=vector(prompt,parse_snapshot(changed,href))
            change=contrast(model,names,before,after)
            change['contributions']=[r for r in change['contributions'] if abs(r['delta_log_odds'])>1e-12]
            change.update(record_id=row['record_id'],snapshot_id=row['snapshot_id'],hostname=row['hostname'],prompt=prompt,url=href,
                          action=action,detail=detail,delta_probability=change['after_probability']-change['before_probability'],
                          serialization_delta_probability=control_probability-original_probability,
                          edit_over_serialized_probability=change['after_probability']-control_probability,
                          group_delta_log_odds={group:sum(r['delta_log_odds'] for r in change['contributions'] if r['group']==group) for group in ('HTML document','Prompt × HTML','Fixed prompt','Fixed URL','Parser/source diagnostics')})
            edits.append(change)
        print('Checked',len(sampled),'validation HTML snapshots',flush=True)
        if len(sampled)==40:break
    summary={}
    for action in ACTIONS:
        applicable=[r for r in edits if r['action']==action]
        summary[action]=bootstrap_delta(applicable) if applicable else {'rows':0,'hosts':0}
        summary[action]['not_applicable']=sum(r['action']==action for r in skipped)
    result={'model':'frozen selected v5 (retained by v6)','model_sha256':selection['model_sha256'],
            'split':'validation only','test_used':False,'refit':False,'sample_rule':'first 40 hash-sorted validation HTML records; no selection by labels or score gains',
            'sample_record_ids':sampled,'matched_support':matched_support(validation_rows),'feature_groups':{n:feature_group(n) for n in names},
            'summary':summary,'edits':edits,'not_applicable':skipped,
            'checks':['raw/cache feature parity for every original sample','body word multiset preserved for every applicable edit','prompt and URL contributions exactly zero','all transformed-feature deltas sum to exact LR logit change','serialization-only control recorded'],
            'limitations':['Lexical rearrangement is not factual verification or guaranteed readability improvement.','Bootstrap intervals are conditional on this small, selected development sample and frozen model.','Scores predict the sampled within-host high class among already-cited pages, not citation occurrence probability.']}
    (args.output_dir/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
