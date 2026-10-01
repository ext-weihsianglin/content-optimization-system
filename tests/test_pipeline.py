"""Source identity, frozen split, and offline execution invariants."""

import json
from pathlib import Path
import socket

import pytest

from preprocessing.offline import network_disabled
from preprocessing.schema import snapshot_identity, stable_hash


def test_identity_preserves_url_context_and_snapshot_variants():
    original = snapshot_identity("same payload", "https://example.com/a")
    changed_url = snapshot_identity("same payload", "https://example.com/b")
    changed_payload = snapshot_identity("different payload", "https://example.com/a")
    assert original[0] == changed_url[0]
    assert original[1] != changed_url[1]
    assert original != changed_payload


def test_network_connections_rejected_and_restored():
    original = socket.create_connection
    with network_disabled():
        with pytest.raises(RuntimeError, match="disabled"):
            socket.create_connection(("example.com", 443))
    assert socket.create_connection is original


def test_frozen_split_has_no_host_or_payload_overlap():
    manifest = json.loads(Path("evaluation/extraction/manifest.json").read_text())
    fingerprint = manifest.pop("manifest_hash")
    assert stable_hash(manifest) == fingerprint
    development = [row for row in manifest["snapshots"] if row["split"] == "dev"]
    heldout = [row for row in manifest["snapshots"] if row["split"] == "heldout"]
    assert len(development) == 60
    assert len(heldout) == 40
    assert not {row["hostname"] for row in development} & {row["hostname"] for row in heldout}
    assert not {row["payload_hash"] for row in development} & {row["payload_hash"] for row in heldout}


def test_blinded_extraction_inputs_omit_labels_and_prompts():
    manifest = json.loads(Path("evaluation/extraction/manifest.json").read_text())
    for row in manifest["snapshots"]:
        assert "prompt" not in row
        assert "citation_category" not in row
