"""Typed parquet and atomic, content-addressed artifacts."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, data):
    atomic_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())


def read_json(path):
    return json.loads(Path(path).read_text())


def write_rows(path, rows, schema=None):
    table = pa.Table.from_pylist(rows, schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd")
    atomic_bytes(path, sink.getvalue().to_pybytes())


def read_rows(path):
    return pq.read_table(path).to_pylist()


def write_array(path, array):
    import io
    stream = io.BytesIO()
    np.save(stream, np.asarray(array, dtype=np.float32), allow_pickle=False)
    atomic_bytes(path, stream.getvalue())


def load_run(run):
    run = Path(run)
    manifest = read_json(run / "manifest.json")
    for name, expected in manifest["artifacts"].items():
        if file_hash(run / name) != expected:
            raise ValueError(f"Run artifact changed: {name}")
    return manifest


def content_identity(unit, lookup):
    """Full logical view signature; shared individual chunks aren't duplicate pages."""
    if unit["status"] == "derived":
        members = json.loads(unit["diagnostics_json"])["members"]
        return digest("".join(lookup[uid]["text"] for uid in members))
    return unit["text_hash"]
