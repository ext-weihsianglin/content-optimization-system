"""Check frozen provenance, preserved population, and training-only transformations."""
import json
import argparse
from pathlib import Path
import joblib
import numpy as np
from trad_ml_scorer.finalize_frontier import sha
from trad_ml_scorer.train_lr import pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('data/raw'))
    args = parser.parse_args()
    root, cache = Path('trad_ml_scorer/v4'), Path('data/trad_ml_scorer/v4')
    selection = json.loads((root/'selection.json').read_text())
    manifest = json.loads((cache/'manifest.json').read_text())
    assert sha(cache/'model.joblib') == selection['model_sha256']
    assert sha(cache/'features.npz') == selection['dataset_sha256']
    assert all(sha(p)==h for p,h in selection['code_hashes'].items())
    data, old = dict(np.load(cache/'features.npz')), dict(np.load('data/trad_ml_scorer/v2/features.npz'))
    assert sha('data/trad_ml_scorer/v2/features.npz') == manifest['source_features_sha256']
    for key in ('ids','y','hosts','splits','clean','common'):
        np.testing.assert_array_equal(data[key],old[key])
    for a,b in [('train','validation'),('train','test'),('validation','test')]:
        assert not set(data['hosts'][data['splits']==a]) & set(data['hosts'][data['splits']==b])
    bundle = joblib.load(cache/'model.joblib')
    cols = [manifest['feature_names'].index(n) for n in bundle['feature_names']]
    train = data['splits']=='train'
    x = data['X'][train][:,cols]
    reproduced = pipeline(bundle['selection']['C']).fit(x,data['y'][train])
    model = bundle['pipeline']
    np.testing.assert_allclose(model[0].statistics_,reproduced[0].statistics_)
    np.testing.assert_allclose(model[1].mean_,reproduced[1].mean_)
    np.testing.assert_allclose(model[1].scale_,reproduced[1].scale_)
    assert int(model[1].n_samples_seen_) == int(train.sum())
    np.testing.assert_allclose(model[-1].coef_,reproduced[-1].coef_,rtol=1e-10,atol=1e-10)
    np.testing.assert_allclose(model[-1].intercept_,reproduced[-1].intercept_,rtol=1e-10,atol=1e-10)
    import duckdb
    from trad_ml_scorer.predict_frontier import predict_frontier
    from trad_ml_scorer.retention_features import parse_snapshot
    from trad_ml_scorer.robust_features import robust_features
    from preprocessing.schema import snapshot_identity
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:
        records = {r['record_id']: r for r in map(json.loads, stream)}
    connection = duckdb.connect()
    examples = []
    for split in ('train','validation'):
        for i in np.flatnonzero(data['splits']==split)[:3]:
            record = records[str(data['ids'][i])]
            raw = connection.execute('SELECT prompt,html_content,href FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(args.input_dir/record['source_file']),record['source_row']]).fetchone()
            prompt,payload,href = raw
            assert snapshot_identity(payload,href)[1] == record['snapshot_id']
            values = robust_features(prompt,parse_snapshot(payload,href))
            np.testing.assert_allclose([values[n] for n in manifest['feature_names']],data['X'][i],equal_nan=True)
            prediction = predict_frontier(bundle,prompt,payload,href)
            expected = model.predict_proba(data['X'][i:i+1][:,cols])[0,1]
            np.testing.assert_allclose(prediction['p_is_cited_high'],expected,atol=1e-12)
            examples.append({'record_id':record['record_id'],'split':split,**prediction})
    (root/'example_predictions.json').write_text(json.dumps(examples,indent=2)+'\n')
    report = {'status':'passed','preserved_v2_rows':len(data['y']),'training_rows':int(train.sum()),'raw_parity_examples':len(examples),
              'checks':['model and feature cache hashes','parser and feature source hashes','exact v2 row/label/split/quality identity','zero host overlap','training-only imputer/scaler and full LR refit parity'],
              'scope':'Cached feature parity for 120 validation documents additionally recorded by stress_frontier. Raw inference parity verified on six train/validation source snapshots; this is not new independent-host evidence.'}
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
