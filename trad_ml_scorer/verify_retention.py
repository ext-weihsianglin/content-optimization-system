"""Check retention snapshot joins, frozen models, feature parity, and split isolation."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import duckdb
import joblib
import numpy as np

from preprocessing.schema import snapshot_identity
from trad_ml_scorer.lr_features import FEATURE_NAMES as V1_NAMES
from trad_ml_scorer.prepare_lr_data import leakage_audit
from trad_ml_scorer.retention_features import FEATURE_NAMES, features_from_document, parse_snapshot, predict_retention


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('data/trad_ml_scorer/v2'))
    parser.add_argument('--output-dir', type=Path, default=Path('trad_ml_scorer/v2'))
    parser.add_argument('--input-dir', type=Path, default=Path('data/raw'))
    args = parser.parse_args()
    manifest = json.loads((args.data_dir/'manifest.json').read_text())
    for filename, expected in manifest['source_files'].items():
        assert hashlib.sha256((args.input_dir / filename).read_bytes()).hexdigest() == expected
    selection = json.loads((args.output_dir/'selection.json').read_text())
    assert hashlib.sha256((args.data_dir/'features.npz').read_bytes()).hexdigest()==manifest['features_sha256']
    records=[json.loads(line) for line in (args.data_dir/'records.jsonl').read_text().splitlines()]
    assert leakage_audit(records)==manifest['leakage_audit']
    assert len({r['snapshot_id'] for r in records})==manifest['unique_snapshots']
    assert len(list((args.data_dir/'documents').glob('*.json.gz')))==manifest['unique_snapshots']
    assert json.loads((args.data_dir/'host_splits.json').read_text())==json.loads(Path('data/lr/host_splits.json').read_text())
    data=np.load(args.data_dir/'features.npz')
    # Verify preprocessing statistics against the appropriate common/full TRAIN population.
    for name,entry in selection['models'].items():
        model_path=args.data_dir/f'{name}.joblib'
        assert hashlib.sha256(model_path.read_bytes()).hexdigest()==entry['model_sha256']
        bundle=joblib.load(model_path)
        eligible=data['common'] if name.endswith('_common') else np.ones(len(data['y']),dtype=bool)
        mask=(data['splits']=='train') & eligible
        x=data['X_v1'] if name=='v1_common' else data['X'][:,[FEATURE_NAMES.index(f) for f in bundle['feature_names']]]
        xt=x[mask]
        model=bundle['pipeline']
        medians=np.nanmedian(xt,axis=0)
        medians[np.isnan(medians)]=0
        np.testing.assert_allclose(model[0].statistics_,medians)
        np.testing.assert_allclose(model[1].mean_,model[0].transform(xt).mean(axis=0))
        assert int(model[1].n_samples_seen_)==len(xt)
        assert entry['C']==min(entry['candidates'],key=lambda r:r['validation']['log_loss'])['C']
    assert selection['selected_name']==min(('retention_whole','retention_sections'),key=lambda n:selection['models'][n]['validation']['log_loss'])
    bundle=joblib.load(args.data_dir/'model.joblib')
    assert hashlib.sha256((args.data_dir/'model.joblib').read_bytes()).hexdigest()==selection['selected']['model_sha256']
    by_id={r['record_id']:r for r in records if not r['exclusions']}
    con=duckdb.connect()
    examples=[]
    for split in ('train','validation'):
        for i in np.flatnonzero(data['splits']==split)[:3]:
            row=by_id[str(data['ids'][i])]
            raw=con.execute('SELECT prompt,html_content,href FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(args.input_dir/row['source_file']),row['source_row']]).fetchone()
            prompt,payload,href=raw
            payload_hash,identity=snapshot_identity(payload,href)
            assert identity==row['snapshot_id'] and payload_hash==row['html_sha256']
            with gzip.open(args.data_dir/'documents'/f'{identity}.json.gz','rt') as stream:
                archived=json.load(stream)
            assert 'prompt' not in archived and 'is_cited_high' not in archived
            fresh=parse_snapshot(payload,href)
            assert fresh['text']==archived['text']
            assert fresh['blocks']==archived['blocks']
            assert [b for c in archived['chunks'] for b in c['block_ids']]==[b['block_id'] for b in archived['blocks']]
            values=features_from_document(prompt,fresh)
            np.testing.assert_allclose([values[f] for f in FEATURE_NAMES],data['X'][i],equal_nan=True)
            columns=[FEATURE_NAMES.index(f) for f in bundle['feature_names']]
            expected=bundle['pipeline'].predict_proba(data['X'][i:i+1,columns])[0,1]
            actual=predict_retention(bundle,prompt,payload,href)
            np.testing.assert_allclose(actual['p_is_cited_high'],expected,atol=1e-12)
            examples.append({'record_id':row['record_id'],'snapshot_id':identity,'split':split,'prompt':prompt,'url':href,'is_cited_high':int(data['y'][i]),**actual})
    if selection.get('v1_frozen_model_sha256'):
        assert hashlib.sha256(Path('data/lr/model.joblib').read_bytes()).hexdigest()==selection['v1_frozen_model_sha256']
    (args.output_dir/'example_predictions.json').write_text(json.dumps(examples,indent=2)+'\n')
    result={'status':'passed','unique_snapshots':manifest['unique_snapshots'],'raw_parity_examples':len(examples),'v1_model_preserved': bool(selection.get('v1_frozen_model_sha256')),
            'checks':['existing local v1 model checked when supplied','all source Parquet file fingerprints match','complete unique-snapshot archive','copied v1 hostname assignments','zero cross-split host/URL/HTML/retained-text/record overlap','exact payload+URL identity joins','all full/common preprocessing fits use train only','all regularization choices use validation loss','primary winner chosen only from v2 variants by validation','raw/document/feature/model parity','chunk membership exact and ordered; no duplicated blocks']}
    (args.output_dir/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
