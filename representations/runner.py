"""Resumable hosted requests backed by shared shards and atomic run exports."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time

import numpy as np

from .cache import CacheBusyError, VectorCache, default_cache_root, request_key
from .contracts import FAILURE_SCHEMA
from .providers import HTTPProvider, ProviderError
from .storage import digest, file_hash, load_run, read_json, read_rows, write_json, write_rows


@contextmanager
def run_lock(run):
    with (Path(run) / ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another command is writing this run") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def request_identity(unit, config):
    return request_key(unit, config)


def normalized(vector):
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("Cannot normalize an invalid vector")
    return vector / norm


def embed(run, model_name, *, resume=False, retry_failed=False, max_requests=None,
          provider=None, sleep=time.sleep, cache_root=None):
    run = Path(run)
    with run_lock(run):
        manifest = load_run(run)
        if model_name not in manifest["configuration"]["models"]:
            raise ValueError("Model not present in frozen run configuration")
        config = manifest["configuration"]["models"][model_name]
        store = VectorCache(cache_root or default_cache_root(run), config)
        try:
            try:
                with store.writer(run):
                    store.recover()
                    return _embed(run, model_name, manifest, store, resume, retry_failed, max_requests, provider, sleep)
            except CacheBusyError:
                # Immutable, already-published vectors can serve readers while a
                # different run writes additional vectors in this model namespace.
                locations = store.locations()
                units = read_rows(run / "units.parquet")
                if any(request_identity(u, config) not in locations for u in units if u["status"] == "ready"):
                    raise
                return _embed(run, model_name, manifest, store, resume, retry_failed, max_requests, provider, sleep)
        finally:
            store.close()


def import_legacy(run, cfgid, config, requests, store, locations):
    """Import old paid vectors only when backed by a checksum-verified run export."""
    folder = run / "vectors" / cfgid
    if not (folder / "index.json").is_file():
        return
    exported = np.load(folder / "vectors.npy", mmap_mode="r", allow_pickle=False)
    old_index = {r["request_id"]: r for r in read_json(folder / "index.json")
                 if r["request_id"] and r["status"] == "success"}
    items = []
    for rid, unit in requests.items():
        if rid in locations:
            continue
        old_id = digest([config, unit["role"], unit["text_hash"]])
        row = old_index.get(old_id)
        if row is None:
            continue
        path = run / "cache" / cfgid / f"{old_id}.npy"
        if not path.is_file():
            continue
        vector = np.load(path, allow_pickle=False)
        if not np.array_equal(vector, exported[row["row"]]):
            raise ValueError("Legacy cached vector differs from verified run export")
        items.append((rid, vector))
        if len(items) == 256:
            locations.update(store.save(items, kind="legacy_import"))
            items = []
    locations.update(store.save(items, kind="legacy_import"))


def _embed(run, model_name, manifest, store, resume, retry_failed, max_requests, provider, sleep):
    config = manifest["configuration"]["models"][model_name]
    cfgid = digest(config)
    previous = manifest["models"].get(model_name)
    if previous and not resume:
        raise ValueError("Model run exists; use --resume")
    if previous and previous["config_id"] != cfgid:
        raise ValueError("Model configuration changed; prepare a new run")
    if max_requests is not None and max_requests < 1:
        raise ValueError("max_requests must be positive")
    if any(config[k] < 1 for k in ("attempts", "batch_size", "concurrency", "batch_bytes")):
        raise ValueError("Invalid runner limits")
    units = read_rows(run / "units.parquet")
    requests = {}
    for unit in units:
        if unit["status"] == "ready":
            requests.setdefault(request_identity(unit, config), unit)
    cache = run / "cache" / cfgid
    cache.mkdir(parents=True, exist_ok=True)
    failures_path = cache / "failures.json"
    failures = read_json(failures_path) if failures_path.exists() else {}
    # Translate historical run-local failure keys to stable embedding keys.
    for rid, unit in requests.items():
        old_id = digest([config, unit["role"], unit["text_hash"]])
        if old_id in failures:
            failures[rid] = {**failures.pop(old_id), "request_id": rid}
    locations = store.locations()
    import_legacy(run, cfgid, config, requests, store, locations)
    pending = []
    for rid, unit in sorted(requests.items()):
        if rid in locations:
            store.get(locations[rid])  # Fail closed on corruption, before any API work.
            failures.pop(rid, None)
        elif rid not in failures or retry_failed:
            pending.append((rid, unit))
    if max_requests:
        pending = pending[:max_requests]
    grouped = defaultdict(list)
    for rid, unit in pending:
        grouped[unit["role"]].append((rid, unit))

    def batches():
        for role, items in sorted(grouped.items()):
            batch, byte_count = [], 0
            for item in items:
                size = len(item[1]["text"].encode()) + (len(config.get("query_instruction", "").encode()) if role == "query" else 0)
                if batch and (len(batch) >= config["batch_size"] or byte_count + size > config["batch_bytes"]):
                    yield role, batch
                    batch, byte_count = [], 0
                if size > config["batch_bytes"]:
                    raise ValueError("A unit exceeds configured batch budget")
                batch.append(item)
                byte_count += size
            if batch:
                yield role, batch

    if provider is None and pending:
        if config['provider'] == 'mlx':
            from .local_provider import MLXProvider
            provider = MLXProvider(config)
        else:
            provider = HTTPProvider(config)
    usage_path = cache / "usage.jsonl"

    def execute(job):
        role, batch = job
        for attempt in range(1, config["attempts"] + 1):
            try:
                result, used = provider.embed([u["text"] for _, u in batch], role)
                if len(result) != len(batch):
                    raise ProviderError("response_cardinality_mismatch")
                for array in result:
                    norm = np.linalg.norm(array)
                    if np.shape(array) != (config["dimensions"],) or not np.isfinite(array).all() or not np.isfinite(norm) or norm == 0:
                        raise ProviderError("invalid_vector_dimension_or_norm")
                # Persist in the worker as soon as the response is validated.
                saved = store.save([(rid, array) for (rid, _), array in zip(batch, result)], usage=used)
                return batch, saved, used, None, attempt
            except ProviderError as error:
                if error.fatal:
                    raise
                if not error.retryable or attempt == config["attempts"]:
                    return batch, {}, {}, error, attempt
                sleep(min(2 ** (attempt - 1), 30))

    fatal = None
    jobs = iter(batches())
    with ThreadPoolExecutor(max_workers=config["concurrency"]) as pool:
        active = set()
        exhausted = False
        while active or not exhausted:
            while not exhausted and fatal is None and len(active) < config["concurrency"]:
                job = next(jobs, None)
                if job is None:
                    exhausted = True
                    break
                active.add(pool.submit(execute, job))
            if fatal:
                exhausted = True
            if not active:
                break
            completed, active = wait(active, return_when=FIRST_COMPLETED)
            for future in completed:
                try:
                    batch, saved, used, error, attempts = future.result()
                except ProviderError as error:
                    fatal = error
                    continue
                if error:
                    for rid, _ in batch:
                        failures[rid] = {"request_id": rid, "reason": error.reason, "attempts": attempts, "retryable": error.retryable}
                else:
                    locations.update(saved)
                    for rid, _ in batch:
                        failures.pop(rid, None)
                    with usage_path.open('a') as stream:
                        stream.write(json.dumps({"requests": [rid for rid, _ in batch], "usage": used}) + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                write_json(failures_path, failures)
    index = export_vectors(run, cfgid, config, units, store, locations, failures)
    complete = all(row["status"] != "incomplete" for row in index)
    model_status = {"config_id": cfgid, "embedding_identity": store.identity, "cache_root": str(store.root),
                    "storage": "sqlite-shards-v1", "model": config["model"], "provider": config["provider"],
                    "status": "complete" if complete and not failures else "complete_with_failures" if complete else "partial",
                    "vectors": sum(row["status"] == "success" for row in index), "logical_units": len(units),
                    "unique_requests": len(requests), "cached_requests": sum(rid in locations for rid in requests),
                    "failed_requests": len(failures), "fatal_error": fatal.reason if fatal else None}
    manifest["models"][model_name] = model_status
    for filename in ("vectors.npy", "index.json", "index.parquet", "failures.parquet"):
        relative = f"vectors/{cfgid}/{filename}"
        manifest["artifacts"][relative] = file_hash(run / relative)
    write_json(run / "manifest.json", manifest)
    if fatal:
        raise fatal
    return model_status


def export_vectors(run, cfgid, config, units, store, locations, failures):
    """Create the portable run matrix without holding the corpus vectors in RAM."""
    import pyarrow as pa
    lookup = {u["unit_id"]: u for u in units}
    keys = {u["unit_id"]: request_identity(u, config) for u in units if u["status"] == "ready"}
    available = {uid for uid, rid in keys.items() if rid in locations}
    derived = {}
    for unit in units:
        if unit["status"] == "derived":
            members = json.loads(unit["diagnostics_json"])["members"]
            if members and all(member in available for member in members):
                total = np.zeros(config["dimensions"], dtype=np.float64)
                for member in members:
                    total += normalized(store.get(locations[keys[member]])) * lookup[member]["content_weight"]
                if np.isfinite(total).all() and np.linalg.norm(total) > 0:
                    derived[unit["unit_id"]] = normalized(total).astype(np.float32)
    index = []
    for unit in units:
        uid, rid = unit["unit_id"], keys.get(unit["unit_id"])
        success = uid in available or uid in derived
        status = "success" if success else ("failed" if rid in failures else "unavailable" if unit["status"] == "unavailable" else "incomplete")
        index.append({"unit_id": uid, "request_id": rid, "row": None,
                      "status": status, "reason": failures.get(rid, {}).get("reason") or unit.get("reason")})
    destination = run / "vectors" / cfgid
    destination.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".vectors-", suffix=".npy", dir=destination)
    os.close(fd)
    count = sum(row["status"] == "success" for row in index)
    try:
        matrix = np.lib.format.open_memmap(name, mode="w+", dtype=np.float32, shape=(count, config["dimensions"]))
        offset = 0
        for row in index:
            if row["status"] != "success":
                continue
            row["row"] = offset
            uid = row["unit_id"]
            matrix[offset] = derived[uid] if uid in derived else store.get(locations[row["request_id"]])
            offset += 1
        matrix.flush()
        del matrix
        with open(name, "rb") as stream:
            os.fsync(stream.fileno())
        os.replace(name, destination / "vectors.npy")
        directory = os.open(destination, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    write_json(destination / "index.json", index)
    schema = pa.schema([("unit_id", pa.string()), ("request_id", pa.string()), ("row", pa.int64()),
                        ("status", pa.string()), ("reason", pa.string())])
    write_rows(destination / "index.parquet", index, schema)
    write_rows(destination / "failures.parquet", list(failures.values()), FAILURE_SCHEMA)
    return index


def load_vectors(run, model_name):
    manifest = load_run(run)
    info = manifest["models"].get(model_name)
    if not info:
        raise ValueError("No embedding run for this model")
    folder = Path(run) / "vectors" / info["config_id"]
    arrays = np.load(folder / "vectors.npy", mmap_mode="r", allow_pickle=False)
    index = read_json(folder / "index.json")
    if sum(row["status"] == "success" for row in index) != len(arrays):
        raise ValueError("Vector index cardinality mismatch")
    return {row["unit_id"]: normalized(arrays[row["row"]]) for row in index if row["status"] == "success"}, manifest
