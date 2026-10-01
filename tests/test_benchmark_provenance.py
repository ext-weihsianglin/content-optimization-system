import copy
import json

import pytest

from preprocessing.benchmark import ROOT, validate_provenance
from preprocessing.schema import stable_hash


def inputs():
    manifest = json.loads((ROOT / "evaluation/extraction/manifest.json").read_text())
    annotations = json.loads((ROOT / "evaluation/extraction/annotations.json").read_text())
    freeze = json.loads((ROOT / "evaluation/extraction/freeze.json").read_text())
    run = {"configuration": freeze["configuration"], "source_fingerprints": freeze["extraction_fingerprints"], "input_manifest_hash": manifest["manifest_hash"]}
    run["run_identity"] = stable_hash({"config": run["configuration"], "code": run["source_fingerprints"]})
    results = [{"run_identity": run["run_identity"]}]
    return manifest, annotations, results, run, freeze


def test_frozen_provenance_is_valid():
    validate_provenance(*inputs())


@pytest.mark.parametrize("mutation", ["mixed_run", "references", "config", "manifest", "scoring"])
def test_provenance_rejects_mismatch(mutation):
    manifest, annotations, results, run, freeze = copy.deepcopy(inputs())
    if mutation == "mixed_run":
        results[0]["run_identity"] = "wrong"
    elif mutation == "references":
        annotations["reference_hash"] = "wrong"
    elif mutation == "config":
        run["configuration"]["timeout_seconds"] += 1
    elif mutation == "manifest":
        manifest["snapshots"][0]["hostname"] = "wrong"
    else:
        freeze["evaluation_sha256"] = "wrong"
    with pytest.raises(ValueError):
        validate_provenance(manifest, annotations, results, run, freeze)
