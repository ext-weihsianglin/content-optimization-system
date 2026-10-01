"""Run offline extraction candidates with versioned, resumable results."""

from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import signal
import time

import duckdb

from preprocessing.offline import network_disabled
from preprocessing.schema import CandidateResult, Snapshot, snapshot_identity, stable_hash


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def time_limit(seconds):
    def timeout(signum, frame):
        raise TimeoutError(f"Extraction exceeded {seconds} seconds")

    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def code_fingerprint():
    paths = [ROOT / "preprocessing" / name for name in ["schema.py", "blocks.py", "quality.py", "offline.py", "runner.py", "adapters/local.py", "adapters/external.py"]]
    paths += [ROOT / "preprocessing/node/package-lock.json", ROOT / "preprocessing/node/worker.cjs", ROOT / "preprocessing/node/worker.js", ROOT / "scripts/analyze_content.py", ROOT / "uv.lock"]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.exists()}


def write_parquet(connection, rows, destination):
    if not rows:
        return
    temporary = destination.with_suffix(".jsonl")
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows))
    target = str(destination).replace("'", "''")
    connection.execute(f"COPY (SELECT * FROM read_json_auto(?, format='newline_delimited',sample_size=-1,maximum_object_size=33554432)) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)", [str(temporary)])
    temporary.unlink()


def evaluation_inputs(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    claimed = manifest.pop("manifest_hash")
    if stable_hash(manifest) != claimed:
        raise ValueError("Evaluation manifest changed after freeze")
    manifest["manifest_hash"] = claimed
    for entry in manifest["snapshots"]:
        payload = (ROOT / "data/evaluation" / f"{entry['snapshot_id']}.txt").read_text()
        payload_hash, snapshot_id = snapshot_identity(payload, entry["href"])
        if payload_hash != entry["payload_hash"] or snapshot_id != entry["snapshot_id"]:
            raise ValueError("Snapshot payload or URL differs from frozen manifest")
        yield Snapshot(snapshot_id, payload_hash, entry["href"], entry["hostname"], payload, entry["format"]), entry


def run(args):
    from preprocessing.adapters.local import extract_baseline, extract_conservative, extract_markdown_text
    from preprocessing.adapters.external import ReadabilityWorker, extract_trafilatura
    from preprocessing.blocks import html_to_blocks, blocks_to_markdown, blocks_to_text
    from preprocessing.quality import source_inventory

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    configuration = json.loads(Path(args.config).read_text())
    fingerprints = code_fingerprint()
    run_identity = stable_hash({"config": configuration, "code": fingerprints})
    results_path = output / "results.jsonl"
    manifest_path = output / "manifest.json"
    if results_path.exists() and not args.resume:
        raise ValueError("Output already contains results; use --resume or a new output directory")
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if previous and previous["run_identity"] != run_identity:
        raise ValueError("Code/configuration changed: use a new output directory instead of reusing cached results")
    completed = {}
    if results_path.exists():
        with results_path.open() as stream:
            for line in stream:
                result = json.loads(line)
                completed[(result["snapshot_id"], result["method"])] = result
    input_manifest = json.loads(Path(args.manifest).read_text())
    run_manifest = {"run_identity": run_identity, "input_manifest_hash": input_manifest["manifest_hash"], "configuration": configuration, "source_fingerprints": fingerprints, "dependencies": {name: version(name) for name in ["duckdb", "beautifulsoup4", "trafilatura", "markdown-it-py", "lxml"]}, "status": "running", "network": "Python sockets denied; Node resources and script execution disabled"}
    if previous and previous["input_manifest_hash"] != run_manifest["input_manifest_hash"]:
        raise ValueError("Input manifest differs from cached run")
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    worker = None
    source_rows = []
    inventory_rows = []
    started = time.perf_counter()
    with results_path.open("a") as stream, network_disabled():
        try:
            for index, (snapshot, entry) in enumerate(evaluation_inputs(Path(args.manifest)), 1):
                source_rows.append({**entry, "record_id": stable_hash([entry["source_file_hash"], entry["source_row"]])})
                if args.split != "all" and entry["split"] != args.split:
                    continue
                try:
                    with time_limit(configuration["timeout_seconds"]):
                        inventory = source_inventory(snapshot.payload, snapshot.href, snapshot.format)
                except Exception as error:
                    inventory = {"quality_flags": ["inventory_failed"], "error": f"{type(error).__name__}: {error}"}
                inventory_rows.append({"snapshot_id": snapshot.snapshot_id, "inventory_json": json.dumps(inventory, ensure_ascii=False)})
                for method in configuration["methods"]:
                    cache_key = (snapshot.snapshot_id, method)
                    if cache_key in completed:
                        continue
                    begin = time.perf_counter()
                    try:
                        if len(snapshot.payload.encode()) > configuration["max_payload_bytes"]:
                            result = CandidateResult(method, "unsupported_format", diagnostics={"reason": "Payload exceeds configured byte limit; source preserved"})
                        else:
                            with time_limit(configuration["timeout_seconds"]):
                                if method == "readability":
                                    worker = worker or ReadabilityWorker()
                                    result = worker.extract(snapshot)
                                else:
                                    result = {"baseline": extract_baseline, "trafilatura": extract_trafilatura, "conservative_dom": extract_conservative, "markdown_text": extract_markdown_text}[method](snapshot)
                                if result.status == "no_output":
                                    result.status = "empty"
                                if result.status == "ok" and result.html and not result.blocks:
                                    result.blocks = html_to_blocks(result.html, snapshot.href, source_html=snapshot.payload)
                                if result.status == "ok" and result.blocks:
                                    if method != "baseline":
                                        result.diagnostics["native_text_characters"] = len(result.text)
                                        result.text = blocks_to_text(result.blocks)
                                    if not result.markdown:
                                        result.markdown = blocks_to_markdown(result.blocks)
                                if result.status == "ok" and not result.text.strip():
                                    result.status = "empty"
                    except TimeoutError as error:
                        result = CandidateResult(method, "timeout", diagnostics={"error": str(error)})
                        if method == "readability" and worker:
                            worker.close()
                            worker = None
                    except Exception as error:
                        result = CandidateResult(method, "error", diagnostics={"error": f"{type(error).__name__}: {error}"})
                    serialized = {"snapshot_id": snapshot.snapshot_id, **result.to_dict(), "runtime_ms": round((time.perf_counter() - begin) * 1000, 3), "run_identity": run_identity}
                    stream.write(json.dumps(serialized, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    completed[cache_key] = serialized
                print(f"Processed {index}/100 {entry['split']} {snapshot.hostname}", flush=True)
        finally:
            if worker:
                worker.close()
    connection = duckdb.connect()
    results = list(completed.values())
    block_rows = [{"snapshot_id": result["snapshot_id"], "method": result["method"], **block} for result in results for block in result["blocks"]]
    extraction_rows = [{key: value for key, value in result.items() if key not in {"blocks", "html"}} | {"metadata": json.dumps(result["metadata"], ensure_ascii=False), "diagnostics": json.dumps(result["diagnostics"], ensure_ascii=False)} for result in results]
    write_parquet(connection, extraction_rows, output / "extractions.parquet")
    write_parquet(connection, [{"snapshot_id": row["snapshot_id"], "method": row["method"], "block_json": json.dumps(row, ensure_ascii=False)} for row in block_rows], output / "blocks.parquet")
    write_parquet(connection, source_rows, output / "records.parquet")
    write_parquet(connection, source_rows, output / "snapshots.parquet")
    write_parquet(connection, inventory_rows, output / "source_features.parquet")
    run_manifest.update(status="complete", attempted_results=len(results), snapshots_with_results=len({row["snapshot_id"] for row in results}), elapsed_seconds=round(time.perf_counter() - started, 3), split=args.split)
    manifest_path.write_text(json.dumps(run_manifest, indent=2) + "\n")
    print(json.dumps({key: run_manifest[key] for key in ["status", "attempted_results", "snapshots_with_results", "elapsed_seconds"]}, indent=2))
