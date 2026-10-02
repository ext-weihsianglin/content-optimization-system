"""Versioned offline full-corpus extraction with the default markdownify pipeline.

Documents are gzip JSON with full blocks/chunks/metadata. Every source row has an
index entry; exact payload-plus-URL snapshots are parsed once. No source truncation,
remote calls, model inference or scoring. Resume checks source/code/dependency hashes.
"""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time

import duckdb

from preprocessing.blocks import BLOCK_SCHEMA_VERSION
from preprocessing.markdownify_serializer import SERIALIZER_VERSION
from preprocessing.offline import network_disabled
from preprocessing.runner import code_fingerprint, time_limit
from preprocessing.schema import snapshot_identity, stable_hash

PIPELINE_VERSION = 'retention-markdownify-corpus-v1'


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_document(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def validate_document(doc, identity, payload_hash, run_identity):
    if (doc.get('snapshot_id'), doc.get('source', {}).get('payload_hash'), doc.get('extraction', {}).get('run_identity')) != (identity, payload_hash, run_identity):
        raise ValueError('Cached document identity, source hash or extraction version mismatch')
    content_hash = doc['extraction'].get('content_hash')
    unhashed = {**doc, 'extraction': {key: value for key, value in doc['extraction'].items() if key != 'content_hash'}}
    if content_hash != stable_hash(unhashed):
        raise ValueError('Document content checksum mismatch')
    blocks, chunks = doc.get('blocks', []), doc.get('chunks', [])
    if [key for chunk in chunks for key in chunk['block_ids']] != [block['block_id'] for block in blocks]:
        raise ValueError('Chunk partition does not contain every block exactly once in order')
    if doc.get('chunk_ids', []) != [chunk['chunk_id'] for chunk in chunks]:
        raise ValueError('Chunk identities disagree with document')
    if doc['selection'].get('method') and doc['source']['format'] == 'html' and doc.get('representation', {}).get('serializer') != SERIALIZER_VERSION:
        raise ValueError('Selected HTML document did not use the markdownify serializer')


def parse_one(item):
    from trad_ml_scorer.retention_features import parse_snapshot
    identity, payload_hash, payload, href, host, source, directory, run_identity, timeout = item
    destination = Path(directory) / f'{identity}.json.gz'
    if destination.exists():
        doc = read_document(destination)
        validate_document(doc, identity, payload_hash, run_identity)
        return identity, doc['selection']['status'], True
    begin = time.perf_counter()
    try:
        with network_disabled(), time_limit(timeout):
            doc = parse_snapshot(payload, href, host, source)
            if doc['source']['format'] == 'html':
                from preprocessing.inline_fidelity import location_diagnostics
                doc['source_location_validation'] = location_diagnostics(doc['blocks'], payload)
                if doc['source_location_validation'].get('invalid_locators', 0):
                    raise ValueError('Invalid original-source locator')
    except Exception as error:
        doc = {'schema_version': 'downstream-document-v1', 'snapshot_id': identity,
               'source': {**source, 'payload_hash': payload_hash, 'href': href, 'hostname': host, 'format': 'unknown'},
               'raw_payload_path': None, 'raw_payload_reference': {**source, 'payload_hash': payload_hash},
               'selection': {'policy': 'retention-first-v1', 'status': 'parse_error', 'method': None,
                             'human_validated': False, 'quality_flags': ['extraction_failed'], 'reasons': ['Explicit failure; original source reference retained; no fallback']},
               'error': f'{type(error).__name__}: {error}', 'text': '', 'markdown': '', 'blocks': [], 'chunks': [], 'chunk_ids': []}
    doc['extraction'] = {'pipeline_version': PIPELINE_VERSION, 'run_identity': run_identity,
                         'block_schema_version': BLOCK_SCHEMA_VERSION, 'serializer': SERIALIZER_VERSION,
                         'elapsed_seconds': round(time.perf_counter() - begin, 6)}
    doc['extraction']['content_hash'] = stable_hash(doc)
    validate_document(doc, identity, payload_hash, run_identity)
    temporary = destination.with_suffix('.tmp')
    with temporary.open('wb') as backing, gzip.GzipFile(fileobj=backing, mode='wb', filename='', mtime=0, compresslevel=3) as stream:
        stream.write(json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    temporary.replace(destination)
    return identity, doc['selection']['status'], False


def identity_for(files, timeout):
    fingerprints = code_fingerprint()
    for name in ['preprocessing/corpus.py', 'preprocessing/inline_fidelity.py', 'preprocessing/select.py', 'preprocessing/downstream.py', 'trad_ml_scorer/retention_features.py']:
        fingerprints[name] = file_hash(Path(name))
    return {'pipeline_version': PIPELINE_VERSION, 'source_files': {path.name: file_hash(path) for path in files},
            'source_fingerprints': fingerprints,
            'dependencies': {name: version(name) for name in ['duckdb', 'beautifulsoup4', 'markdown-it-py', 'markdownify', 'lxml']},
            'timeout_seconds': timeout, 'chunk_target_characters': 6000,
            'network': 'Disabled in every extraction worker; saved Parquet snapshots only'}


def index_export(output, records, run_identity):
    statuses, formats, methods, block_types, inline_types, mapping = (Counter() for _ in range(6))
    blocks_total = chunks_total = oversized = 0
    expected = {row['snapshot_id']: row['payload_hash'] for row in records}
    artifacts = []
    staging = output / '.indexes'
    staging.mkdir(exist_ok=True)
    location_counts = Counter()
    with (staging / 'records.jsonl').open('w') as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    def inline(nodes):
        for node in nodes:
            inline_types[node['type']] += 1
            mapping[node['mapping_status']] += 1
            inline(node.get('children', []))
    with (staging / 'documents.jsonl').open('w') as documents, (staging / 'chunks.jsonl').open('w') as chunks:
        for identity, payload_hash in sorted(expected.items()):
            path = output / 'documents' / f'{identity}.json.gz'
            doc = read_document(path)
            validate_document(doc, identity, payload_hash, run_identity)
            selection = doc['selection']
            statuses[selection['status']] += 1
            formats[doc['source']['format']] += 1
            methods[selection.get('method') or 'none'] += 1
            location_counts.update(doc.get('source_location_validation', {}))
            for block in doc['blocks']:
                block_types[block['type']] += 1
                mapping[block['mapping_status']] += 1
                inline(block.get('inline_nodes', []))
                for cell in (block.get('table') or {}).get('cells', []):
                    inline(cell.get('inline_nodes', []))
            blocks_total += len(doc['blocks'])
            chunks_total += len(doc['chunks'])
            oversized += sum(chunk['oversized'] for chunk in doc['chunks'])
            digest = file_hash(path)
            documents.write(json.dumps({'snapshot_id': identity, 'payload_hash': payload_hash, 'document_path': str(path.relative_to(output)),
                                        'sha256': digest, 'status': selection['status'], 'method': selection.get('method'),
                                        'format': doc['source']['format'], 'blocks': len(doc['blocks']), 'chunks': len(doc['chunks']),
                                        'quality_flags': selection.get('quality_flags', []), 'error': doc.get('error')}, ensure_ascii=False) + '\n')
            for chunk in doc['chunks']:
                chunks.write(json.dumps(chunk, ensure_ascii=False) + '\n')
    connection = duckdb.connect()
    connection.execute("SET memory_limit='2GB'")
    connection.execute('SET threads=1')
    expected_rows = {'records': len(records), 'documents': len(expected), 'chunks': chunks_total}
    for name in ['records', 'documents', 'chunks']:
        destination = str(staging / f'{name}.parquet').replace("'", "''")
        if expected_rows[name]:
            count = connection.execute('SELECT COUNT(*) FROM read_json_auto(?,format=\'newline_delimited\',maximum_object_size=33554432)', [str(staging / f'{name}.jsonl')]).fetchone()[0]
            connection.execute(f"COPY (SELECT * FROM read_json_auto(?,format='newline_delimited',sample_size=-1,maximum_object_size=33554432)) TO '{destination}' (FORMAT PARQUET,COMPRESSION ZSTD)", [str(staging / f'{name}.jsonl')])
        else:
            count = 0
            connection.execute(f"COPY (SELECT NULL::VARCHAR AS chunk_id,NULL::VARCHAR AS snapshot_id,NULL::VARCHAR AS method,NULL::INTEGER AS \'order\',[]::VARCHAR[] AS block_ids,[]::VARCHAR[] AS block_schema_versions,NULL::JSON AS heading_path,NULL::VARCHAR AS text,NULL::VARCHAR AS markdown,NULL::INTEGER AS characters,NULL::BOOLEAN AS oversized WHERE false) TO '{destination}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        if count != expected_rows[name]:
            raise ValueError(f'{name} index row count mismatch')
        for suffix in ['jsonl', 'parquet']:
            path = staging / f'{name}.{suffix}'
            artifacts.append({'path': path.name, 'rows': count, 'sha256': file_hash(path)})
            path.replace(output / path.name)
    connection.close()
    return {'raw_rows': len(records), 'unique_snapshots': len(expected), 'shared_snapshot_references': len(records) - len(expected),
            'snapshot_statuses': dict(statuses), 'source_formats': dict(formats), 'selected_methods': dict(methods),
            'blocks': blocks_total, 'chunks': chunks_total, 'oversized_chunks': oversized,
            'block_types': dict(block_types), 'inline_types': dict(inline_types), 'source_mapping_statuses': dict(mapping),
            'source_location_validation': dict(location_counts),
            'artifacts': artifacts}


def run(input_dir, output, workers=4, resume=False, limit=None, timeout=120):
    files = sorted(Path(input_dir).glob('*.parquet'))
    if not files:
        raise FileNotFoundError('No local Parquet source files found')
    identity = identity_for(files, timeout)
    frozen_sources = json.loads(Path('evaluation/extraction/manifest.json').read_text())['input_hashes']
    for name, digest in identity['source_files'].items():
        frozen_digest = frozen_sources.get(f'data/raw/{name}')
        if frozen_digest and frozen_digest != digest:
            raise ValueError(f'Original source Parquet hash changed: {name}')
    identity['scope'] = {'limit_rows': limit, 'input_files': [path.name for path in files]}
    run_identity = stable_hash(identity)
    if (output / 'manifest.json').exists():
        raise FileExistsError('Completed export exists; choose a new version')
    if output.exists():
        if not resume or not (output / 'run_identity.json').exists():
            raise FileExistsError('Output exists; use a fresh directory or explicitly resume this run')
        if json.loads((output / 'run_identity.json').read_text()) != identity:
            raise ValueError('Source/code/dependencies/config changed; cannot reuse cached extraction')
    else:
        output.mkdir(parents=True)
        (output / 'run_identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    directory = output / 'documents'
    directory.mkdir(exist_ok=True)
    started = time.perf_counter()
    records, seen, statuses = [], set(), Counter()
    completed = resumed = 0
    connection = duckdb.connect()
    connection.execute("SET memory_limit='2GB'")
    connection.execute('SET threads=1')
    connection.execute('SET temp_directory=?', [str(output / '.duckdb-temp')])
    def inputs():
        for path in files:
            remaining = limit - len(records) if limit is not None else None
            if remaining is not None and remaining <= 0:
                break
            # Never globally sort/materialize the full corpus's HTML payloads.
            # One file at a time; original row numbers make ordering auditable.
            query = 'SELECT prompt,citation_category,href,hostname,html_content,filename,file_row_number FROM read_parquet(?,filename=true,file_row_number=true)'
            if remaining is not None:
                query += f' LIMIT {remaining}'
            cursor = connection.execute(query, [str(path)])
            while rows := cursor.fetchmany(32):
                for prompt, label, href, host, payload, filename, row in rows:
                    payload_hash, snapshot_id = snapshot_identity(payload, href)
                    source = {'source_file': Path(filename).name, 'source_file_hash': identity['source_files'][Path(filename).name], 'source_row': row}
                    records.append({**source, 'row_id': stable_hash([source['source_file_hash'], row]), 'snapshot_id': snapshot_id,
                                    'payload_hash': payload_hash, 'href': href, 'hostname': host, 'prompt': prompt,
                                    'citation_category': label, 'document_path': f'documents/{snapshot_id}.json.gz'})
                    if snapshot_id in seen:
                        continue
                    seen.add(snapshot_id)
                    yield (snapshot_id, payload_hash, payload, href, host, source, str(directory), run_identity, timeout)
    iterator = inputs()
    pending = set()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        exhausted = False
        while pending or not exhausted:
            while not exhausted and len(pending) < workers * 2:
                item = next(iterator, None)
                if item is None:
                    exhausted = True
                else:
                    pending.add(pool.submit(parse_one, item))
            if not pending:
                break
            done, pending = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            for future in done:
                _, status, cached = future.result()
                statuses[status] += 1
                completed += 1
                resumed += cached
            if done and (completed % 50 < len(done) or not pending):
                progress = {'completed_snapshots': completed, 'source_rows_seen': len(records), 'statuses': dict(statuses),
                            'elapsed_seconds': round(time.perf_counter() - started, 1), 'resumed_snapshots': resumed}
                (output / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
                print(json.dumps(progress), flush=True)
    connection.close()
    records.sort(key=lambda row: (row['source_file'], row['source_row']))
    print('Validating documents and writing indexes/Parquet...', flush=True)
    summary = index_export(output, records, run_identity)
    manifest = {**identity, **summary, 'run_identity': run_identity, 'status': 'complete',
                'input_directory': str(Path(input_dir).resolve()), 'output_directory': str(output.resolve()),
                'elapsed_seconds': round(time.perf_counter() - started, 3), 'resumed_snapshots': resumed,
                'validation': 'Every row resolves to a hash-identified snapshot; every selected block occurs exactly once in its ordered chunk partition; no truncation or silent fallback',
                'limitations': 'Extraction coverage is not human semantic accuracy; native formats use native parsing; corpus scoring/model retraining is outside this export'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: manifest[key] for key in ['status', 'raw_rows', 'unique_snapshots', 'snapshot_statuses', 'blocks', 'chunks', 'elapsed_seconds']}, indent=2), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--limit-rows', type=int, help='Bounded development pilot; recorded explicitly in the manifest')
    parser.add_argument('--timeout-seconds', type=int, default=120)
    args = parser.parse_args()
    if args.workers < 1 or args.timeout_seconds < 1 or (args.limit_rows is not None and args.limit_rows < 1):
        raise ValueError('Workers, timeout and optional row limit must be positive')
    run(args.input_dir, args.output, args.workers, args.resume, args.limit_rows, args.timeout_seconds)


if __name__ == '__main__':
    main()
