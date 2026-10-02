"""Raw snapshot inference with the frozen v4 scoring view and provenance checks."""
import hashlib
from pathlib import Path
import numpy as np
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.robust_features import robust_features, VERSION


def predict_frontier(bundle, prompt, payload, href=''):
    if bundle['feature_version'] != VERSION:
        raise ValueError('Model/extractor version mismatch')
    root = Path(__file__).resolve().parents[1]
    for filename, expected in bundle['code_hashes'].items():
        if hashlib.sha256((root/filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Parser or feature code changed since fitting: {filename}')
    doc = parse_snapshot(payload,href)
    if not doc['selection'].get('method') or not doc['text'].strip():
        return {'p_is_cited_high':None, 'selection':doc['selection'], 'reason':'No retained content; model abstained'}
    values = robust_features(prompt,doc)
    row = np.asarray([[values[n] for n in bundle['feature_names']]])
    return {'p_is_cited_high':float(bundle['pipeline'].predict_proba(row)[0,1]), 'selection':doc['selection'], 'feature_version':VERSION}
