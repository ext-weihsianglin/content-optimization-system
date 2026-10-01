"""Build v4 from retained snapshots; no raw data parsing or eligibility changes."""
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from trad_ml_scorer.robust_features import robust_features, VERSION
from trad_ml_scorer.frontier_features import DESCRIPTIONS, FAMILIES
from trad_ml_scorer.retention_features import FEATURE_NAMES


def main():
    source, output = Path('data/trad_ml_scorer/v2'), Path('data/trad_ml_scorer/v4')
    output.mkdir(parents=True, exist_ok=True)
    if (output/'features.npz').exists():
        raise FileExistsError('Frozen v4 cache exists')
    with (source/'records.jsonl').open() as stream:
        records = {r['record_id']:r for r in map(json.loads,stream)}
    data = dict(np.load(source/'features.npz'))
    rows, names = [], None
    for i,identity in enumerate(data['ids']):
        record = records[str(identity)]
        with gzip.open(source/'documents'/(record['snapshot_id']+'.json.gz'),'rt') as stream:
            doc = json.load(stream)
        assert doc['snapshot_id'] == record['snapshot_id']
        values = robust_features(record['prompt'],doc)
        if names is None:
            names = list(values)
        assert list(values) == names
        rows.append(list(values.values()))
        if i % 1000 == 0:
            print(i,flush=True)
    data['X'] = np.asarray(rows)
    np.savez_compressed(output/'features.npz',**data)
    manifest = {'version':VERSION,'base_names':FEATURE_NAMES,'feature_names':names,'descriptions':DESCRIPTIONS,'families':FAMILIES,
                'source_features_sha256':hashlib.sha256((source/'features.npz').read_bytes()).hexdigest(),
                'extractor_sha256':hashlib.sha256(Path('trad_ml_scorer/robust_features.py').read_bytes()).hexdigest(),
                'features_sha256':hashlib.sha256((output/'features.npz').read_bytes()).hexdigest(), 'rows':len(rows),
                'population':'Exactly v2 eligible rows and hostname assignments. Scoring view suppresses repeated/unsupported headings; parser documents unchanged.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__ == '__main__':
    main()
