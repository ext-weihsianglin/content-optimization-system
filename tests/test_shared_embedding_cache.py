"""Shared reuse, identity boundaries, corruption and interrupted-write recovery."""
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from representations.cache import VectorCache, embedding_config, default_cache_root
from representations.inputs import prepare
from representations.runner import embed, load_vectors, request_identity
from representations.storage import digest, read_json, read_rows, write_array, write_json
from test_representations import FakeProvider, fixture
from representations.config import load_config


class SharedCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        fixture(self.source, count=4)
        self.config = load_config()
        self.config['models'] = {'test': {**self.config['models']['openai-large'], 'model':'shared-test', 'dimensions':8}}
        self.cache = self.root / 'shared'

    def tearDown(self):
        self.tmp.cleanup()

    def test_persistent_volume_discovery_and_overrides(self):
        checkout = self.root / 'project'
        persistent = self.root / 'data' / 'project'
        result = type('GitResult', (), {'returncode': 0, 'stdout': str(checkout / '.git')})()
        with patch.dict('os.environ', {}, clear=True), patch('representations.cache.subprocess.run', return_value=result):
            self.assertEqual(default_cache_root('run'), (checkout / 'data/representations/shared-store').resolve())
            persistent.mkdir(parents=True)
            self.assertEqual(default_cache_root('run'), (persistent / 'representations/shared-store').resolve())
            with patch.dict('os.environ', {'CONTENT_OPTIMIZATION_DATA_ROOT': str(self.root / 'override')}):
                self.assertEqual(default_cache_root('run'), (self.root / 'override/representations/shared-store').resolve())
                with patch.dict('os.environ', {'EMBEDDING_CACHE_ROOT': str(self.root / 'cache-override')}):
                    self.assertEqual(default_cache_root('run'), (self.root / 'cache-override').resolve())

    def run_at(self, name, config=None):
        run = self.root / name
        prepare(self.source, run, config or self.config)
        return run

    def test_cross_run_reuse_and_execution_tuning_no_credentials(self):
        first = self.run_at('first')
        provider = FakeProvider()
        embed(first, 'test', provider=provider, cache_root=self.cache)
        changed = copy.deepcopy(self.config)
        changed['models']['test'].update(batch_size=1, concurrency=1, timeout=1, key_env='ABSENT_CREDENTIAL')
        second = self.run_at('second', changed)
        with patch('representations.runner.HTTPProvider', side_effect=AssertionError('Should not instantiate provider')):
            embed(second, 'test', cache_root=self.cache)
        left, _ = load_vectors(first, 'test')
        right, _ = load_vectors(second, 'test')
        self.assertEqual(set(left), set(right))
        for uid in left:
            np.testing.assert_array_equal(left[uid], right[uid])
        self.assertGreater(provider.calls, 0)
        connection = sqlite3.connect(self.cache / 'catalog.sqlite3')
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM models').fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs WHERE state='finished'").fetchone()[0], 2)
        connection.close()

    def test_only_new_content_calls_provider(self):
        first = self.run_at('first')
        embed(first, 'test', provider=FakeProvider(), cache_root=self.cache)
        # A changed prompt introduces one query request; all document vectors reuse.
        from representations.storage import write_rows
        rows = read_rows(self.source / 'records.parquet')
        rows[0]['prompt'] = 'Entirely new prompt'
        write_rows(self.source / 'records.parquet', rows)
        second = self.run_at('second')
        provider = FakeProvider()
        seen = []
        original = provider.embed
        provider.embed = lambda texts, role: (seen.extend((role, t) for t in texts) or original(texts, role))
        embed(second, 'test', provider=provider, cache_root=self.cache)
        self.assertEqual(seen, [('query', 'Entirely new prompt')])

    def test_identity_excludes_scheduling_but_includes_semantics(self):
        config = self.config['models']['test']
        unit = {'role':'document','text_hash':'hash'}
        key = request_identity(unit, config)
        for field, value in [('batch_size', 1), ('timeout', 9), ('key_env', 'OTHER'), ('serializer_version','other')]:
            self.assertEqual(key, request_identity(unit, {**config, field:value}))
        for field, value in [('revision','new'), ('dimensions',4), ('endpoint','other'), ('query_instruction','prefix'), ('provider_order',['route'])]:
            self.assertNotEqual(key, request_identity(unit, {**config, field:value}))
        self.assertNotEqual(key, request_identity({**unit, 'role':'query'}, config))
        self.assertNotEqual(key, request_identity({**unit, 'text_hash':'other'}, config))

    def test_model_writer_exclusion(self):
        config = self.config['models']['test']
        first, second = VectorCache(self.cache, config), VectorCache(self.cache, config)
        try:
            with first.writer(self.root):
                with self.assertRaisesRegex(ValueError, 'Another session'):
                    with second.writer(self.root):
                        self.fail('Concurrent writer acquired lock')
        finally:
            first.close(); second.close()

    def test_shard_corruption_fails_before_api(self):
        first = self.run_at('first')
        embed(first, 'test', provider=FakeProvider(), cache_root=self.cache)
        shard = next(self.cache.glob('embeddings/*/vector-shards/*.npy'))
        data = bytearray(shard.read_bytes()); data[-1] ^= 1; shard.write_bytes(data)
        second = self.run_at('second')
        provider = FakeProvider()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            embed(second, 'test', provider=provider, cache_root=self.cache)
        self.assertEqual(provider.calls, 0)

    def test_recover_durable_shard_after_catalog_commit_interruption(self):
        config = self.config['models']['test']
        store = VectorCache(self.cache, config)
        try:
            with store.writer(self.root):
                store.save([('request', np.arange(1,9))], usage={'tokens': 12})
                with store.db:
                    store.db.execute('DELETE FROM vectors')
                    store.db.execute('DELETE FROM events')
                store.recover()
                np.testing.assert_array_equal(store.get(store.locations()['request']), np.arange(1,9))
                self.assertEqual(store.db.execute("SELECT kind FROM events").fetchone()[0], 'recovered')
        finally:
            store.close()

    def test_migrate_legacy_paid_vectors_without_provider(self):
        run = self.run_at('legacy')
        manifest = read_json(run / 'manifest.json')
        config = self.config['models']['test']; cfgid = digest(config)
        units = read_rows(run / 'units.parquet')
        arrays, index = [], []
        provider = FakeProvider()
        for unit in units:
            rid = digest([config, unit['role'], unit['text_hash']]) if unit['status']=='ready' else None
            vector = provider.embed([unit['text']], unit['role'])[0][0] if rid else None
            index.append({'unit_id':unit['unit_id'], 'request_id':rid, 'row':len(arrays) if rid else None,
                          'status':'success' if rid else 'unavailable', 'reason':unit.get('reason')})
            if rid:
                write_array(run / 'cache' / cfgid / (rid+'.npy'), vector)
                arrays.append(vector)
        folder = run / 'vectors' / cfgid
        write_array(folder / 'vectors.npy', np.stack(arrays))
        write_json(folder / 'index.json', index)
        from representations.storage import file_hash
        for name in ('vectors.npy', 'index.json'):
            manifest['artifacts'][str((folder / name).relative_to(run))] = file_hash(folder / name)
        manifest['models']['test'] = {'config_id':cfgid}
        write_json(run / 'manifest.json', manifest)
        with patch('representations.runner.HTTPProvider', side_effect=AssertionError('No paid recomputation')):
            result = embed(run, 'test', resume=True, cache_root=self.cache)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(list(self.cache.glob('embeddings/*/vector-shards/*.json')))

    def test_reuse_input_recipe_and_frozen_model_config(self):
        from representations.inputs import reuse_inputs
        first = self.run_at('first')
        changed = copy.deepcopy(self.config)
        changed['models']['test']['batch_size'] = 1
        result = reuse_inputs(first, self.root/'fork', changed)
        self.assertEqual(result['models'], {})
        self.assertEqual(read_rows(first/'units.parquet'), read_rows(self.root/'fork'/'units.parquet'))
        changed['chunk_bytes'] = 1024
        with self.assertRaisesRegex(ValueError, 'recipe changed'):
            reuse_inputs(first, self.root/'bad', changed)

    def test_backup_is_portable_and_reuses_without_api(self):
        from representations.cache import backup_cache
        first = self.run_at('first')
        embed(first, 'test', provider=FakeProvider(), cache_root=self.cache)
        backup = self.root/'backup'
        result = backup_cache(self.cache, backup)
        self.assertGreater(result['vectors'], 0)
        second = self.run_at('second')
        with patch('representations.runner.HTTPProvider', side_effect=AssertionError('Backup must reuse')):
            embed(second, 'test', cache_root=backup)
        left, _ = load_vectors(first, 'test')
        right, _ = load_vectors(second, 'test')
        for uid in left:
            np.testing.assert_array_equal(left[uid], right[uid])

    def test_cached_readers_can_export_during_another_model_job(self):
        first = self.run_at('first')
        embed(first, 'test', provider=FakeProvider(), cache_root=self.cache)
        second = self.run_at('second')
        writer = VectorCache(self.cache, self.config['models']['test'])
        try:
            with writer.writer(first):
                with patch('representations.runner.HTTPProvider', side_effect=AssertionError('Cached reader cannot call API')):
                    self.assertEqual(embed(second, 'test', cache_root=self.cache)['status'], 'complete')
        finally:
            writer.close()
