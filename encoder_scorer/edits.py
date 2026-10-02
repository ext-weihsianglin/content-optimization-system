"""Prepare blinded controlled-edit pairs; intended edits are not quality labels."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from encoder_scorer.curate import canonical, sha256

EDIT_TYPES = ("query_repetition", "duplicate_headings", "irrelevant_padding", "misleading_title", "prose_removal", "source_passage_first")


def edited(packet, title, mode):
    candidate = deepcopy(packet)
    if candidate["coverage"]["omitted_block_ids"]:
        raise ValueError("Use full-body views for initial controlled edits")
    candidate_title = title
    if mode in {"query_repetition", "duplicate_headings", "irrelevant_padding"}:
        text = packet["query"] if mode != "irrelevant_padding" else "Decorative wallpaper comes in many colors and patterns."
        repetitions = 20 if mode == "duplicate_headings" else 1
        for i in range(repetitions):
            identity = f"edit::{mode}::{i}"
            candidate["blocks"].append({"block_id": identity,
                "type": "heading" if mode == "duplicate_headings" else "paragraph",
                "text": text if repetitions > 1 else (text + " ") * 20,
                "parent_id": None, "heading_level": 2 if mode == "duplicate_headings" else None, "table": None})
    elif mode == "misleading_title":
        candidate_title = "Verified 2026 pricing and guaranteed results: " + packet["query"]
    elif mode in {"prose_removal", "source_passage_first"}:
        paragraphs = [b for b in candidate["blocks"] if b["type"] == "paragraph" and b["parent_id"] is None and b["text"].strip()]
        if not paragraphs:
            raise ValueError("No top-level prose to edit")
        target = max(paragraphs, key=lambda b: len(b["text"]))
        candidate["blocks"].remove(target)
        if mode == "source_passage_first":
            candidate["blocks"].insert(0, target)
    else:
        raise ValueError("Unknown edit type")
    candidate["coverage"].update(included_block_ids=[b["block_id"] for b in candidate["blocks"]],
                                  original_block_count=len(candidate["blocks"]),
                                  scope="full_candidate_body", policy="controlled-edit-retained-view-v1",
                                  serialized_block_characters=len(canonical(candidate["blocks"])))
    # Namespaced source evidence distinguishes candidate assertions from source fidelity.
    candidate["evidence_pack"] = {"kind": "original_page_fidelity", "blocks": [
        {"block_id": "reference::" + b["block_id"], "text": b["text"]} for b in packet["blocks"]]}
    return candidate, candidate_title


def build(packets_path, output, count=3):
    if output.exists():
        raise FileExistsError("Use a new edit directory")
    packets = [json.loads(line) for line in packets_path.open()]
    eligible = [p for p in packets if p["split"] == "train" and not p["packet"]["coverage"]["omitted_block_ids"]
                and any(b["type"] == "paragraph" and b["parent_id"] is None and b["text"].strip() for b in p["packet"]["blocks"])]
    if count < 1 or len(eligible) < count:
        raise ValueError("Insufficient full-body training cases for controlled edits")
    pairs, ledger = [], []
    for item in sorted(eligible, key=lambda p: sha256(("edit-parent-v1" + p["record_id"]).encode()))[:count]:
        for mode in EDIT_TYPES:
            candidate, title = edited(item["packet"], item["title"], mode)
            original = deepcopy(item["packet"])
            original["evidence_pack"] = deepcopy(candidate["evidence_pack"])
            pair_id = sha256((item["record_id"] + mode).encode())
            options = [{"packet": original, "title": item["title"]}, {"packet": candidate, "title": title}]
            candidate_side = "B"
            if int(pair_id[0], 16) % 2:
                options.reverse()
                candidate_side = "A"
            # Only this pair payload may reach a comparison judge; mutation intent stays separate.
            pairs.append({"pair_id": pair_id, "A": options[0], "B": options[1]})
            ledger.append({"pair_id": pair_id, "parent_record_id": item["record_id"],
                           "split": item["split"], "edit_type": mode, "candidate_side": candidate_side,
                           "quality_label": None, "source_fidelity_only": True})
    output.mkdir(parents=True)
    for name, values in (("pairs", pairs), ("provenance", ledger)):
        with (output / f"{name}.jsonl").open("w") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")
    summary = {"version": "teacher-edits-v1", "parent_cases": count, "pairs": len(pairs),
               "input_packets_sha256": sha256(packets_path.read_bytes()), "edit_types": list(EDIT_TYPES),
               "pairs_sha256": sha256((output / "pairs.jsonl").read_bytes()),
               "provenance_sha256": sha256((output / "provenance.jsonl").read_bytes()),
               "teacher_labels": 0, "model_calls": 0,
               "limitations": ["Post-parser controls, not raw-HTML robustness",
                   "Prose removal is not certified answer removal; passage-first is not certified improvement",
                   "Original-page pack tests fidelity, not external truth",
                   "Token budgeting is pending teacher choice; never silently truncate edited blocks"]}
    (output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parents", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(build(args.packets, args.output, args.parents), indent=2))


if __name__ == "__main__":
    main()
