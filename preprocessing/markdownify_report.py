"""Reviewable development, held-out and corpus evidence for markdownify adoption.

Every scope gets its own fresh directory. Development fixtures inform conversion;
held-out outputs are diagnostic only. Corpus reports summarize extraction coverage,
not semantic accuracy. Original reports and full exports are never overwritten.
"""
import argparse
from collections import Counter
from html import escape
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import types

import duckdb

from preprocessing.adapters.local import extract_conservative
from preprocessing.blocks import BLOCK_SCHEMA_VERSION
from preprocessing.corpus import file_hash, read_document, validate_document
from preprocessing.inline_fidelity import heldout, location_diagnostics
from preprocessing.markdownify_serializer import OPTIONS, SERIALIZER_VERSION
from preprocessing.offline import network_disabled
from preprocessing.runner import code_fingerprint
from preprocessing.schema import Snapshot, snapshot_identity

ROOT = Path(__file__).resolve().parents[1]
INCUMBENT = 'caf590d1c3b78fa0d66899e799307635e84d23b2'


def incumbent():
    module = types.ModuleType('markdownify_report_incumbent_blocks')
    adapter = types.ModuleType('markdownify_report_incumbent_adapter')
    sys.modules[module.__name__] = module
    for path, target in [('preprocessing/blocks.py', module), ('preprocessing/adapters/local.py', adapter)]:
        code = subprocess.check_output(['git', 'show', f'{INCUMBENT}:{path}'], cwd=ROOT, text=True)
        code = code.replace('from preprocessing.blocks import', 'from markdownify_report_incumbent_blocks import')
        exec(compile(code, f'{INCUMBENT}:{path}', 'exec'), target.__dict__)
    return adapter.extract_conservative


def development():
    previous = incumbent()
    fixture = json.loads((ROOT / 'evaluation/inline-fidelity/development.json').read_text())
    results = []
    for case in fixture['cases']:
        payload_hash, identity = snapshot_identity(case['html'], fixture['href'])
        source = Snapshot(identity, payload_hash, fixture['href'], 'example.test', case['html'], 'html')
        result = extract_conservative(source)
        old = previous(source)
        results.append({**case, 'incumbent_markdown': old.markdown, 'markdownify_powered_markdown': result.markdown,
                        'expected_matches': result.markdown == case['expected_markdown'],
                        'text_unchanged': result.text == old.text, 'source_locations': location_diagnostics(result.blocks, case['html']),
                        'blocks': result.blocks, 'representation': result.diagnostics})
    return {'scope': '12 hand-authored development fixtures; implementation/adoption evidence, not independent semantic accuracy.',
            'fixture_count': len(results), 'expected_matches': sum(row['expected_matches'] for row in results), 'results': results}


def corpus_report(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    for path, digest in manifest['source_fingerprints'].items():
        if file_hash(ROOT / path) != digest:
            raise ValueError(f'Current extraction code differs from completed run: {path}')
    for artifact in manifest['artifacts']:
        if file_hash(directory / artifact['path']) != artifact['sha256']:
            raise ValueError(f'Export artifact hash mismatch: {artifact["path"]}')
    errors = []
    samples = []
    quality = Counter()
    locators = Counter()
    checked = blocks = chunks = 0
    with (directory / 'documents.jsonl').open() as stream:
        for line in stream:
            index = json.loads(line)
            path = directory / index['document_path']
            if file_hash(path) != index['sha256']:
                raise ValueError('Document gzip file hash mismatch')
            doc = read_document(path)
            validate_document(doc, index['snapshot_id'], index['payload_hash'], manifest['run_identity'])
            checked += 1
            blocks += len(doc['blocks'])
            chunks += len(doc['chunks'])
            quality.update(doc['selection'].get('quality_flags', []))
            locators.update(doc.get('source_location_validation', {}))
            if doc.get('error'):
                errors.append({'snapshot_id': doc['snapshot_id'], 'source': doc['source'], 'error': doc['error']})
            if len(samples) < 12 and doc['selection'].get('method'):
                samples.append({'snapshot_id': doc['snapshot_id'], 'href': doc['source']['href'], 'status': doc['selection']['status'],
                                'format': doc['source']['format'], 'representation': doc.get('representation'),
                                'text_preview': doc['text'][:1200], 'markdown_preview': doc['markdown'][:1800],
                                'preview_truncated': len(doc['text']) > 1200 or len(doc['markdown']) > 1800,
                                'blocks': len(doc['blocks']), 'chunks': len(doc['chunks'])})
    if (checked, blocks, chunks) != (manifest['unique_snapshots'], manifest['blocks'], manifest['chunks']):
        raise ValueError('Corpus export totals differ from independently validated documents')
    rows = 0
    identities = set()
    expected_hashes = {}
    source_rows = {}
    with (directory / 'records.jsonl').open() as stream:
        for line in stream:
            record = json.loads(line)
            rows += 1
            if record['row_id'] in identities:
                raise ValueError('Duplicate source row identity in export')
            identities.add(record['row_id'])
            expected_hashes[record['snapshot_id']] = record['payload_hash']
            source_rows[(record['source_file'], record['source_row'])] = record
            if not (directory / record['document_path']).exists():
                raise ValueError('Source row has no explicit document outcome')
    if rows != manifest['raw_rows'] or len(expected_hashes) != checked:
        raise ValueError('Source row/snapshot coverage mismatch')
    # Independently reread original rows, including duplicate snapshot references.
    connection = duckdb.connect()
    connection.execute("SET memory_limit='2GB'")
    connection.execute('SET threads=1')
    raw_verified = 0
    for name, digest in manifest['source_files'].items():
        path = Path(manifest['input_directory']) / name
        if file_hash(path) != digest:
            raise ValueError('Raw Parquet hash changed since extraction')
        cursor = connection.execute('SELECT prompt,citation_category,href,hostname,html_content,file_row_number FROM read_parquet(?,file_row_number=true)', [str(path)])
        while batch := cursor.fetchmany(32):
            for prompt, label, href, host, payload, row in batch:
                record = source_rows.get((name, row))
                if record is None:
                    if manifest['scope']['limit_rows'] is not None:
                        continue
                    raise ValueError('Original source row absent from full export')
                payload_hash, identity = snapshot_identity(payload, href)
                if (record['payload_hash'], record['snapshot_id'], record['prompt'], record['citation_category'], record['href'], record['hostname'], record['source_file_hash']) != (payload_hash, identity, prompt, label, href, host, digest):
                    raise ValueError('Export row differs from its original Parquet source')
                raw_verified += 1
    connection.close()
    if raw_verified != rows:
        raise ValueError('Not every exported row was verified against raw source')
    return {'scope': 'Complete saved-corpus extraction coverage and integrity; not content accuracy, model retraining or citation uplift.',
            'manifest': manifest, 'verification': {'document_file_hashes_checked': checked, 'document_content_checksums_checked': checked,
                       'source_rows_with_outcomes': rows, 'blocks_partitioned_once_in_order': blocks, 'chunks': chunks,
                       'raw_rows_payload_url_and_metadata_verified': raw_verified,
                       'source_locations': dict(locators), 'artifact_hashes_checked': len(manifest['artifacts'])},
            'quality_flags': dict(quality), 'errors': errors, 'samples': samples,
            'limitations': 'Preview snippets are explicitly truncated; full documents/chunks are not truncated. Native formats retain native parsing. Full gzip documents/raw data stay outside Git.'}


def render(result, mode):
    page = '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Markdownify adoption</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:10px;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    page += '<h1>Markdownify adoption: ' + escape(mode) + '</h1><p>' + escape(result['scope']) + '</p>'
    if mode == 'development':
        page += f'<p>{result["expected_matches"]}/{result["fixture_count"]} expected outputs match.</p><table><tr><th>Fixture / HTML</th><th>Incumbent structured serializer</th><th>Default markdownify pipeline</th></tr>'
        for row in result['results']:
            page += '<tr><td>' + escape(row['id']) + '<pre>' + escape(row['html']) + '</pre></td>' + ''.join('<td><pre>' + escape(row[key]) + '</pre></td>' for key in ['incumbent_markdown', 'markdownify_powered_markdown']) + '</tr>'
        page += '</table>'
    elif mode == 'heldout':
        page += '<p>' + escape(result['limitations']) + '</p><pre>' + escape(json.dumps({key: result[key] for key in ['snapshots', 'evaluable_snapshots', 'anchors', 'source_locations']}, indent=2)) + '</pre>'
    else:
        page += '<pre>' + escape(json.dumps({key: result['manifest'][key] for key in ['raw_rows', 'unique_snapshots', 'snapshot_statuses', 'blocks', 'chunks', 'oversized_chunks', 'elapsed_seconds']}, indent=2)) + '</pre>'
        page += '<p>' + escape(result['limitations']) + '</p><pre>' + escape(json.dumps(result['verification'], indent=2)) + '</pre>'
        for row in result['samples']:
            page += '<details><summary>' + escape(row['href']) + ' — ' + escape(row['status']) + '</summary><p>Bounded, escaped previews; full output stays in the local export.</p><h3>Text</h3><pre>' + escape(row['text_preview']) + '</pre><h3>Markdown</h3><pre>' + escape(row['markdown_preview']) + '</pre></details>'
    return page + '<p>Full report evidence: results.json</p>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['development', 'heldout', 'corpus'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--heldout-cache', type=Path)
    parser.add_argument('--corpus-export', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Existing report directory; choose a fresh version')
    with network_disabled():
        if args.mode == 'development':
            result = development()
        elif args.mode == 'heldout':
            if args.heldout_cache is None:
                raise ValueError('Local held-out snapshot cache required')
            result = heldout(incumbent(), args.heldout_cache)
            result['scope'] = 'Separate held-out diagnostics of the fixed, development-implemented markdownify pipeline against the incumbent structured serializer; no serializer tuning/selection on these snapshots.'
        else:
            if args.corpus_export is None:
                raise ValueError('Completed corpus export required')
            result = corpus_report(args.corpus_export)
    result.update(incumbent_revision=INCUMBENT, serializer=SERIALIZER_VERSION, block_schema_version=BLOCK_SCHEMA_VERSION,
                  converter_options=OPTIONS, dependencies={name: version(name) for name in ['markdownify', 'beautifulsoup4', 'markdown-it-py']},
                  source_fingerprints=code_fingerprint(),
                  report_code_sha256=file_hash(Path(__file__)),
                  frozen_evaluation_hashes={str(path.relative_to(ROOT)): file_hash(path) for path in (ROOT / 'evaluation/extraction').glob('*.json')})
    args.output.mkdir(parents=True)
    (args.output / 'results.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    (args.output / 'report.html').write_text(render(result, args.mode))
    print(f'Wrote {args.mode} evidence to {args.output}')


if __name__ == '__main__':
    main()
