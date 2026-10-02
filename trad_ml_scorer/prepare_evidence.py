"""Add v5 evidence features to the cached v4 matrix, preserving all row identities."""
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from trad_ml_scorer.evidence_features import evidence_features, VERSION, DESCRIPTIONS, FAMILIES


def main():
    source=Path('data/trad_ml_scorer/v4'); output=Path('data/trad_ml_scorer/v5')
    output.mkdir(parents=True,exist_ok=True)
    if (output/'features.npz').exists():
        raise FileExistsError('Frozen v5 feature cache exists')
    base=json.loads((source/'manifest.json').read_text())
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert digest(source/'features.npz')==base['features_sha256']
    data=dict(np.load(source/'features.npz'))
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:
        records={r['record_id']:r for r in map(json.loads,stream)}
    rows=[]; new_names=None; hashes={}
    for i,identity in enumerate(data['ids']):
        r=records[str(identity)]
        assert r['split']==data['splits'][i] and r['is_cited_high']==data['y'][i]
        path=Path('data/trad_ml_scorer/v2/documents')/(r['snapshot_id']+'.json.gz')
        payload=path.read_bytes(); hashes[path.name]=hashlib.sha256(payload).hexdigest()
        doc=json.loads(gzip.decompress(payload))
        assert doc['snapshot_id']==r['snapshot_id']
        values=evidence_features(r['prompt'],doc)
        if new_names is None:
            new_names=list(values)
        assert list(values)==new_names
        rows.append(list(values.values()))
        if i%1000==0:
            print(i,flush=True)
    data['X']=np.column_stack([data['X'],np.asarray(rows)])
    np.savez_compressed(output/'features.npz',**data)
    baseline=base['feature_names']; families={**base['families'],**FAMILIES}
    variants={'v4_baseline':baseline,**{f'plus_{family}':baseline+names for family,names in FAMILIES.items()},'all_evidence':baseline+new_names}
    code_hashes=json.loads(Path('trad_ml_scorer/v4/selection.json').read_text())['code_hashes']
    for filename in ('trad_ml_scorer/evidence_features.py','trad_ml_scorer/prepare_evidence.py'):
        code_hashes[filename]=digest(Path(filename))
    manifest={'version':VERSION,'base_names':baseline,'feature_names':baseline+new_names,'families':families,
              'variants':variants,'descriptions':{**base['descriptions'],**DESCRIPTIONS},
              'extractor_sha256':digest(Path('trad_ml_scorer/evidence_features.py')),'code_hashes':code_hashes,
              'source_features_sha256':base['features_sha256'],'features_sha256':digest(output/'features.npz'),
              'snapshot_hashes':hashes,'rows':len(rows),'population':'Exactly v4/v2 eligible records and hostname assignments; no reparsing or corpus-fitted feature transforms.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':
    main()
