"""Resumable hosted requests; immutable cache vectors and atomic run exports."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import time

import numpy as np

from .contracts import FAILURE_SCHEMA
from .providers import HTTPProvider, ProviderError
from .storage import digest, file_hash, load_run, read_json, read_rows, write_array, write_json, write_rows


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
    return digest([config, unit["role"], unit["text_hash"]])


def normalized(vector):
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("Cannot normalize an invalid vector")
    return vector / norm


def embed(run, model_name, *, resume=False, retry_failed=False, max_requests=None,
          provider=None, sleep=time.sleep):
    run = Path(run)
    with run_lock(run):
        return _embed(run, model_name, resume, retry_failed, max_requests, provider, sleep)


def _embed(run, model_name, resume, retry_failed, max_requests, provider, sleep):
    manifest = load_run(run)
    if model_name not in manifest["configuration"]["models"]:
        raise ValueError("Model not present in frozen run configuration")
    config = manifest["configuration"]["models"][model_name]
    cfgid = digest(config)
    previous = manifest["models"].get(model_name)
    if previous and not resume:
        raise ValueError("Model run exists; use --resume")
    if previous and previous["config_id"] != cfgid:
        raise ValueError("Model configuration changed; prepare a new run")
    if max_requests is not None and max_requests < 1:
        raise ValueError("max_requests must be positive")
    units = read_rows(run / "units.parquet")
    requests = {}
    for unit in units:
        if unit["status"] == "ready":
            requests.setdefault(request_identity(unit, config), unit)
    cache = run / "cache" / cfgid
    cache.mkdir(parents=True, exist_ok=True)
    failures_path = cache / "failures.json"
    failures = read_json(failures_path) if failures_path.exists() else {}
    vectors = {}
    pending = []
    for rid, unit in sorted(requests.items()):
        path = cache / f"{rid}.npy"
        if path.exists():
            array = np.load(path, allow_pickle=False)
            if array.shape != (config["dimensions"],) or not np.isfinite(array).all() or np.linalg.norm(array) == 0:
                raise ValueError("Corrupted cached vector")
            vectors[rid] = array
            failures.pop(rid, None)
        elif rid not in failures or retry_failed:
            pending.append((rid, unit))
    if max_requests:
        pending = pending[:max_requests]
    grouped = defaultdict(list)
    for rid, unit in pending:
        grouped[unit["role"]].append((rid, unit))
    batches = []
    for role, items in sorted(grouped.items()):
        batch, byte_count = [], 0
        for item in items:
            size = len(item[1]["text"].encode()) + (len(config.get("query_instruction", "").encode()) if role == "query" else 0)
            if batch and (len(batch) >= config["batch_size"] or byte_count + size > config["batch_bytes"]):
                batches.append((role, batch))
                batch, byte_count = [], 0
            if size > config["batch_bytes"]:
                raise ValueError("A unit exceeds configured batch budget")
            batch.append(item)
            byte_count += size
        if batch:
            batches.append((role, batch))
    # Credentials are needed only when there is actual pending work.
    provider = provider or (HTTPProvider(config) if batches else None)
    usage = list(read_json(cache / "usage.json")) if (cache / "usage.json").exists() else []

    def execute(job):
        role, batch = job
        for attempt in range(1, config["attempts"] + 1):
            try:
                result, used = provider.embed([u["text"] for _, u in batch], role)
                # Also validate injected/test providers before caching.
                if len(result) != len(batch):
                    raise ProviderError("response_cardinality_mismatch")
                for array in result:
                    if np.shape(array) != (config["dimensions"],) or not np.isfinite(array).all() or np.linalg.norm(array) == 0:
                        raise ProviderError("invalid_vector_dimension_or_norm")
                return batch, result, used, None, attempt
            except ProviderError as error:
                if error.fatal:
                    raise
                if not error.retryable or attempt == config["attempts"]:
                    return batch, None, {}, error, attempt
                sleep(min(2 ** (attempt - 1), 30))

    fatal = None
    try:
        with ThreadPoolExecutor(max_workers=config["concurrency"]) as pool:
            for batch, result, used, error, attempts in pool.map(execute, batches):
                if error:
                    for rid, _ in batch:
                        failures[rid] = {"request_id": rid, "reason": error.reason, "attempts": attempts, "retryable": error.retryable}
                else:
                    for (rid, _), array in zip(batch, result):
                        array = np.asarray(array, dtype=np.float32)
                        write_array(cache / f"{rid}.npy", array)
                        vectors[rid] = array
                        failures.pop(rid, None)
                    usage.append({"requests": [rid for rid, _ in batch], "usage": used})
                write_json(failures_path, failures)
                write_json(cache / "usage.json", usage)
    except ProviderError as error:
        fatal = error
    by_unit, index, arrays = {}, [], []
    for unit in units:
        if unit["status"] == "ready":
            vector = vectors.get(request_identity(unit, config))
            if vector is not None:
                by_unit[unit["unit_id"]] = vector
    for unit in units:
        if unit["status"] == "derived":
            members = json.loads(unit["diagnostics_json"])["members"]
            weights = {u["unit_id"]: u["content_weight"] for u in units if u["unit_id"] in members}
            if all(member in by_unit for member in members):
                pooled = np.average([normalized(by_unit[m]) for m in members], axis=0, weights=[weights[m] for m in members])
                if np.linalg.norm(pooled) > 0:
                    by_unit[unit["unit_id"]] = normalized(pooled).astype(np.float32)
    for unit in units:
        uid = unit["unit_id"]
        vector = by_unit.get(uid)
        rid = request_identity(unit, config) if unit["status"] == "ready" else None
        status = "success" if vector is not None else ("failed" if rid in failures else ("unavailable" if unit["status"] == "unavailable" else "incomplete"))
        index.append({"unit_id": uid, "request_id": rid, "row": len(arrays) if vector is not None else None,
                      "status": status, "reason": failures.get(rid, {}).get("reason") or unit.get("reason")})
        if vector is not None:
            arrays.append(vector)
    destination = run / "vectors" / cfgid
    write_array(destination / "vectors.npy", np.stack(arrays) if arrays else np.empty((0, config["dimensions"])))
    write_json(destination / "index.json", index)
    write_rows(destination / "failures.parquet", list(failures.values()), FAILURE_SCHEMA)
    complete = all(row["status"] != "incomplete" for row in index)
    model_status = {"config_id": cfgid, "model": config["model"], "provider": config["provider"],
                    "status": "complete" if complete and not failures else "complete_with_failures" if complete else "partial",
                    "vectors": len(arrays), "logical_units": len(units), "unique_requests": len(requests),
                    "cached_requests": len(vectors), "failed_requests": len(failures),
                    "fatal_error": fatal.reason if fatal else None}
    manifest["models"][model_name] = model_status
    for filename in ("vectors.npy", "index.json", "failures.parquet"):
        relative = str((destination / filename).relative_to(run))
        manifest["artifacts"][relative] = file_hash(destination / filename)
    # Any prior alignment/projection artifacts belong to older vector hashes.
    write_json(run / "manifest.json", manifest)
    if fatal:
        raise fatal
    return model_status


def load_vectors(run, model_name):
    manifest = load_run(run)
    info = manifest["models"].get(model_name)
    if not info:
        raise ValueError("No embedding run for this model")
    folder = Path(run) / "vectors" / info["config_id"]
    arrays = np.load(folder / "vectors.npy", allow_pickle=False)
    index = read_json(folder / "index.json")
    if sum(row["status"] == "success" for row in index) != len(arrays):
        raise ValueError("Vector index cardinality mismatch")
    return {row["unit_id"]: normalized(arrays[row["row"]]) for row in index if row["status"] == "success"}, manifest
