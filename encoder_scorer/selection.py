"""Versioned provider selections resolved into canonical source-grounded labels.

Provider IDs are constrained by packet-specific schemas. Canonical quote strings
are copied from complete packet blocks, never inferred from model prose.
"""

from copy import deepcopy

from encoder_scorer.contracts import SCHEMAS, STRING, arr, enum, obj, validate_structure
from encoder_scorer.curate import canonical

CONTRACT = "teacher-selection-v1"
EVIDENCE_GRANULARITY = "complete-source-block"


def preflight(schema):
    """Bound the strict schema before token counting or paid generation.

    Conservative margins below OpenAI's published 5,000 properties, 1,000 enum
    values, 120,000 schema-string characters and ten nesting levels.
    https://developers.openai.com/api/docs/guides/structured-outputs
    """
    properties = enums = 0
    def count(node):
        nonlocal properties, enums
        if isinstance(node, dict):
            properties += len(node.get("properties", {}))
            enums += len(node.get("enum", []))
            values = node.get("enum", [])
            if len(values) > 250 and sum(len(v) for v in values if isinstance(v, str)) > 14000:
                raise ValueError("Selection schema exceeds bounded single-enum string budget; no call or truncation")
            for child in node.values():
                count(child)
        elif isinstance(node, list):
            for child in node:
                count(child)
    count(schema)
    if properties > 4500 or enums > 950 or len(canonical(schema)) > 110000:
        raise ValueError("Selection schema exceeds bounded property/enum/size budget; no call or truncation")
    # Resolve refs to count effective nesting and detect unexpected recursion.
    def depth(node, level=0, stack=()):
        if "$ref" in node:
            ref = node["$ref"]
            if ref in stack:
                raise ValueError("Selection schema cannot be recursive")
            return depth(schema["$defs"][ref.removeprefix("#/$defs/")], level, (*stack, ref))
        if node.get("type") in ("object", "array"):
            level += 1
        if level > 9:
            raise ValueError("Selection schema exceeds bounded nesting budget; no call or truncation")
        for child in node.get("properties", {}).values():
            depth(child, level, stack)
        if "items" in node:
            depth(node["items"], level, stack)
    depth(schema)


def prepare(task):
    """Adapt runtime requests; leave saved packets and canonical schemas intact."""
    task = deepcopy(task)
    stage = task["stage"]
    if stage == "requirements":
        task["system"] += ("\nAssess a static page's ability to answer the query. "
                           "Ambiguity may justify unassessable, but do not require a page to "
                           "invite a conversation or ask the user a follow-up question.")
        return task
    packet = task["input"]
    body = packet.get("blocks", [])
    support = packet.get("evidence_pack", {}).get("blocks", [])
    all_ids = [b["block_id"] for b in body + support]
    if len(set(all_ids)) != len(all_ids):
        raise ValueError("Candidate/support block IDs must be unique and distinct")
    definitions = {}

    def choices(name, ids):
        if not ids:
            return {"type": "array", "items": STRING, "maxItems": 0}
        definitions[name] = enum(*ids)
        return arr({"$ref": "#/$defs/" + name})

    def evidence(domain):
        blocks = body if domain == "body" else support
        name = domain.title() + "EvidenceId"
        ids = [b["block_id"] for b in blocks if b["text"].strip()]
        if not ids:
            return {"type": "array", "items": obj({"block_id": STRING}), "maxItems": 0}
        definitions[name] = enum(*ids)
        return arr(obj({"block_id": {"$ref": "#/$defs/" + name}}))

    def transform(schema, domain):
        schema = deepcopy(schema)
        for key, child in schema.get("properties", {}).items():
            if key in {"evidence", "claim_evidence", "support_evidence"}:
                selected = "body" if key == "claim_evidence" else "support" if key == "support_evidence" else domain
                schema["properties"][key] = evidence(selected)
            elif key == "block_ids":
                schema["properties"][key] = choices("BodyBlockId", [b["block_id"] for b in body])
            else:
                schema["properties"][key] = transform(child, domain)
        if "items" in schema:
            schema["items"] = transform(schema["items"], domain)
        return schema

    schema = transform(SCHEMAS[stage], "support" if stage == "support" else "body")
    partial = bool(packet.get("coverage", {}).get("omitted_block_ids"))
    if stage == "body":
        assessment = schema["properties"]["requirement_assessments"]["items"]
        assessment["properties"].pop("requirement_id")
        assessment["required"].remove("requirement_id")
        if partial:
            assessment["properties"]["state"]["enum"].remove("missing")
        requirements = packet["requirements"]["requirements"]
        ids = [r["requirement_id"] for r in requirements]
        if not ids or len(set(ids)) != len(ids) or any(not i.strip() for i in ids):
            raise ValueError("Frozen requirements must have unique nonempty IDs")
        definitions["RequirementAssessment"] = assessment
        schema["properties"]["requirement_assessments"] = obj({
            i: {"$ref": "#/$defs/RequirementAssessment"} for i in ids})
    elif stage == "title" and partial:
        schema["properties"]["promises"]["items"]["properties"]["state"]["enum"].remove("unfulfilled")
    schema["$defs"] = definitions
    preflight(schema)
    task["response_schema"] = schema
    task["provider_contract"] = CONTRACT
    task["system"] = task["system"].replace(
        "Quote exact source spans with\nblock IDs; do not invent evidence.",
        "Select source block IDs for evidence; do not copy quotes or invent evidence.")
    task["system"] += ("\nEvidence contains only schema-allowed block_id selections. "
                       "The backend copies the full selected source block verbatim. "
                       "Select blocks that support the judgment; copied text alone does not prove relevance or truth. "
                       "Use the exact response schema; requirement assessments are keyed by frozen requirement ID. "
                       "On partial views use unassessable where omitted content could change a missing/unfulfilled judgment.")
    return task


def assemble(task, selection):
    """Reject invalid selections before copying any immutable source text."""
    validate_structure(selection, task["response_schema"])
    if task.get("provider_contract") != CONTRACT:
        return deepcopy(selection)
    packet = task["input"]
    sources = {b["block_id"]: b["text"] for b in packet.get("blocks", [])
               + packet.get("evidence_pack", {}).get("blocks", [])}
    result = deepcopy(selection)
    if task["stage"] == "body":
        result["requirement_assessments"] = [
            {"requirement_id": key, **value} for key, value in result["requirement_assessments"].items()]

    def resolve(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"evidence", "claim_evidence", "support_evidence"}:
                    for item in value:
                        item["quote"] = sources[item["block_id"]]
                else:
                    resolve(value)
        elif isinstance(node, list):
            for child in node:
                resolve(child)
    resolve(result)
    return result
