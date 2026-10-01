"""Training-split provenance and independent title/H1 transforms."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from representations.config import load_config
from representations.corpus import training_manifests
from representations.inputs import prepare
from representations.projection import apply_pca, project
from representations.runner import embed, load_vectors
from representations.storage import read_json, read_rows, write_rows
from test_representations import FakeProvider, fixture


class CorpusProjectionTests(unittest.TestCase):
    def test_training_only_sources_shared_queries_and_title_subviews(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/'source'; run=root/'run'
            fixture(source,count=50)
            records=read_rows(source/'records.parquet')
            for i,row in enumerate(records):
                row['split']='train' if i<40 else 'test'
                row['upstream_exclusions']=['excluded'] if i==2 else []
            records[41]['prompt']=records[0]['prompt']
            write_rows(source/'records.parquet',records)
            config=load_config()
            config['models']={'test':{**config['models']['openai-large'],'dimensions':8,'model':'corpus-test'}}
            prepare(source,run,config)
            # Mirror retention association exclusions for this fixture.
            from representations.contracts import ASSOCIATION_SCHEMA
            associations=read_rows(run/'associations.parquet')
            for row in associations:
                row['upstream_exclusions']=['excluded'] if row['record_id']=='r2' else []
            write_rows(run/'associations.parquet',associations,ASSOCIATION_SCHEMA)
            from representations.storage import file_hash,write_json
            manifest=read_json(run/'manifest.json');manifest['artifacts']['associations.parquet']=file_hash(run/'associations.parquet')
            write_json(run/'manifest.json',manifest)
            embed(run,'test',provider=FakeProvider(),cache_root=root/'cache')
            fits=training_manifests(run,'test')
            self.assertEqual(fits['query']['mixed_or_unknown_split_units'],1)
            self.assertEqual(fits['page']['training_units'],39)
            vectors,_=load_vectors(run,'test')
            self.assertLessEqual(len(vectors.cache),1024)
            first=project(run,'test','title',2,fit_manifest=fits['document_title']['path'],subview='document_title')
            second=project(run,'test','title',2,fit_manifest=fits['h1']['path'],subview='h1')
            left=read_rows(run/'projections'/first['projection_id']/'pca.parquet')
            right=read_rows(run/'projections'/second['projection_id']/'pca.parquet')
            self.assertFalse({r['unit_id'] for r in left}&{r['unit_id'] for r in right})
            output=root/'applied.parquet'
            apply_pca(run,'test',run/'projections'/first['projection_id'],output)
            self.assertEqual({r['unit_id'] for r in read_rows(output)},{r['unit_id'] for r in left})
            expected={r['unit_id']:r['coordinates'] for r in left}
            for row in read_rows(output):
                np.testing.assert_allclose(row['coordinates'],expected[row['unit_id']],atol=1e-6)

            # Changing a held-out vector cannot alter the saved training PCA fit.
            info=read_json(run/'manifest.json')
            vector_folder=run/'vectors'/info['models']['test']['config_id']
            index={r['unit_id']:r for r in read_json(vector_folder/'index.json')}
            units=read_rows(run/'units.parquet')
            heldout=next(u for u in units if u['snapshot_id']=='s45' and u['subview']=='document_title')
            matrix=np.load(vector_folder/'vectors.npy').copy()
            matrix[index[heldout['unit_id']]['row']]=np.arange(8,0,-1)
            from representations.storage import write_array
            write_array(vector_folder/'vectors.npy',matrix)
            info['artifacts'][str((vector_folder/'vectors.npy').relative_to(run))]=file_hash(vector_folder/'vectors.npy')
            write_json(run/'manifest.json',info)
            changed=project(run,'test','title',2,fit_manifest=fits['document_title']['path'],subview='document_title')
            original=np.load(run/'projections'/first['projection_id']/'pca.npz')
            newer=np.load(run/'projections'/changed['projection_id']/'pca.npz')
            np.testing.assert_array_equal(original['mean'],newer['mean'])
            np.testing.assert_array_equal(original['components'],newer['components'])
