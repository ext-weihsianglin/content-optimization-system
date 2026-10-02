"""Strict provider-neutral teacher response schemas and evidence validation."""

COMPONENTS = ("intent_fulfillment", "section_usefulness", "title_body_consistency", "evidence_support")
SCHEMA_VERSION = "teacher-label-v1"


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def arr(item):
    return {"type": "array", "items": item}


STRING = {"type": "string"}


def enum(*values):
    return {"type": "string", "enum": list(values)}


EVIDENCE = obj({"block_id": STRING, "quote": STRING})
RATING = obj({"score": {"type": ["integer", "null"], "minimum": 0, "maximum": 3},
              "applicability": enum("assessed", "not_applicable", "unassessable"),
              "reason": STRING, "evidence": arr(EVIDENCE)})
REQUIREMENT = obj({"requirement_id": STRING, "text": STRING,
                   "origin": enum("explicit", "inferred"), "importance": enum("essential", "optional")})
REQUIREMENTS_SCHEMA = obj({"schema_version": enum(SCHEMA_VERSION),
                          "task_type": enum("lookup", "comparison", "procedure", "explanation", "other", "ambiguous"),
                          "ambiguity": STRING, "requirements": arr(REQUIREMENT)})
BODY_SCHEMA = obj({"schema_version": enum(SCHEMA_VERSION),
    "requirement_assessments": arr(obj({"requirement_id": STRING,
        "state": enum("answered", "partial", "missing", "contradicted", "unassessable"),
        "reason": STRING, "evidence": arr(EVIDENCE)})),
    "section_assessments": arr(obj({"section_id": STRING, "block_ids": arr(STRING),
        "contribution": enum("answer", "evidence", "prerequisite", "repetition", "unrelated", "mixed", "unassessable"),
        "reason": STRING, "evidence": arr(EVIDENCE)})),
    "components": obj({k: RATING for k in ("intent_fulfillment", "section_usefulness")}),
    "limitations": arr(STRING)})
TITLE_SCHEMA = obj({"schema_version": enum(SCHEMA_VERSION),
    "promises": arr(obj({"promise": STRING, "state": enum("fulfilled", "partial", "unfulfilled", "unassessable"),
                         "reason": STRING, "evidence": arr(EVIDENCE)})),
    "components": obj({"title_body_consistency": RATING}), "limitations": arr(STRING)})
SUPPORT_SCHEMA = obj({"schema_version": enum(SCHEMA_VERSION),
    "claims": arr(obj({"claim": STRING, "claim_evidence": arr(EVIDENCE),
        "state": enum("supported", "unsupported", "contradicted", "unassessable"),
        "support_evidence": arr(EVIDENCE), "reason": STRING})),
    "components": obj({"evidence_support": RATING}), "limitations": arr(STRING)})
SCHEMAS = {"requirements": REQUIREMENTS_SCHEMA, "body": BODY_SCHEMA, "title": TITLE_SCHEMA, "support": SUPPORT_SCHEMA}


def validate_structure(value, schema, path="response", root=None):
    root = schema if root is None else root
    if "$ref" in schema:
        prefix = "#/$defs/"
        if not schema["$ref"].startswith(prefix):
            raise ValueError(f"{path}: unsupported schema reference")
        return validate_structure(value, root["$defs"][schema["$ref"][len(prefix):]], path, root)
    kind = schema["type"]
    kinds = kind if isinstance(kind, list) else [kind]
    valid = any((k == "null" and value is None) or (k == "integer" and type(value) is int)
                or (k == "string" and isinstance(value, str)) or (k == "object" and isinstance(value, dict))
                or (k == "array" and isinstance(value, list)) for k in kinds)
    if not valid:
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum")
    if type(value) is int and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        raise ValueError(f"{path}: score outside rubric")
    if isinstance(value, dict):
        if set(value) != set(schema["properties"]):
            raise ValueError(f"{path}: missing or unexpected fields")
        for key, child in value.items():
            validate_structure(child, schema["properties"][key], path + "." + key, root)
    if isinstance(value, list):
        if not schema.get("minItems", len(value)) <= len(value) <= schema.get("maxItems", len(value)):
            raise ValueError(f"{path}: array outside allowed size")
        for i, child in enumerate(value):
            validate_structure(child, schema["items"], f"{path}[{i}]", root)


def validate_response(stage, response, packet, requirements=None):
    validate_structure(response, SCHEMAS[stage])
    blocks = {b["block_id"]: b["text"] for b in packet.get("blocks", [])}
    support = {b["block_id"]: b["text"] for b in packet.get("evidence_pack", {}).get("blocks", [])}
    if set(blocks) & set(support):
        raise ValueError("Evidence-pack IDs must be distinct from candidate block IDs")

    def evidence(items, available):
        for item in items:
            if item["block_id"] not in available or not item["quote"].strip() or item["quote"] not in available[item["block_id"]]:
                raise ValueError("Evidence must quote an exact nonempty span from an available block")

    def rating(item):
        if (item["applicability"] == "assessed") != (item["score"] is not None):
            raise ValueError("Only assessed components may have numeric scores")
        if not item["reason"].strip():
            raise ValueError("Component justification is required")
        evidence(item["evidence"], blocks if stage != "support" else support)
        if item["score"] is not None and item["score"] > 0 and not item["evidence"]:
            raise ValueError("Positive scores require evidence pointers")

    if stage == "requirements":
        ids = [r["requirement_id"] for r in response["requirements"]]
        if not ids or len(set(ids)) != len(ids) or any(not i.strip() for i in ids):
            raise ValueError("Query requirements must have distinct nonempty IDs")
        if any(not r["text"].strip() for r in response["requirements"]):
            raise ValueError("Requirement text must not be empty")
        return
    for component in response["components"].values():
        rating(component)
    if stage == "body":
        if requirements is None:
            raise ValueError("Body assessment requires frozen query requirements")
        expected = {r["requirement_id"] for r in requirements["requirements"]}
        actual = [r["requirement_id"] for r in response["requirement_assessments"]]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("Every frozen requirement must be assessed exactly once")
        for item in response["requirement_assessments"]:
            evidence(item["evidence"], blocks)
            if item["state"] in {"answered", "partial", "contradicted"} and not item["evidence"]:
                raise ValueError("Substantive requirement assessments need evidence")
            if item["state"] == "missing" and packet["coverage"]["omitted_block_ids"]:
                raise ValueError("Omitted content cannot establish a globally missing answer; use unassessable")
        seen = set()
        for item in response["section_assessments"]:
            if not item["section_id"].strip() or item["section_id"] in seen:
                raise ValueError("Section IDs must be unique")
            seen.add(item["section_id"])
            if not item["block_ids"] or any(i not in blocks for i in item["block_ids"]):
                raise ValueError("Section references unavailable blocks")
            evidence(item["evidence"], {i: blocks[i] for i in item["block_ids"]})
    elif stage == "title":
        for item in response["promises"]:
            evidence(item["evidence"], blocks)
            if item["state"] in {"fulfilled", "partial"} and not item["evidence"]:
                raise ValueError("Fulfilled title promises require evidence")
            if item["state"] == "unfulfilled" and packet["coverage"]["omitted_block_ids"]:
                raise ValueError("Partial body coverage cannot establish an unfulfilled promise")
        if not packet.get("title", "").strip() and response["components"]["title_body_consistency"]["applicability"] != "not_applicable":
            raise ValueError("Missing title must be not applicable")
    elif stage == "support":
        if not support and response["components"]["evidence_support"]["applicability"] != "unassessable":
            raise ValueError("Without an evidence pack, support is unassessable")
        for item in response["claims"]:
            evidence(item["claim_evidence"], blocks)
            evidence(item["support_evidence"], support)
            if not item["claim_evidence"]:
                raise ValueError("Claims must be traceable to the assessed page")
            if item["state"] in {"supported", "contradicted"} and not item["support_evidence"]:
                raise ValueError("Support/contradiction requires evidence from the supplied pack")
            if not support and item["state"] != "unassessable":
                raise ValueError("No evidence pack means claim support is unassessable")
