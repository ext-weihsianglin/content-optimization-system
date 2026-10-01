"""Saved-document adapter coverage; never uses network or real corpus artifacts."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from representations.config import load_config
from representations.inputs import prepare
from representations.storage import read_rows, write_json
from trad_ml_scorer.retention_features import parse_snapshot


class SavedDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        html = '<html><head><title>Source title</title></head><body><h1>Source heading</h1><p>' + 'Retained words ' * 700 + '</p><h2>Details</h2><table><tr><th>Size</th><td>Large</td></tr></table></body></html>'
        self.doc = parse_snapshot(html, 'https://example.org/product#original', 'example.org',
                                  {'source_file': 'part.parquet', 'source_file_hash': 'rawhash', 'source_row': 0})
        self.doc['selection'].update(status='needs_review', quality_flags=['possible_error_response'])
        self.records = [dict(source_file='part.parquet', source_file_hash='rawhash', source_row=i,
                             record_id='same-content-id', snapshot_id=self.doc['snapshot_id'], prompt='Find size',
                             html_sha256=self.doc['source']['payload_hash'], hostname='example.org',
                             href='https://example.org/product', is_cited_high=1, split='train',
                             exclusions=['exact_duplicate'] if i else []) for i in range(2)]
        write_json(self.source / 'manifest.json', dict(parser_policy='retention-first-v1', raw_rows=2,
                   unique_snapshots=1, source_files={'part.parquet': 'rawhash'}))
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        folder = self.source / 'documents'
        folder.mkdir(exist_ok=True)
        with gzip.open(folder / (self.doc['snapshot_id'] + '.json.gz'), 'wt') as stream:
            json.dump(self.doc, stream)
        with (self.source / 'records.jsonl').open('w') as stream:
            for row in self.records:
                stream.write(json.dumps(row) + '\n')

    def test_retained_review_content_source_chunks_and_duplicate_rows(self):
        output = self.root / 'run'
        manifest = prepare(self.source, output, load_config())
        units = read_rows(output / 'units.parquet')
        associations = read_rows(output / 'associations.parquet')
        self.assertEqual(manifest['records'], 2)
        self.assertEqual(len({a['record_id'] for a in associations}), 2)
        self.assertEqual({a['source_record_id'] for a in associations}, {'same-content-id'})
        self.assertEqual({a['split'] for a in associations}, {'train'})
        self.assertEqual({a['href'] for a in associations}, {'https://example.org/product#original'})
        self.assertTrue(any(a['upstream_exclusions'] == ['exact_duplicate'] for a in associations))
        sections = [u for u in units if u['view'] == 'section']
        self.assertGreater(len(sections), len(self.doc['chunks']))
        self.assertEqual({c for u in sections for c in u['source_chunk_ids']}, set(self.doc['chunk_ids']))
        self.assertTrue(all(json.loads(u['diagnostics_json'])['selection_status'] == 'needs_review' for u in sections))
        self.assertTrue(any('"cells"' in u['text'] for u in sections))
        self.assertEqual(next(u['text'] for u in units if u['subview'] == 'document_title'), 'Source title')
        self.assertTrue(all('Find size' not in u['text'] for u in units if u['role'] == 'document'))

    def test_corrupt_chunk_partition_is_rejected(self):
        self.doc['chunks'][0]['block_ids'].append(self.doc['blocks'][0]['block_id'])
        self.save()
        with self.assertRaisesRegex(ValueError, 'partition'):
            prepare(self.source, self.root / 'run', load_config())

    def test_record_document_mismatch_is_rejected(self):
        self.records[0]['html_sha256'] = 'wrong'
        self.save()
        with self.assertRaisesRegex(ValueError, 'payload mismatch'):
            prepare(self.source, self.root / 'run', load_config())

    def test_duplicate_source_row_is_rejected(self):
        self.records[1]['source_row'] = 0
        self.save()
        with self.assertRaisesRegex(ValueError, 'row identity'):
            prepare(self.source, self.root / 'run', load_config())
