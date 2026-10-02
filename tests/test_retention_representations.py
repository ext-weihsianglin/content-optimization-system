"""Saved-document adapter coverage; never uses network or real corpus artifacts."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from representations.config import load_config
from representations.inputs import prepare
from representations.storage import digest, file_hash, read_rows, write_json
from representations.inputs import render_block
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

    def markdownify_source(self):
        for block in self.doc['blocks']:
            block.update(schema_version='dom-blocks-v3', inline_markdown=block['text'])
        self.doc['extraction'] = {'run_identity':'new-run', 'serializer':'markdownify-structured-v1'}
        self.doc['extraction']['content_hash'] = digest(self.doc)
        for row in self.records:
            row.update(row_id='row-' + str(row['source_row']), payload_hash=row['html_sha256'], citation_category='top')
        self.save()
        document = 'documents/' + self.doc['snapshot_id'] + '.json.gz'
        (self.source / 'documents.jsonl').write_text(json.dumps({'snapshot_id':self.doc['snapshot_id'], 'sha256':file_hash(self.source / document)}) + '\n')
        names = ['records.jsonl','documents.jsonl']
        write_json(self.source / 'manifest.json', {'pipeline_version':'retention-markdownify-corpus-v1',
            'status':'complete','run_identity':'new-run', 'raw_rows':2,'unique_snapshots':1,
            'source_files':{'part.parquet':'rawhash'},'artifacts':[{'path':n,'sha256':file_hash(self.source/n)} for n in names]})

    def test_markdownify_integrity_and_original_split_join(self):
        # Reference the same original rows with their frozen splits and exclusions.
        self.records = [{**r, 'href':self.doc['source']['href']} for r in self.records]
        self.save()
        reference = self.root / 'reference'
        prepare(self.source, reference, load_config())
        self.markdownify_source()
        output = self.root / 'markdownify'
        manifest = prepare(self.source, output, load_config(), split_reference=reference)
        rows = read_rows(output / 'associations.parquet')
        self.assertEqual({r['split'] for r in rows}, {'train'})
        self.assertEqual({r['source_record_id'] for r in rows}, {'row-0','row-1'})
        self.assertTrue(any(r['upstream_exclusions'] == ['exact_duplicate'] for r in rows))
        self.assertEqual(manifest['upstream']['manifest']['run_identity'], 'new-run')
        self.assertEqual(manifest['upstream']['split_reference']['associations_sha256'], file_hash(reference / 'associations.parquet'))

    def test_markdownify_document_corruption_rejected(self):
        self.markdownify_source()
        self.doc['blocks'][0]['text'] = 'corrupted'
        self.save()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            prepare(self.source, self.root / 'markdownify', load_config())

    def test_markdownify_content_checksum_rejected_even_with_updated_file_index(self):
        self.markdownify_source()
        self.doc['blocks'][0]['text'] = 'corrupted'
        self.save()
        document = self.source / 'documents' / (self.doc['snapshot_id']+'.json.gz')
        (self.source / 'documents.jsonl').write_text(json.dumps({'snapshot_id':self.doc['snapshot_id'],'sha256':file_hash(document)})+'\n')
        from representations.storage import read_json
        manifest = read_json(self.source / 'manifest.json')
        for artifact in manifest['artifacts']:
            artifact['sha256'] = file_hash(self.source / artifact['path'])
        write_json(self.source / 'manifest.json',manifest)
        with self.assertRaisesRegex(ValueError, 'content identity'):
            prepare(self.source, self.root / 'markdownify', load_config())

    def test_markdownify_split_reference_rejects_changed_query(self):
        self.records = [{**r,'href':self.doc['source']['href']} for r in self.records]
        self.save()
        reference = self.root / 'reference'
        prepare(self.source, reference, load_config())
        self.records[0]['prompt'] = 'Different original query'
        self.markdownify_source()
        with self.assertRaisesRegex(ValueError, 'Split reference'):
            prepare(self.source,self.root / 'markdownify',load_config(),split_reference=reference)

    def test_markdownify_renderer_preserves_inline_semantics(self):
        block = {'block_id':'b1','type':'paragraph','schema_version':'dom-blocks-v3',
                 'text':'Price $100 $80; use x', 'inline_markdown':'Price ~~$100~~ $80; use `x`  \nnext'}
        self.assertEqual(render_block(block, {'b1':block}), block['inline_markdown'])
        code = {**block, 'type':'code','text':' x  \n  y ', 'inline_markdown':'incorrect'}
        self.assertEqual(render_block(code, {'b1':code}), 'Code (unspecified):\n x  \n  y ')
