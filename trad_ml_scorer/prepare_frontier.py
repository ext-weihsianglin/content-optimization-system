"""Derive richer features from the existing cache, without rerunning parsing."""
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from trad_ml_scorer.frontier_features import richer_features, DESCRIPTIONS, FAMILIES, VERSION
from trad_ml_scorer.retention_features import FEATURE_NAMES


def main():
    source = Path('data/trad_ml_scorer/v2')
    output = Path('data/trad_ml_scorer/v3')
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'features.npz').exists():
        raise FileExistsError('Frozen feature cache already exists')
    with (source / 'records.jsonl').open() as stream:
        records = {r['record_id']: r for r in map(json.loads, stream)}
    data = dict(np.load(source / 'features.npz'))
    rows, names = [], None
    for i, identity in enumerate(data['ids']):
        record = records[str(identity)]
        with gzip.open(source / 'documents' / (record['snapshot_id'] + '.json.gz'), 'rt') as stream:
            doc = json.load(stream)
        assert doc['snapshot_id'] == record['snapshot_id']
        values = richer_features(record['prompt'], doc)
        if names is None:
            names = list(values)
        assert list(values) == names
        rows.append(list(values.values()))
        if i % 1000 == 0:
            print(f'{i}/{len(data["ids"])} derived from cache', flush=True)
    data['X'] = np.column_stack([data['X'], np.asarray(rows)])
    np.savez_compressed(output / 'features.npz', **data)
    manifest = {'version': VERSION, 'base_names': FEATURE_NAMES, 'feature_names': FEATURE_NAMES + names,
                'descriptions': DESCRIPTIONS, 'families': FAMILIES,
                'source_features_sha256': hashlib.sha256((source/'features.npz').read_bytes()).hexdigest(),
                'extractor_sha256': hashlib.sha256(Path('trad_ml_scorer/frontier_features.py').read_bytes()).hexdigest(),
                'features_sha256': hashlib.sha256((output/'features.npz').read_bytes()).hexdigest(),
                'rows': len(rows), 'population': 'Exactly v2 eligible rows, IDs, labels and hostname assignments; no reparsing'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')

if __name__ == '__main__':
    main()
