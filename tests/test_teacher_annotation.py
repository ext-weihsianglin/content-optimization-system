"""Provider isolation, durable trace accounting, and resume/failure behavior."""

import json
from pathlib import Path

import pytest

from encoder_scorer.annotate import OUTPUT_LIMITS, Runner, api_payload, response_label
from encoder_scorer.annotate import estimated_cost, seed_valid_traces
from encoder_scorer.curate import canonical, sha256
from encoder_scorer.packets import request
from encoder_scorer.contracts import SCHEMA_VERSION


def requirements():
    return {"schema_version": SCHEMA_VERSION, "task_type": "lookup", "ambiguity": "",
            "requirements": [{"requirement_id": "r1", "text": "Explain resetting", "origin": "explicit", "importance": "essential"}]}


class FakeTransport:
    def __init__(self, labels, fail=False):
        self.labels = iter(labels)
        self.generated = 0
        self.fail = fail

    def post(self, endpoint, body):
        if endpoint == "responses/input_tokens":
            return {"input_tokens": 50, "object": "response.input_tokens"}
        self.generated += 1
        if self.fail:
            raise RuntimeError("Simulated ambiguous transport failure")
        label = next(self.labels)
        return {"id": "response-test", "status": "completed", "model": body["model"],
                "usage": {"input_tokens": 50, "output_tokens": 100},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(label)}]}]}


def config(budget=10):
    return {"reasoning_effort": "medium", "max_input_tokens": 100000, "max_calls": 6, "budget_usd": budget,
            "prices": {"gpt-5": (1.25, 10.00)}}


def task():
    return request("requirements", {"query": "How do I reset?"}, "Test rubric")


def test_api_input_is_blind_and_remote_storage_disabled():
    body = api_payload(task(), "gpt-5.6-luna", "medium")
    assert body["store"] is False
    assert json.loads(body["input"]) == {"query": "How do I reset?"}
    assert body["text"]["format"]["strict"] is True
    assert "api_key" not in canonical(body)


def test_resume_reuses_exact_valid_response_without_generating_again(tmp_path):
    out = tmp_path / "run"
    transport = FakeTransport([requirements()])
    runner = Runner(out, config(), transport)
    assert runner.assess("id", "gpt-5.6-luna", "requirements", task()) == requirements()
    trace = runner.traces()[0]
    assert trace["request_sha256"] == sha256(canonical(trace["request"]).encode())
    assert trace["estimated_cost_usd"] > 0
    resumed = Runner(out, config(), transport, resume=True)
    assert resumed.assess("id", "gpt-5.6-luna", "requirements", task()) == requirements()
    assert transport.generated == 1
    with pytest.raises(ValueError, match="identical"):
        Runner(out, config(20), transport, resume=True)


def test_validation_repair_keeps_failed_trace_and_charges_both_calls(tmp_path):
    invalid = requirements()
    invalid["requirements"] = []
    transport = FakeTransport([invalid, requirements()])
    runner = Runner(tmp_path / "run", config(), transport)
    assert runner.assess("id", "gpt-5.6-luna", "requirements", task()) == requirements()
    traces = runner.traces()
    assert [t["validation_status"] for t in traces] == ["invalid", "valid"]
    assert all(t["estimated_cost_usd"] > 0 for t in traces)
    assert json.loads(traces[1]["request"]["input"])["repair"]["validation_error"]


def test_budget_cap_blocks_generation(tmp_path):
    transport = FakeTransport([requirements()])
    runner = Runner(tmp_path / "run", config(0.0000001), transport)
    with pytest.raises(RuntimeError, match="cap"):
        runner.assess("id", "gpt-5.6-luna", "requirements", task())
    assert transport.generated == 0
    assert runner.traces() == []


def test_ambiguous_network_failure_is_preserved_and_not_retried(tmp_path):
    transport = FakeTransport([], fail=True)
    runner = Runner(tmp_path / "run", config(), transport)
    with pytest.raises(RuntimeError, match="Simulated"):
        runner.assess("id", "gpt-5.6-luna", "requirements", task())
    assert runner.traces()[0]["execution_status"] == "transport_error"
    with pytest.raises(RuntimeError, match="inspect"):
        runner.assess("id", "gpt-5.6-luna", "requirements", task())
    assert transport.generated == 1


def test_incomplete_or_refused_response_never_becomes_labels():
    with pytest.raises(ValueError, match="Incomplete"):
        response_label({"status": "incomplete", "output": []})
    with pytest.raises(ValueError, match="refusal"):
        response_label({"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]})


def test_explicit_timeout_recovery_preserves_reservation_and_attempt():
    import tempfile
    class TransientTransport(FakeTransport):
        def post(self, endpoint, body):
            try:
                return super().post(endpoint, body)
            finally:
                if endpoint == "responses":
                    self.fail = False
    with tempfile.TemporaryDirectory() as directory:
        transport = TransientTransport([requirements()], fail=True)
        settings = {**config(), "allow_transport_retry": True}
        runner = Runner(Path(directory) / "run", settings, transport)
        assert runner.assess("id", "gpt-5", "requirements", task()) == requirements()
        traces = runner.traces()
        assert traces[0]["execution_status"] == "transport_error"
        assert "estimated_cost_usd" not in traces[0]
        assert traces[1]["attempt"] == 2 and traces[1]["retry_reason"]
        assert transport.generated == 2


def test_parallel_budget_reservations_prevent_overspend(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    barrier = threading.Barrier(2)
    class SlowTransport(FakeTransport):
        def post(self, endpoint, body):
            if endpoint == "responses/input_tokens":
                barrier.wait(timeout=2)
            else:
                time.sleep(.1)
            return super().post(endpoint, body)
    reserve = estimated_cost("gpt-5", 50 + len(canonical(task()["response_schema"]).encode()) + 1024,
                             OUTPUT_LIMITS["requirements"])
    transport = SlowTransport([requirements()])
    runner = Runner(tmp_path / "run", config(reserve * 1.5), transport)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(runner.assess, identity, "gpt-5", "requirements", task()) for identity in ("one", "two")]
        successes, failures = 0, 0
        for future in futures:
            try:
                assert future.result() == requirements()
                successes += 1
            except RuntimeError as error:
                assert "cap" in str(error)
                failures += 1
    assert (successes, failures, transport.generated) == (1, 1, 1)


def test_code_revision_seeding_records_lineage_and_reuses_valid_calls(tmp_path):
    first = Runner(tmp_path / "first", {**config(), "code_sha256": {"old": "fingerprint"}}, FakeTransport([requirements()]))
    first.assess("id", "gpt-5", "requirements", task())
    transport = FakeTransport([])
    second = Runner(tmp_path / "second", {**config(), "code_sha256": {"new": "fingerprint"}}, transport)
    seed_valid_traces(second, tmp_path / "first")
    assert second.assess("id", "gpt-5", "requirements", task()) == requirements()
    assert second.traces()[0]["seed_source_manifest_sha256"]
    assert transport.generated == 0
