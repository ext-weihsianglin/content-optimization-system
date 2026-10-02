"""Check saved-document/raw-HTML feature and prediction parity on fixed validation rows."""
import gzip
import json
from pathlib import Path
import duckdb
import joblib
import numpy as np
from preprocessing.offline import network_disabled
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.markdownify_context import FEATURE_ORDER, feature_row
from trad_ml_scorer.semantic_features import NAMES
from trad_ml_scorer.retrain_markdownify import DATA, CORPUS, OUTPUT, REPORT, CODE
from trad_ml_scorer.prepare_semantic import digest
from trad_ml_scorer.predict_markdownify import load_model, predict_document


def main():
    model=load_model(OUTPUT/'model.joblib')
    manifest=json.loads((OUTPUT/'manifest.json').read_text())
    assert model['feature_names']==FEATURE_ORDER
    assert {p:digest(p) for p in CODE}==model['code_hashes']
    assert digest(OUTPUT/'features.npz')==manifest['features_sha256']
    data=np.load(OUTPUT/'features.npz')
    with open(DATA/'trad_ml_scorer/v2/records.jsonl') as stream:
        records={r['record_id']:r for r in map(json.loads,stream)}
    candidates=[i for i,identity in enumerate(data['ids']) if data['splits'][i]=='validation' and data['X'][i,FEATURE_ORDER.index('format_html')]==1]
    selected=sorted(candidates,key=lambda i:str(data['ids'][i]))[:20]
    con=duckdb.connect();checks=[]
    for i in selected:
        record=records[str(data['ids'][i])]
        raw=DATA/'raw'/record['source_file']
        # File identities are frozen by the export; verify before use.
        assert digest(raw)==record['source_file_hash']
        payload,href,host,prompt=con.execute('SELECT html_content,href,hostname,prompt FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(raw),record['source_row']]).fetchone()
        assert (href,host,prompt)==(record['href'],record['hostname'],record['prompt'])
        with gzip.open(CORPUS/'documents'/(record['snapshot_id']+'.json.gz'),'rt') as stream:
            saved=json.load(stream)
        with network_disabled():
            parsed=parse_snapshot(payload,href,host)
        assert parsed['snapshot_id']==record['snapshot_id']
        scores=dict(zip(NAMES,data['X'][i,:10]))
        a=feature_row(prompt,saved,scores);b=feature_row(prompt,parsed,scores)
        np.testing.assert_allclose(a,data['X'][i],rtol=0,atol=1e-12,equal_nan=True)
        np.testing.assert_allclose(a,b,rtol=0,atol=1e-12,equal_nan=True)
        pa=model['pipeline'].predict_proba(a[None,:])[0,1];pb=predict_document(model,prompt,parsed,scores)
        np.testing.assert_allclose(pa,pb,atol=1e-12,rtol=0)
        finite=np.isfinite(a)&np.isfinite(b)
        checks.append({'record_id':record['record_id'],'snapshot_id':record['snapshot_id'],
                       'max_feature_delta':float(np.max(abs(a[finite]-b[finite]))),
                       'probability_delta':float(abs(pa-pb))})
    identity=json.loads((CORPUS/'run_identity.json').read_text())
    parser_checks={p:{'corpus_sha256':identity['source_fingerprints'][p],'current_sha256':digest(p)} for p in (
        'preprocessing/blocks.py','preprocessing/markdownify_serializer.py','preprocessing/adapters/local.py',
        'preprocessing/quality.py','preprocessing/downstream.py','preprocessing/select.py','trad_ml_scorer/retention_features.py')}
    report={'scope':'20 fixed validation HTML records. All context features recomputed; existing semantic scores reused. No embedding regeneration or webapp execution.',
            'rows':len(checks),'checks':checks,'parser_fingerprints':parser_checks,
            'all_checked_parser_files_match_corpus':all(v['corpus_sha256']==v['current_sha256'] for v in parser_checks.values()),
            'model_sha256':digest(OUTPUT/'model.joblib'),'verification_code_sha256':digest(__file__)}
    (REPORT/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('checks','parser_fingerprints')},indent=2))

if __name__=='__main__':main()
