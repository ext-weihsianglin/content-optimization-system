"""Offline extraction candidates; HTML block serialization belongs to the caller."""

import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time

from preprocessing.schema import CandidateResult


MAX_PAYLOAD_BYTES = 10_000_000
TRAFILATURA_OPTIONS = {
    "output_format": "html",
    "include_tables": True,
    "include_links": True,
    "include_formatting": True,
    "include_comments": False,
    "include_images": True,
    "with_metadata": True,
    "deduplicate": False,
    "favor_precision": False,
    "favor_recall": False,
    "date_extraction_params": {
        "original_date": True, "extensive_search": False, "max_date": "9999-12-31",
    },
}


def _preflight(snapshot, method):
    if snapshot.format != "html":
        return CandidateResult(method, status="unsupported_format")
    if not snapshot.payload.strip():
        return CandidateResult(method, status="no_output")
    if len(snapshot.payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        return CandidateResult(method, status="error", diagnostics={"reason": "payload_too_large"})
    return None


def extract_trafilatura(snapshot):
    """Use fixed preservation settings and keep extracted metadata out of the body."""
    early = _preflight(snapshot, "trafilatura")
    if early is not None:
        return early
    try:
        import trafilatura
        from trafilatura.core import build_html_output
        from trafilatura.xml import xmltotxt

        document = trafilatura.bare_extraction(
            snapshot.payload, url=snapshot.href, **TRAFILATURA_OPTIONS
        )
        diagnostics = {"version": trafilatura.__version__, "configuration": TRAFILATURA_OPTIONS}
        if document is None:
            return CandidateResult("trafilatura", status="no_output", diagnostics=diagnostics)
        text = xmltotxt(document.body, include_formatting=False).strip()
        metadata = {
            key: value for key, value in document.as_dict().items()
            if key not in {"body", "commentsbody", "comments", "text", "raw_text"}
            and value is not None
        }
        return CandidateResult(
            "trafilatura", status="ok" if text else "no_output",
            html=build_html_output(document, with_metadata=False) if text else "",
            text=text, metadata=metadata, diagnostics=diagnostics,
        )
    except Exception as error:
        return CandidateResult("trafilatura", status="error", diagnostics={"error": str(error)})


class ReadabilityWorker:
    """One lazy, persistent JSONL subprocess, serialized and restarted after failures."""

    def __init__(self, timeout_seconds=30, *, node_executable="node", worker_path=None):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self.node_executable = node_executable
        self.worker_path = Path(worker_path) if worker_path else Path(__file__).resolve().parents[1] / "node" / "worker.cjs"
        self._process = None
        self._lock = threading.Lock()

    def _stop(self):
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close()
        process.stdout.close()

    def close(self):
        with self._lock:
            self._stop()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _exchange(self, request):
        if self._process is None or self._process.poll() is not None:
            self._stop()
            self._process = subprocess.Popen(
                [self.node_executable, str(self.worker_path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
            os.set_blocking(self._process.stdin.fileno(), False)
            os.set_blocking(self._process.stdout.fileno(), False)
        process = self._process
        pending = memoryview(request)
        response = bytearray()
        deadline = time.monotonic() + self.timeout_seconds
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Readability worker timed out")
                for key, _ in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        try:
                            written = os.write(process.stdin.fileno(), pending[:65536])
                        except BlockingIOError:
                            continue
                        pending = pending[written:]
                        if not pending:
                            selector.unregister(process.stdin)
                    else:
                        try:
                            chunk = os.read(process.stdout.fileno(), 65536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            raise RuntimeError("Readability worker closed stdout")
                        response.extend(chunk)
                        if len(response) > 100_000_000:
                            raise ValueError("Readability response too large")
                        if b"\n" in response:
                            line, remainder = response.split(b"\n", 1)
                            if remainder.strip() or pending:
                                raise ValueError("Unexpected Readability protocol output")
                            return json.loads(line)

    def extract(self, snapshot):
        early = _preflight(snapshot, "readability")
        if early is not None:
            return early
        with self._lock:
            try:
                request = (json.dumps({"html": snapshot.payload, "url": snapshot.href}) + "\n").encode("utf-8")
                result = self._exchange(request)
                if not isinstance(result, dict) or result.get("status") not in {"ok", "no_output", "error"}:
                    raise ValueError("Invalid Readability response")
                for field in ("html", "text", "markdown"):
                    if not isinstance(result.get(field, ""), str):
                        raise ValueError(f"Invalid Readability {field}")
                for field in ("metadata", "diagnostics"):
                    if not isinstance(result.get(field, {}), dict):
                        raise ValueError(f"Invalid Readability {field}")
                if result["status"] == "ok" and not result.get("text", "").strip():
                    result["status"] = "no_output"
                return CandidateResult("readability", **{
                    key: value for key, value in result.items()
                    if key in {"status", "html", "text", "markdown", "metadata", "diagnostics"}
                })
            except BaseException as error:
                self._stop()
                if not isinstance(error, Exception):
                    raise
                return CandidateResult(
                    "readability", status="timeout" if isinstance(error, TimeoutError) else "error",
                    diagnostics={"error": str(error)},
                )
