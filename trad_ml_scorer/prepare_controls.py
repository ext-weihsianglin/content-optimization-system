"""Cache v6 ablations against the selected v5 features, without reparsing."""
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from trad_ml_scorer.control_features import control_features, VERSION, DESCRIPTIONS, FAMILIES, METADATA_MATCHES


def main():
    source=Path('data/trad_ml_scorer/v5'); output=Path('data/trad_ml_scorer/v6')
    output.mkdir(parents=True,exist_ok=True)
    if (output/'features.npz').exists():
        raise FileExistsError('Frozen v6 cache exists')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    previous=json.loads((source/'manifest.json').read_text())
    assert digest(source/'features.npz')==previous['features_sha256']
    baseline=json.loads(Path('trad_ml_scorer/v5/selection.json').read_text())['selected']['feature_names']
    data=dict(np.load(source/'features.npz'))
    indices=[previous['feature_names'].index(n) for n in baseline]
    original=data['X'][:,indices]
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:
        records={r['record_id']:r for r in map(json.loads,stream)}
    rows=[]; names=None
    for i,identity in enumerate(data['ids']):
        r=records[str(identity)]; filename=r['snapshot_id']+'.json.gz'
        payload=(Path('data/trad_ml_scorer/v2/documents')/filename).read_bytes()
        assert hashlib.sha256(payload).hexdigest()==previous['snapshot_hashes'][filename]
        doc=json.loads(gzip.decompress(payload))
        assert doc['snapshot_id']==r['snapshot_id']
        values=control_features(r['prompt'],doc,dict(zip(baseline,original[i])))
        if names is None:names=list(values)
        assert list(values)==names
        rows.append(list(values.values()))
        if i%1000==0:print(i,flush=True)
    data['X']=np.column_stack([original,np.asarray(rows)])
    np.savez_compressed(output/'features.npz',**data)
    without_metadata=[n for n in baseline if n not in METADATA_MATCHES]
    normalized_supported={n.removeprefix('supported_') for n in FAMILIES['combined_support']}
    variants={'v5_baseline':baseline,
              'corroboration':without_metadata+FAMILIES['corroboration'],
              'long_prose':baseline+FAMILIES['long_prose'],
              'normalization':baseline+FAMILIES['normalization'],
              'combined':without_metadata+FAMILIES['corroboration']+FAMILIES['long_prose']+[n for n in FAMILIES['normalization'] if n not in normalized_supported]+FAMILIES['combined_support']}
    hashes=dict(previous['code_hashes'])
    for filename in ('trad_ml_scorer/control_features.py','trad_ml_scorer/prepare_controls.py'):
        hashes[filename]=digest(Path(filename))
    manifest={'version':VERSION,'base_names':baseline,'feature_names':baseline+names,'variants':variants,
              'families':{**previous['families'],**FAMILIES},'descriptions':{**previous['descriptions'],**DESCRIPTIONS},
              'code_hashes':hashes,'extractor_sha256':digest(Path('trad_ml_scorer/control_features.py')),
              'source_features_sha256':previous['features_sha256'],'features_sha256':digest(output/'features.npz'),
              'snapshot_hashes':previous['snapshot_hashes'],'rows':len(rows),'population':'Exactly v5 rows and hostname assignments; first 96 columns are selected v5 features.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':main()
