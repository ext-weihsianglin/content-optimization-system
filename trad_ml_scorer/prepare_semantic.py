"""Join a supplied embedding run to frozen LR records and verify original-space scores."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import duckdb
import numpy as np
from trad_ml_scorer.semantic_features import NAMES, DESCRIPTIONS, original_cosines, section_summary, validate_join

DEFAULT_RUN = '/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/representations/runs/markdownify-openai-v1'
DEFAULT_CORPUS = '/Users/ext-weihsiang.lin/Documents/profound/data/content-optimization-system/processed/markdownify-corpus-v1-complete'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(connection, path, columns='*'):
    result = connection.execute(f'SELECT {columns} FROM read_parquet(?)', [str(path)])
    names = [d[0] for d in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=Path(DEFAULT_RUN))
    parser.add_argument('--corpus', type=Path, default=Path(DEFAULT_CORPUS))
    parser.add_argument('--output', type=Path, default=Path('data/trad_ml_scorer/v7'))
    args = parser.parse_args()
    if (args.output/'manifest.json').exists():
        raise FileExistsError('Frozen semantic cache exists; reuse it or choose a new output')
    run = args.run
    bundle = json.loads((run/'features/openai-v1.json').read_text())
    upstream = json.loads((run/'manifest.json').read_text())
    vector_dir = Path('vectors')/bundle['model']['config_id']
    paths = ['units.parquet', 'associations.parquet', bundle['alignment'], str(vector_dir/'index.parquet'), str(vector_dir/'vectors.npy')]
    hashes = {}
    for name in paths:
        hashes[name] = digest(run/name)
        assert hashes[name] == upstream['artifacts'][name], name
        print('Verified', name, flush=True)
    assert hashes[str(vector_dir/'vectors.npy')] == bundle['vector_sha256']
    corpus_hashes = {}
    for name in ('manifest.json', 'records.parquet', 'documents.parquet'):
        corpus_hashes[name] = digest(args.corpus/name)
        assert corpus_hashes[name] == upstream['upstream']['hashes'][name], name
    base_dir = Path('data/trad_ml_scorer/v5')
    base_manifest = json.loads((base_dir/'manifest.json').read_text())
    assert digest(base_dir/'features.npz') == base_manifest['features_sha256']
    data = dict(np.load(base_dir/'features.npz'))
    assert len(set(data['ids'])) == len(data['ids'])
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:
        # Same canonical duplicate resolution as prior feature preparation.
        records = {r['record_id']: r for r in map(json.loads, stream)}
    con = duckdb.connect()
    associations = rows(con, run/'associations.parquet')
    lookup = {(r['source_file_hash'], r['source_row']): r for r in associations}
    assert len(lookup) == len(associations)
    alignment = rows(con, run/bundle['alignment'])
    align_lookup = {(r['source_file_hash'], r['source_row']): r for r in alignment}
    assert len(align_lookup) == len(alignment)
    joined, matrix, available = [], [], []
    for i, identity in enumerate(data['ids']):
        record = records[str(identity)]
        key = record['source_file_hash'], record['source_row']
        association, scores = lookup[key], align_lookup[key]
        validate_join(record, association)
        validate_join(record, scores)
        assert association['query_unit_id'] == scores['query_unit_id']
        assert association['extraction_id'] == scores['extraction_id']
        assert scores['model_config_id'] == bundle['model']['config_id']
        assert record['split'] == data['splits'][i] and record['hostname'] == data['hosts'][i] and record['is_cited_high'] == data['y'][i]
        values = [np.nan if scores[n] is None else float(scores[n]) for n in NAMES]
        assert all(np.isnan(v) or (np.isfinite(v) and -1.00001 <= v <= 1.00001) for v in values)
        matrix.append(values)
        available.append(scores['page_similarity'] is not None and scores['section_max'] is not None)
        joined.append({'record_id':str(identity), **{k:association[k] for k in ('source_file_hash','source_row','snapshot_id','extraction_id','query_unit_id','split')},
                       'extraction_status':association['extraction_status'], 'alignment_status':scores['status']})
    matrix = np.asarray(matrix)
    # Recompute every supplied similarity on 20 deterministic development records.
    sample = sorted([r for r in joined if r['split'] == 'validation'], key=lambda r:r['record_id'])[:20]
    wanted = {r['snapshot_id'] for r in sample}
    units = rows(con, run/'units.parquet', 'unit_id,snapshot_id,view,subview')
    by_snapshot = defaultdict(list)
    for unit in units:
        if unit['snapshot_id'] in wanted:
            by_snapshot[unit['snapshot_id']].append(unit)
    indices = rows(con, run/vector_dir/'index.parquet', 'unit_id,row,status')
    vector_rows = {r['unit_id']:r['row'] for r in indices if r['status']=='success'}
    vectors = np.load(run/vector_dir/'vectors.npy', mmap_mode='r')
    assert vectors.shape[1] == 3072
    max_error, compared, sampled_missing_queries = 0., 0, 0
    specs = [('title_similarity','title','document_title'),('h1_similarity','title','h1'),('outline_similarity','outline','outline'),('page_similarity','page','page'),('path_similarity','path','url_path')]
    for record in sample:
        qid = record['query_unit_id']
        actual = align_lookup[record['source_file_hash'],record['source_row']]
        if qid not in vector_rows:
            assert all(actual[n] is None for n in NAMES)
            sampled_missing_queries += 1
            continue
        query = vectors[vector_rows[qid]]
        doc_units = by_snapshot[record['snapshot_id']]
        computed = {}
        for name,view,prefix in specs:
            selected = [u for u in doc_units if u['view']==view and u['subview'].startswith(prefix) and not u['subview'].endswith(':chunk') and u['unit_id'] in vector_rows]
            scores = original_cosines(query, vectors[[vector_rows[u['unit_id']] for u in selected]]) if selected else []
            computed[name] = float(max(scores)) if len(scores) else np.nan
        selected = [u for u in doc_units if u['view']=='section' and u['unit_id'] in vector_rows]
        scores = original_cosines(query, vectors[[vector_rows[u['unit_id']] for u in selected]]) if selected else []
        computed.update(section_summary(scores))
        for name in NAMES:
            expected = np.nan if actual[name] is None else actual[name]
            np.testing.assert_allclose(computed[name], expected, atol=2e-6, rtol=0, equal_nan=True)
            if np.isfinite(expected):
                max_error = max(max_error, abs(computed[name]-expected))
                compared += 1
    host_sets = {s:set(data['hosts'][data['splits']==s]) for s in ('train','validation','test')}
    for s in host_sets:
        for t in host_sets:
            if s != t: assert not host_sets[s] & host_sets[t]
    availability = {}
    for split in host_sets:
        mask = data['splits']==split
        availability[split] = {'rows':int(mask.sum()), 'hosts':len(host_sets[split]),
            'page_and_section_available':int(np.asarray(available)[mask].sum()),
            'missing_per_feature':dict(zip(NAMES, np.isnan(matrix[mask]).sum(axis=0).tolist())),
            'extraction_status':dict(Counter(r['extraction_status'] for r in joined if r['split']==split))}
    pca_audit = {}
    for field,meta in bundle['fields'].items():
        fit_metadata = json.loads((run/meta['metadata']).read_text())
        pca_audit[field] = {'scope':fit_metadata['scope'], 'training_units':len(fit_metadata['fit_unit_ids']),
                            'dimensions':meta['dimensions'], 'used':False,
                            'reason':'Separate field bases; whole-train fit is not fold-local. Use original-space cosine.'}
    args.output.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(args.output/'features.npz', X=matrix, y=data['y'], ids=data['ids'], hosts=data['hosts'], splits=data['splits'], available=np.asarray(available))
    with (args.output/'joined_records.jsonl').open('w') as stream:
        for record in joined:stream.write(json.dumps(record)+'\n')
    manifest = {'version':'lr-semantic-v7','run':str(run),'corpus':str(args.corpus),'feature_names':NAMES,'descriptions':DESCRIPTIONS,
        'source_hashes':hashes,'corpus_hashes':corpus_hashes,'bundle_sha256':digest(run/'features/openai-v1.json'),
        'base_features_sha256':base_manifest['features_sha256'],'features_sha256':digest(args.output/'features.npz'),
        'joined_records_sha256':digest(args.output/'joined_records.jsonl'),'availability':availability,'pca_audit':pca_audit,
        'model':bundle['model'],'serializer_version':bundle['serializer_version'],
        'verification':{'records_joined':len(joined),'additional_exclusions':0,'host_overlap':0,'sample_record_ids':[r['record_id'] for r in sample],
                        'sampled_missing_queries':sampled_missing_queries,'similarities_recomputed':compared,'maximum_absolute_error':max_error},
        'code_hashes':{str(p):digest(p) for p in map(Path,['trad_ml_scorer/semantic_features.py','trad_ml_scorer/prepare_semantic.py'])}}
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'availability':availability,'verification':manifest['verification']},indent=2))

if __name__ == '__main__':main()
