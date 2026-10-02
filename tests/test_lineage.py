"""Exact raw/document/request/shard/projection joins with an offline provider."""
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

import numpy as np

from representations.alignment import align
from representations.config import load_config
from representations.corpus import FIELDS, feature_bundle, training_manifests
from representations.inputs import prepare
from representations.lineage import publish
from representations.projection import project
from representations.runner import embed
from representations.storage import digest, file_hash, read_json, read_rows, write_json, write_rows
from test_representations import FakeProvider


class LineageTests(unittest.TestCase):
    def test_complete_lineage_links_vectors_to_raw_rows_and_preserves_pool_members(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'processed/corpus'; source.mkdir(parents=True)
            raw = root / 'raw'; raw.mkdir()
            originals = [{'html_content':f'<h1>Document {i}</h1><p>Body {i}</p>',
                'href':f'https://host{i}.example/item-{i}', 'hostname':f'host{i}.example',
                'prompt':f'Question {i} </script>', 'citation_category':'top'} for i in range(43)]
            write_rows(raw / 'part.parquet', originals)
            raw_hash = file_hash(raw / 'part.parquet')
            records, documents = [], []
            (source / 'documents').mkdir()
            for i, original in enumerate(originals):
                payload = hashlib.sha256(original['html_content'].encode()).hexdigest()
                sid = digest([payload,original['href']])
                blocks = [{'block_id':'b0','order':0,'parent_id':None,'type':'heading',
                    'schema_version':'dom-blocks-v3','heading_level':1,'text':f'Heading {i}', 'inline_markdown':f'Heading {i}'},
                    {'block_id':'b1','order':1,'parent_id':None,'type':'paragraph', 'schema_version':'dom-blocks-v3',
                     'text':f'Body {i} '*60,'inline_markdown':f'Body {i} '*60}]
                chunk = {'chunk_id':f'chunk-{i}','snapshot_id':sid,'method':'conservative_dom',
                         'block_ids':['b0','b1'],'heading_path':[],'oversized':False}
                doc = {'schema_version':'downstream-document-v1','snapshot_id':sid,
                       'source':{'payload_hash':payload,'href':original['href'],'hostname':original['hostname'],'format':'html'},
                       'selection':{'policy':'retention-first-v1','status':'selected','method':'conservative_dom','quality_flags':[]},
                       'source_metadata':{'title':f'Title {i}'}, 'blocks':blocks,'chunks':[chunk],'chunk_ids':[chunk['chunk_id']],
                       'extraction':{'run_identity':'fixture-run','serializer':'markdownify-structured-v1'}}
                doc['extraction']['content_hash'] = digest(doc)
                relative = 'documents/'+sid+'.json.gz'
                with gzip.open(source / relative,'wt') as stream:
                    json.dump(doc, stream)
                documents.append({'snapshot_id':sid,'document_path':relative,'sha256':file_hash(source / relative),'blocks':2,'chunks':1})
                records.append({**{k:v for k,v in original.items() if k!='html_content'},
                    'source_file':'part.parquet','source_file_hash':raw_hash,'source_row':i,
                    'row_id':f'row{i}','snapshot_id':sid,'payload_hash':payload,'split':'train' if i<40 else 'test'})
            for name, rows in [('records',records),('documents',documents)]:
                (source / (name+'.jsonl')).write_text(''.join(json.dumps(row)+'\n' for row in rows))
                write_rows(source / (name+'.parquet'), rows)
            write_json(source / 'manifest.json', {'pipeline_version':'retention-markdownify-corpus-v1',
                'status':'complete','run_identity':'fixture-run','raw_rows':43,'unique_snapshots':43,
                'source_files':{'part.parquet':raw_hash},'artifacts':[{'path':n,'sha256':file_hash(source/n)}
                    for n in ['records.jsonl','records.parquet','documents.jsonl','documents.parquet']]})
            config = load_config(); config.update(chunk_bytes=64,page_bytes=128)
            config['models'] = {'test':{**config['models']['openai-large'],'dimensions':8,'model':'lineage-test'}}
            run = root / 'run'
            prepare(source,run,config,raw_root=raw)
            embed(run,'test',provider=FakeProvider(),cache_root=root/'cache')
            align(run,'test')
            fits = training_manifests(run,'test')
            for name, view, subview in FIELDS:
                project(run,'test',view,2,fit_manifest=fits[name]['path'],subview=subview)
            bundle = feature_bundle(run,'test')
            self.assertEqual(set(bundle['fields']), {name for name,_,_ in FIELDS})
            summary = publish(run,'test',root/'published.html',sample_limit=2)
            self.assertEqual(summary['records'],43)
            self.assertGreater(summary['verified_vector_shards'],0)
            lineage = read_rows(run / 'lineage/units.parquet')
            vectors = np.load(run / 'vectors' / summary['model']['config_id'] / 'vectors.npy')
            for row in lineage:
                if row['shard']:
                    shard = np.load(root/'cache'/row['shard'])
                    np.testing.assert_array_equal(shard[row['shard_row']],vectors[row['export_row']])
            pooled = next(row for row in lineage if row['pool_member_ids'])
            self.assertIsNone(pooled['request_id'])
            self.assertTrue(pooled['projection_fields'])
            self.assertEqual(len(read_rows(run/'lineage/records.parquet')),43)
            self.assertTrue((root/'lineage/index.html').exists())
            self.assertNotIn('</script>', (root/'published.html').read_text().split('<script id="lineage-data"')[1].split('</script>')[0])
            direct = next(row for row in lineage if row['shard'] and len(read_json((root/'cache'/row['shard']).with_suffix('.json'))['request_ids']) > 1)
            ids = read_json((root/'cache'/direct['shard']).with_suffix('.json'))['request_ids']
            with sqlite3.connect(root/'cache/catalog.sqlite3') as db:
                db.execute('UPDATE vectors SET row_number=? WHERE request_id=?', ((direct['shard_row']+1)%len(ids), direct['request_id']))
            with self.assertRaisesRegex(ValueError, 'catalog row'):
                publish(run,'test',root/'bad-catalog.html')
            with sqlite3.connect(root/'cache/catalog.sqlite3') as db:
                db.execute('UPDATE vectors SET row_number=? WHERE request_id=?', (direct['shard_row'], direct['request_id']))
            (raw/'part.parquet').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Raw lineage'):
                publish(run,'test',root/'corrupt.html')
