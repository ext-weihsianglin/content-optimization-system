"""Protect saved formatting and source/split lineage when rebinding teacher packets."""

import gzip
import json

import pytest

from encoder_scorer.curate import canonical, sha256
from encoder_scorer.packets import prepare_packet, MARKDOWN_RECIPE
from encoder_scorer.repackage import rebuild


def test_markdown_is_visible_and_exact_quotes_follow_the_sent_representation():
    from encoder_scorer.contracts import validate_response
    from test_teacher_curation import doc, body_response, requirements
    source = doc()
    source.update(representation={"serializer": "markdownify-structured-v1"},
                  selection={"status": "needs_review", "quality_flags": ["sparse"]})
    for b in source["blocks"]:
        b.update(schema_version="dom-blocks-v3", inline_markdown=b["text"])
    source["blocks"][2]["inline_markdown"] = "Hold the **reset button** for ten seconds."
    packet = prepare_packet(source, "How to reset?")
    assert packet["blocks"][2]["text"] == "Hold the **reset button** for ten seconds."
    assert packet["source_quality"]["flags"] == ["sparse"]
    assert packet["coverage"]["serialization"] == MARKDOWN_RECIPE
    response = body_response()
    for item in [response["requirement_assessments"][0], *response["components"].values()]:
        item["evidence"][0]["quote"] = "Hold the **reset button**"
    validate_response("body", response, packet, requirements())
    response["requirement_assessments"][0]["evidence"][0]["quote"] = "Hold the reset button"
    with pytest.raises(ValueError, match="exact"):
        validate_response("body", response, packet, requirements())


def test_code_tables_and_empty_containers_do_not_fall_back_from_markdown():
    source = {"representation": {"serializer": "markdownify-structured-v1"},
              "selection": {"status": "selected"}, "blocks": [
        {"block_id": "list", "type": "list", "parent_id": None, "text": "", "schema_version": "dom-blocks-v3"},
        {"block_id": "code", "type": "code", "parent_id": "list", "text": "  x\n\n", "inline_markdown": "changed", "schema_version": "dom-blocks-v3"},
        {"block_id": "table", "type": "table", "parent_id": None, "text": "Value", "table": {"cells": [{"text": "Value", "rowspan": 2}]}, "schema_version": "dom-blocks-v3"}]}
    packet = prepare_packet(source, "query")
    assert packet["blocks"][1]["text"] == "  x\n\n"
    assert packet["blocks"][2]["table"]["cells"][0]["rowspan"] == 2
    source["blocks"][0]["text"] = "Content without saved Markdown"
    with pytest.raises(ValueError, match="lacks saved"):
        prepare_packet(source, "query")


def fixture(tmp_path):
    corpus, split = tmp_path / "corpus", tmp_path / "split"
    (corpus / "documents").mkdir(parents=True)
    split.mkdir()
    row = {"record_id": "r", "snapshot_id": "s", "hostname": "host", "split": "train", "prompt": "query",
           "html_sha256": "payload", "href": "https://host/", "status": "selected", "source_file_hash": "file", "source_row": 3}
    (split / "records.jsonl").write_text(json.dumps(row) + "\n")
    (split / "host_splits.json").write_text(json.dumps({"host": "train"}))
    identity = {"pipeline_version": "retention-markdownify-corpus-v1"}
    run_id = sha256(canonical(identity).encode())
    (corpus / "run_identity.json").write_text(json.dumps(identity))
    document = {"snapshot_id": "s", "source": {"payload_hash": "payload", "format": "html"},
                "selection": {"status": "selected", "quality_flags": []}, "representation": {"serializer": "markdownify-structured-v1"},
                "extraction": {"run_identity": run_id}, "text": "source", "blocks": [{"block_id": "b", "type": "paragraph", "text": "source"}]}
    raw = gzip.compress(json.dumps(document).encode())
    (corpus / "documents/s.json.gz").write_bytes(raw)
    (corpus / "documents.jsonl").write_text(json.dumps({"snapshot_id": "s", "sha256": sha256(raw), "status": "selected"}) + "\n")
    exported = {**row, "row_id": "new-row-id", "payload_hash": "payload"}
    (corpus / "records.jsonl").write_text(json.dumps(exported) + "\n")
    manifest = {**identity, "status": "complete", "run_identity": run_id, "source_files": {"raw": "file"},
                "artifacts": [{"path": n, "sha256": sha256((corpus / n).read_bytes())} for n in ("records.jsonl", "documents.jsonl")]}
    (corpus / "manifest.json").write_text(json.dumps(manifest))
    old = {"source_files": manifest["source_files"], "source_records_sha256": sha256((split / "records.jsonl").read_bytes()),
           "host_splits_sha256": sha256((split / "host_splits.json").read_bytes()), "candidate_count": 5,
           "cases": [{**row, "document_sha256": "old-hash", "smoke": True, "independent_review": False}], "smoke_ids": ["r"], "review_ids": []}
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps(old))
    return reference, split, corpus


def test_repackage_preserves_frozen_case_and_queue_identity(tmp_path):
    reference, split, corpus = fixture(tmp_path)
    result = rebuild(reference, split, corpus, tmp_path / "new")
    assert result["smoke_ids"] == ["r"] and result["review_ids"] == []
    assert result["cases"][0]["reference_document_sha256"] == "old-hash"
    assert result["cases"][0]["document_sha256"] != "old-hash"
    assert result["cases"][0]["source_row_id"] == "new-row-id"
    assert result["cases"][0]["split"] == "train"
    with pytest.raises(FileExistsError):
        rebuild(reference, split, corpus, tmp_path / "new")


def test_repackage_rejects_wrong_raw_row_even_if_index_hash_is_updated(tmp_path):
    reference, split, corpus = fixture(tmp_path)
    records = corpus / "records.jsonl"
    row = json.loads(records.read_text()); row["prompt"] = "different query"
    records.write_text(json.dumps(row) + "\n")
    manifest = json.loads((corpus / "manifest.json").read_text())
    manifest["artifacts"][0]["sha256"] = sha256(records.read_bytes())
    (corpus / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Raw-row join"):
        rebuild(reference, split, corpus, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_old_packets_cannot_trigger_new_teacher_calls(tmp_path):
    from encoder_scorer.annotate import run
    packets = tmp_path / "old-packets"
    packets.mkdir()
    (packets / "manifest.json").write_text(json.dumps({"version": "teacher-packets-v1"}))
    class NoCalls:
        def post(self, *args):
            raise AssertionError("Legacy packet reached provider")
    with pytest.raises(ValueError, match="versioned markdownify"):
        run(packets, tmp_path / "calls", "gpt-5", transport=NoCalls())
    assert not (tmp_path / "calls").exists()
