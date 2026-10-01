"""Meaningful invariants for split isolation, blind inputs, and evidence fidelity."""

from copy import deepcopy
import pytest

from encoder_scorer.curate import development_pool, select_cases
from encoder_scorer.packets import body_view, prepare_packet, request
from encoder_scorer.contracts import SCHEMA_VERSION, validate_response
from encoder_scorer.edits import edited


def row(identity, host, split="train", label=1):
    return {"record_id": identity, "hostname": host, "split": split, "exclusions": [],
            "usable": True, "prompt": "How to reset a router?", "href": "https://example.test/help/reset",
            "status": "selected", "is_cited_high": label}


def doc():
    return {"blocks": [
        {"block_id": "h", "type": "heading", "parent_id": None, "text": "Reset"},
        {"block_id": "list", "type": "list", "parent_id": None, "text": ""},
        {"block_id": "step", "type": "list_item", "parent_id": "list", "text": "Hold the reset button for ten seconds."},
        {"block_id": "p", "type": "paragraph", "parent_id": None, "text": "Wait for the router to restart."}],
        "source": {"hostname": "hidden.test", "href": "https://hidden.test"},
        "is_cited_high": 1, "source_metadata": {"title": "Hidden browser title"}}


def rating(score=2):
    return {"score": score, "applicability": "assessed", "reason": "Concrete reset action.",
            "evidence": [{"block_id": "step", "quote": "Hold the reset button"}]}


def requirements():
    return {"schema_version": SCHEMA_VERSION, "task_type": "procedure", "ambiguity": "",
            "requirements": [{"requirement_id": "r1", "text": "Explain reset actions", "origin": "explicit", "importance": "essential"}]}


def body_response():
    return {"schema_version": SCHEMA_VERSION, "requirement_assessments": [
        {"requirement_id": "r1", "state": "answered", "reason": "Reset action provided.",
         "evidence": [{"block_id": "step", "quote": "Hold the reset button"}]}],
        "section_assessments": [{"section_id": "s1", "block_ids": ["h", "list", "step", "p"],
            "contribution": "answer", "reason": "Reset instructions.", "evidence": [{"block_id": "p", "quote": "router to restart"}]}],
        "components": {"intent_fulfillment": rating(), "section_usefulness": rating()}, "limitations": []}


def test_label_changes_and_input_order_do_not_change_pool():
    records = [row("a", "a"), row("b", "b"), row("c", "c", "validation"), row("test", "test", "test")]
    hosts = {r["hostname"]: r["split"] for r in records}
    selected = [r["record_id"] for r in development_pool(records, hosts)]
    changed = deepcopy(list(reversed(records)))
    for r in changed:
        r["is_cited_high"] = 1 - r["is_cited_high"]
    assert [r["record_id"] for r in development_pool(changed, hosts)] == selected
    assert "test" not in selected


def test_split_mismatch_and_insufficient_population_fail():
    with pytest.raises(ValueError, match="split mismatch"):
        development_pool([row("a", "a")], {"a": "test"})
    with pytest.raises(ValueError, match="distinct"):
        select_cases([], 12, 1)


def test_teacher_inputs_hide_provenance_and_separate_query_first():
    packet = prepare_packet(doc(), "How to reset a router?")
    assert "hidden.test" not in str(packet)
    assert "is_cited_high" not in str(packet)
    query_request = request("requirements", packet, "rubric")
    assert query_request["input"] == {"query": "How to reset a router?"}
    body_request = request("body", packet, "rubric", requirements=requirements())
    assert "title" not in body_request["input"]
    with pytest.raises(ValueError, match="Freeze"):
        request("body", packet, "rubric")


def test_atomic_nested_lists_and_explicit_omissions():
    full, coverage = body_view(doc(), 10000)
    assert coverage["omitted_block_ids"] == []
    assert [b["block_id"] for b in full] == ["h", "list", "step", "p"]
    partial, coverage = body_view(doc(), 200)
    ids = {b["block_id"] for b in partial}
    assert ("list" in ids) == ("step" in ids)
    assert set(coverage["omitted_block_ids"]) | ids == {"h", "list", "step", "p"}
    assert coverage["token_budget"] is None


def test_exact_quotes_unknown_requirements_and_numeric_scores():
    packet = prepare_packet(doc(), "How to reset a router?")
    response = body_response()
    validate_response("body", response, packet, requirements())
    forged = deepcopy(response)
    forged["requirement_assessments"][0]["evidence"][0]["quote"] = "Invented reset procedure"
    with pytest.raises(ValueError, match="exact"):
        validate_response("body", forged, packet, requirements())
    forged = deepcopy(response)
    forged["requirement_assessments"][0]["requirement_id"] = "unknown"
    with pytest.raises(ValueError, match="exactly once"):
        validate_response("body", forged, packet, requirements())
    forged = deepcopy(response)
    forged["components"]["intent_fulfillment"]["score"] = True
    with pytest.raises(ValueError, match="expected"):
        validate_response("body", forged, packet, requirements())


def test_partial_input_cannot_prove_globally_missing_answer():
    packet = prepare_packet(doc(), "How to reset a router?")
    packet["coverage"]["omitted_block_ids"] = ["unseen"]
    response = body_response()
    response["requirement_assessments"][0].update(state="missing", evidence=[])
    with pytest.raises(ValueError, match="globally missing"):
        validate_response("body", response, packet, requirements())


def test_no_evidence_pack_cannot_be_treated_as_verified_support():
    packet = prepare_packet(doc(), "How to reset a router?")
    response = {"schema_version": SCHEMA_VERSION, "claims": [],
                "components": {"evidence_support": rating()}, "limitations": []}
    with pytest.raises(ValueError):
        validate_response("support", response, packet)
    response["components"]["evidence_support"] = {"score": None, "applicability": "unassessable", "reason": "No supplied pack", "evidence": []}
    validate_response("support", response, packet)


def test_candidate_assertion_cannot_be_its_own_support_evidence():
    packet = prepare_packet(doc(), "How to reset a router?")
    packet["evidence_pack"] = {"kind": "original_page_fidelity", "blocks": [{"block_id": "reference::step", "text": "Hold the reset button for ten seconds."}]}
    response = {"schema_version": SCHEMA_VERSION, "claims": [], "components": {"evidence_support": rating()}, "limitations": []}
    with pytest.raises(ValueError, match="exact"):
        validate_response("support", response, packet)
    packet["evidence_pack"]["blocks"][0]["block_id"] = "step"
    with pytest.raises(ValueError, match="distinct"):
        validate_response("support", response, packet)


def test_corrupt_block_trees_fail_instead_of_silently_dropping_content():
    broken = doc()
    broken["blocks"][2]["parent_id"] = "missing"
    with pytest.raises(ValueError, match="parent tree"):
        body_view(broken)
    broken = doc()
    broken["blocks"].append(deepcopy(broken["blocks"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        body_view(broken)


def test_controlled_edits_preserve_original_and_keep_separate_fidelity_evidence():
    packet = prepare_packet(doc(), "How to reset a router?")
    original = deepcopy(packet)
    candidate, title = edited(packet, "Reset", "query_repetition")
    assert packet == original
    assert title == "Reset"
    assert candidate["blocks"][-1]["block_id"].startswith("edit::")
    assert all(b["block_id"].startswith("reference::") for b in candidate["evidence_pack"]["blocks"])
    assert len(candidate["evidence_pack"]["blocks"]) == len(original["blocks"])
    candidate, _ = edited(packet, "Reset", "prose_removal")
    assert len(candidate["blocks"]) == len(packet["blocks"]) - 1
    assert not candidate["coverage"]["omitted_block_ids"]  # Removal is the edit, not truncation.
