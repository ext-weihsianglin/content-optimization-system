"""Reference selection must preserve exact sources without accepting bad IDs."""

from copy import deepcopy
import json

import pytest

from encoder_scorer.annotate import Runner, response_label
from encoder_scorer.contracts import SCHEMA_VERSION, validate_response
from encoder_scorer.packets import request
from encoder_scorer.selection import assemble, prepare, preflight


def packet():
    return {"query": "How do I reset?", "blocks": [
        {"block_id": "b1", "text": "Hold **Reset** for `10` seconds.\n  preserve whitespace"},
        {"block_id": "b2", "text": "Wait for the router to restart."},
        {"block_id": "container", "text": ""}],
        "coverage": {"omitted_block_ids": []}, "evidence_pack": {"blocks": []}}


def requirements():
    return {"schema_version": SCHEMA_VERSION, "task_type": "procedure", "ambiguity": "",
            "requirements": [{"requirement_id": "r1", "text": "Explain reset actions",
                              "origin": "explicit", "importance": "essential"}]}


def selection():
    evidence = [{"block_id": "b1"}]
    rating = {"score": 2, "applicability": "assessed", "reason": "Action supplied.", "evidence": evidence}
    return {"schema_version": SCHEMA_VERSION, "requirement_assessments": {
        "r1": {"state": "answered", "reason": "Reset action.", "evidence": evidence}},
        "section_assessments": [{"section_id": "s1", "block_ids": ["b1"],
            "contribution": "answer", "reason": "Reset action.", "evidence": evidence}],
        "components": {"intent_fulfillment": rating, "section_usefulness": rating}, "limitations": []}


def body_task(p=None):
    return prepare(request("body", p or packet(), "Rubric", requirements=requirements()))


def test_backend_copies_markdown_and_whitespace_and_keeps_provider_output_distinct():
    chosen = selection()
    before = deepcopy(chosen)
    label = assemble(body_task(), chosen)
    validate_response("body", label, packet(), requirements())
    assert label["requirement_assessments"][0]["requirement_id"] == "r1"
    assert label["components"]["intent_fulfillment"]["evidence"][0]["quote"] == packet()["blocks"][0]["text"]
    assert chosen == before  # Raw selections remain available for trace/retry review.


@pytest.mark.parametrize("mutation", ["unknown_id", "empty_block", "invented_quote", "missing_requirement", "extra_requirement"])
def test_invalid_references_or_slots_cannot_be_repaired_by_guessing(mutation):
    chosen = deepcopy(selection())
    evidence = chosen["components"]["intent_fulfillment"]["evidence"][0]
    if mutation == "unknown_id":
        evidence["block_id"] = "b999"
    elif mutation == "empty_block":
        evidence["block_id"] = "container"
    elif mutation == "invented_quote":
        evidence["quote"] = "Invented reset instructions"
    elif mutation == "missing_requirement":
        chosen["requirement_assessments"].clear()
    else:
        chosen["requirement_assessments"]["r999"] = chosen["requirement_assessments"]["r1"]
    with pytest.raises(ValueError):
        assemble(body_task(), chosen)


def test_partial_views_exclude_global_absence_in_body_and_title_schema():
    p = packet()
    p["coverage"]["omitted_block_ids"] = ["unseen"]
    chosen = selection()
    chosen["requirement_assessments"]["r1"]["state"] = "missing"
    with pytest.raises(ValueError, match="enum"):
        assemble(body_task(p), chosen)
    chosen["requirement_assessments"]["r1"]["state"] = "unassessable"
    assemble(body_task(p), chosen)
    title = prepare(request("title", p, "Rubric", title="Reset guide"))
    states = title["response_schema"]["properties"]["promises"]["items"]["properties"]["state"]["enum"]
    assert "unfulfilled" not in states and "unassessable" in states
    full = prepare(request("title", packet(), "Rubric", title="Reset guide"))
    assert "unfulfilled" in full["response_schema"]["properties"]["promises"]["items"]["properties"]["state"]["enum"]


def test_support_pack_has_separate_choices_and_copies_pack_text():
    p = packet()
    p["evidence_pack"]["blocks"] = [{"block_id": "ref1", "text": "Reference **reset** guidance."}]
    task = prepare(request("support", p, "Rubric"))
    rating = {"score": 2, "applicability": "assessed", "reason": "Reference supplied.", "evidence": [{"block_id": "ref1"}]}
    chosen = {"schema_version": SCHEMA_VERSION, "claims": [{"claim": "Reset action.",
        "claim_evidence": [{"block_id": "b1"}], "state": "supported", "support_evidence": [{"block_id": "ref1"}],
        "reason": "Reference supports action."}], "components": {"evidence_support": rating}, "limitations": []}
    label = assemble(task, chosen)
    validate_response("support", label, p)
    assert label["claims"][0]["support_evidence"][0]["quote"] == p["evidence_pack"]["blocks"][0]["text"]
    chosen["claims"][0]["support_evidence"][0]["block_id"] = "b1"
    with pytest.raises(ValueError, match="enum"):
        assemble(task, chosen)


def test_empty_input_only_allows_empty_evidence():
    p = packet()
    p["blocks"] = []
    chosen = selection()
    with pytest.raises(ValueError, match="size"):
        assemble(body_task(p), chosen)


def test_selection_does_not_certify_relevance_or_relax_positive_evidence_rule():
    chosen = deepcopy(selection())
    chosen["components"]["intent_fulfillment"]["evidence"] = []
    label = assemble(body_task(), chosen)
    with pytest.raises(ValueError, match="Positive"):
        validate_response("body", label, packet(), requirements())
    chosen["components"]["intent_fulfillment"]["evidence"] = [{"block_id": "b2"}]
    # Valid ID selections are preserved, never relocated using guessed text.
    assert assemble(body_task(), chosen)["components"]["intent_fulfillment"]["evidence"][0]["quote"] == packet()["blocks"][1]["text"]


def test_duplicate_json_keys_reject_conflicts_before_json_can_discard_them():
    def response(text):
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        response_label(response('{"r1": "answered", "r1": "missing"}'))
    assert response_label(response('{"r1": "answered", "r1": "answered"}')) == {"r1": "answered"}


@pytest.mark.parametrize("count, width", [(1000, 0), (251, 80)])
def test_schema_budget_fails_before_any_transport_call(tmp_path, count, width):
    p = packet()
    p["blocks"] = [{"block_id": f"b{i}" + "x" * width, "text": "text"} for i in range(count)]
    class NoCalls:
        def post(self, *args):
            pytest.fail("Oversized schema must never reach the provider")
    runner = Runner(tmp_path / "run", {"reasoning_effort": "medium"}, NoCalls())
    with pytest.raises(ValueError, match="budget"):
        runner.assess("id", "gpt-5", "body", request("body", p, "Rubric", requirements=requirements()), requirements())
    assert runner.traces() == []


def test_live_shape_runner_saves_both_raw_selection_and_canonical_label(tmp_path):
    class Transport:
        def post(self, endpoint, body):
            if endpoint.endswith("input_tokens"):
                return {"input_tokens": 100}
            assert "quote" not in json.dumps(body["text"]["format"]["schema"])
            return {"status": "completed", "model": "gpt-5", "usage": {"input_tokens": 100, "output_tokens": 100},
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(selection())}]}]}
    settings = {"reasoning_effort": "medium", "max_input_tokens": 100000, "max_calls": 6, "budget_usd": 10}
    runner = Runner(tmp_path / "run", settings, Transport())
    label = runner.assess("id", "gpt-5", "body", request("body", packet(), "Rubric", requirements=requirements()), requirements())
    trace = runner.traces()[0]
    assert trace["validation_status"] == "valid"
    assert trace["provider_selection"] == selection() and trace["label"] == label
    assert runner.assess("id", "gpt-5", "body", request("body", packet(), "Rubric", requirements=requirements()), requirements()) == label
