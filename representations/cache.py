"""Shared, immutable vector shards with a transactional SQLite catalog."""

from collections import OrderedDict
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
import uuid

import numpy as np

from .storage import digest, file_hash, write_array, write_json

# These change scheduling/provenance, not the vector returned for the same input.
OPERATIONAL_FIELDS = {"key_env", "batch_size", "batch_bytes", "concurrency", "attempts",
                      "timeout", "max_input_bytes", "serializer_version", "path_normalizer_version", "model_path", "memory_limit_gb", "max_tokens_per_batch"}


def embedding_config(config):
    return {key: value for key, value in config.items() if key not in OPERATIONAL_FIELDS}


def request_key(unit, config):
    return digest(["embedding-cache-v1", embedding_config(config), unit["role"], unit["text_hash"]])


def default_cache_root(run):
    if os.environ.get("EMBEDDING_CACHE_ROOT"):
        return Path(os.environ["EMBEDDING_CACHE_ROOT"]).expanduser().resolve()
    result = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=Path(__file__).parent, capture_output=True, text=True)
    if result.returncode == 0:
        return Path(result.stdout.strip()).parent / "data" / "representations" / "shared-store"
    return Path(run).resolve().parent / "shared-store"


class CacheBusyError(ValueError):
    pass


class VectorCache:
    def __init__(self, root, config):
        self.root = Path(root).expanduser().resolve()
        self.config = embedding_config(config)
        self.identity = digest(self.config)
        self.dimensions = config["dimensions"]
        self.root.mkdir(parents=True, exist_ok=True)
        self.folder = self.root / "embeddings" / self.identity
        self.folder.mkdir(parents=True, exist_ok=True)
        self.guard = threading.RLock()
        self.arrays = OrderedDict()
        self.verified = set()
        self.db = sqlite3.connect(self.root / "catalog.sqlite3", timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS models (
                identity TEXT PRIMARY KEY, configuration TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS vectors (
                request_id TEXT PRIMARY KEY, model_identity TEXT NOT NULL,
                shard TEXT NOT NULL, row_number INTEGER NOT NULL, sha256 TEXT NOT NULL,
                dimensions INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS vectors_model ON vectors(model_identity);
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, model_identity TEXT NOT NULL, run TEXT NOT NULL,
                state TEXT NOT NULL, started REAL NOT NULL, finished REAL);
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, model_identity TEXT NOT NULL, job_id TEXT,
                kind TEXT NOT NULL, details TEXT NOT NULL, created REAL NOT NULL);
        ''')
        import json
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO models VALUES (?, ?)",
                            (self.identity, json.dumps(self.config, sort_keys=True)))

    def close(self):
        self.arrays.clear()
        self.db.close()

    @contextmanager
    def writer(self, run):
        """One writer per model across sessions; process exit releases the lock."""
        with (self.folder / ".writer.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CacheBusyError("Another session is writing this shared embedding model; retry after it finishes") from None
            job = uuid.uuid4().hex
            with self.db:
                self.db.execute("UPDATE jobs SET state='interrupted', finished=? WHERE model_identity=? AND state='running'",
                                (time.time(), self.identity))
                self.db.execute("INSERT INTO jobs VALUES (?, ?, ?, 'running', ?, NULL)",
                                (job, self.identity, str(Path(run).resolve()), time.time()))
            self.job = job
            try:
                yield
            except BaseException:
                with self.db:
                    self.db.execute("UPDATE jobs SET state='interrupted', finished=? WHERE job_id=?", (time.time(), job))
                raise
            else:
                with self.db:
                    self.db.execute("UPDATE jobs SET state='finished', finished=? WHERE job_id=?", (time.time(), job))
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def locations(self):
        return {rid: (shard, row, sha, dim) for rid, shard, row, sha, dim in self.db.execute(
            "SELECT request_id, shard, row_number, sha256, dimensions FROM vectors WHERE model_identity=?", (self.identity,))}

    def recover(self):
        """Recover shards durably written before an interrupted index commit."""
        import json
        known = {row[0] for row in self.db.execute("SELECT DISTINCT shard FROM vectors WHERE model_identity=?", (self.identity,))}
        for manifest_path in sorted((self.folder / "vector-shards").glob("*.json")):
            path = manifest_path.with_suffix(".npy")
            relative = str(path.relative_to(self.root))
            if relative in known:
                continue
            metadata = json.loads(manifest_path.read_text())
            if metadata.get("schema_version") != "embedding-shard-v1" or metadata["model_identity"] != self.identity or metadata["configuration"] != self.config or metadata["dimensions"] != self.dimensions:
                raise ValueError("Invalid orphan shard manifest")
            if file_hash(path) != metadata["sha256"]:
                raise ValueError("Orphan shard checksum mismatch")
            ids = metadata["request_ids"]
            matrix = np.load(path, mmap_mode="r", allow_pickle=False)
            if len(set(ids)) != len(ids) or matrix.shape != (len(ids), self.dimensions):
                raise ValueError("Invalid orphan shard index")
            for row in range(len(ids)):
                self.get((relative, row, metadata["sha256"], self.dimensions))
            with self.db:
                self.db.executemany("INSERT OR IGNORE INTO vectors VALUES (?, ?, ?, ?, ?, ?)",
                                    [(rid, self.identity, relative, row, metadata["sha256"], self.dimensions) for row, rid in enumerate(ids)])
                self.db.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?)",
                                (manifest_path.stem, self.identity, None, "recovered",
                                 json.dumps({"requests": ids, "usage": metadata.get("usage", {})}), time.time()))

    def get(self, location):
        shard, row, expected, dimensions = location
        path = self.root / shard
        if dimensions != self.dimensions or dimensions < 1 or not path.is_file():
            raise ValueError("Corrupted shared vector location")
        if shard not in self.verified:
            if file_hash(path) != expected:
                raise ValueError("Shared vector shard checksum mismatch")
            self.verified.add(shard)
        if shard not in self.arrays:
            self.arrays[shard] = np.load(path, mmap_mode="r", allow_pickle=False)
            if len(self.arrays) > 16:
                self.arrays.popitem(last=False)
        self.arrays.move_to_end(shard)
        matrix = self.arrays[shard]
        if matrix.ndim != 2 or matrix.shape[1] != dimensions or not 0 <= row < len(matrix):
            raise ValueError("Corrupted shared vector shard shape/index")
        vector = np.array(matrix[row], dtype=np.float32, copy=True)
        norm = np.linalg.norm(vector)
        if not np.isfinite(vector).all() or not np.isfinite(norm) or norm == 0:
            raise ValueError("Corrupted shared vector values")
        return vector

    def save(self, items, *, kind="api", usage=None):
        """Publish durable shard+manifest before its SQLite index transaction."""
        import json
        if not items:
            return {}
        with self.guard:
            existing = {row[0] for rid, _ in items for row in self.db.execute(
                "SELECT request_id FROM vectors WHERE request_id=?", (rid,))}
            items = [(rid, np.asarray(vector, dtype=np.float32)) for rid, vector in items if rid not in existing]
            if not items:
                return {}
            ids = [rid for rid, _ in items]
            matrix = np.stack([vector for _, vector in items])
            norms = np.linalg.norm(matrix, axis=1)
            if len(set(ids)) != len(ids) or matrix.shape != (len(ids), self.dimensions) or not np.isfinite(matrix).all() or not np.isfinite(norms).all() or (norms == 0).any():
                raise ValueError("Invalid shared vector batch")
            shard_id = uuid.uuid4().hex
            path = self.folder / "vector-shards" / f"{shard_id}.npy"
            write_array(path, matrix)
            sha = file_hash(path)
            relative = str(path.relative_to(self.root))
            write_json(path.with_suffix(".json"), {"schema_version": "embedding-shard-v1", "model_identity": self.identity,
                       "dimensions": self.dimensions, "request_ids": ids, "sha256": sha, "configuration": self.config,
                       "kind": kind, "usage": usage or {}})
            rows = [(rid, self.identity, relative, row, sha, self.dimensions) for row, rid in enumerate(ids)]
            with self.db:
                self.db.executemany("INSERT INTO vectors VALUES (?, ?, ?, ?, ?, ?)", rows)
                self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                                (shard_id, self.identity, getattr(self, "job", None), kind,
                                 json.dumps({"requests": ids, "usage": usage or {}}), time.time()))
            return {rid: (relative, row, sha, self.dimensions) for row, rid in enumerate(ids)}


def backup_cache(root, output):
    """Snapshot SQLite, then copy only immutable shards referenced by that snapshot."""
    import shutil
    from .storage import read_json
    root, output = Path(root).expanduser().resolve(), Path(output).expanduser().resolve()
    if output == root or output.is_relative_to(root):
        raise ValueError('Backup must be outside the source store')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Backup requires an empty destination')
    source = sqlite3.connect((root / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True)
    output.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(output / 'catalog.sqlite3')
    try:
        source.backup(target)
        target.execute('PRAGMA journal_mode=DELETE')
        shards = target.execute('SELECT DISTINCT shard,sha256 FROM vectors').fetchall()
        hashes = {}
        for relative, expected in shards:
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or file_hash(path) != expected:
                raise ValueError('Invalid backup shard provenance')
            dest = output / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            if file_hash(dest) != expected:
                raise ValueError('Backup shard checksum mismatch')
            shutil.copyfile(path.with_suffix('.json'), dest.with_suffix('.json'))
            metadata = read_json(dest.with_suffix('.json'))
            if metadata['sha256'] != expected:
                raise ValueError('Backup shard manifest mismatch')
            hashes[relative] = expected
            hashes[str(dest.with_suffix('.json').relative_to(output))] = file_hash(dest.with_suffix('.json'))
        vector_count = target.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Backup SQLite integrity check failed')
    finally:
        target.close(); source.close()
    hashes['catalog.sqlite3'] = file_hash(output / 'catalog.sqlite3')
    result = {'schema_version':'embedding-store-backup-v1','status':'complete','vectors':vector_count,
              'shards':len(shards), 'files':hashes,
              'scope':'SQLite point-in-time snapshot and referenced immutable vector shards'}
    write_json(output / 'backup-manifest.json', result)
    return {'output':str(output),'vectors':vector_count,'shards':len(shards)}


def cache_status(root):
    """Read progress without acquiring a writer lock or requiring credentials."""
    import json
    root = Path(root).expanduser().resolve()
    connection = sqlite3.connect((root / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True)
    try:
        models = []
        for identity, raw in connection.execute('SELECT identity,configuration FROM models ORDER BY identity'):
            config = json.loads(raw)
            count, shards = connection.execute('SELECT COUNT(*), COUNT(DISTINCT shard) FROM vectors WHERE model_identity=?', (identity,)).fetchone()
            api_batches, tokens, local_seconds = connection.execute('''
                SELECT COUNT(*), COALESCE(SUM(COALESCE(json_extract(details,'$.usage.total_tokens'),
                    json_extract(details,'$.usage.input_tokens_with_role_prefix'),0)),0),
                    COALESCE(SUM(json_extract(details,'$.usage.elapsed_seconds')),0)
                FROM events WHERE model_identity=? AND kind='api'
            ''', (identity,)).fetchone()
            jobs = [{'job_id':job,'run':run,'state':state,'elapsed_seconds':round((end or time.time())-start, 2)}
                    for job,run,state,start,end in connection.execute('SELECT job_id,run,state,started,finished FROM jobs WHERE model_identity=? ORDER BY started DESC LIMIT 5',(identity,))]
            models.append({'embedding_identity':identity,'model':config['model'],'provider':config['provider'],
                           'dimensions':config['dimensions'],'saved_vectors':count,'shards':shards,
                           'inference_batches':api_batches,'reported_tokens':tokens,
                           'reported_local_compute_seconds':local_seconds,'recent_jobs':jobs})
        return {'cache_root':str(root),'models':models}
    finally:
        connection.close()
