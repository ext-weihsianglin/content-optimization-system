"""Bounded, resumable OpenAI smoke annotation with saved requests and responses."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from encoder_scorer.contracts import SCHEMA_VERSION, validate_response
from encoder_scorer.curate import canonical, sha256
from encoder_scorer.packets import MARKDOWN_RECIPE, request
from encoder_scorer.selection import CONTRACT, EVIDENCE_GRANULARITY, assemble, prepare

# Standard text prices checked against official model cards on 2026-10-01.
# Cached input is charged at the full input rate here for a conservative estimate.
PRICES = {"gpt-5": (1.25, 10.00), "gpt-5-mini": (0.25, 2.00),
          "gpt-5.6-luna": (0.20, 1.20), "gpt-5.6-terra": (2.00, 12.00), "gpt-5.6-sol": (4.00, 20.00)}
OUTPUT_LIMITS = {"requirements": 4000, "body": 10000, "title": 5000}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def estimated_cost(model, input_tokens, output_tokens):
    inp, out = PRICES[model]
    return (input_tokens * inp + output_tokens * out) / 1_000_000


class OpenAITransport:
    def __init__(self):
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("OPENAI_API_KEY is required; no secret is saved or printed")

    def post(self, endpoint, body):
        req = urllib.request.Request("https://api.openai.com/v1/" + endpoint,
            data=canonical(body).encode(), headers={"Authorization": "Bearer " + self.key,
            "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # No headers/credentials in errors or trace files.
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"OpenAI HTTP {error.code}: {detail[:1500]}") from None


def api_payload(task, model, effort):
    return {"model": model, "instructions": task["system"], "input": canonical(task["input"]),
            "reasoning": {"effort": effort}, "store": False,
            "max_output_tokens": OUTPUT_LIMITS[task["stage"]],
            "text": {"format": {"type": "json_schema", "name": "teacher_" + task["stage"],
                                 "strict": True, "schema": task["response_schema"]}}}


def response_label(response):
    if response.get("status") != "completed":
        raise ValueError("Incomplete or unsuccessful model response: " + str(response.get("incomplete_details") or response.get("error")))
    texts = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise ValueError("Model refusal")
            if content.get("type") == "output_text":
                texts.append(content["text"])
    if not texts:
        raise ValueError("Response contains no visible structured output")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result and canonical(result[key]) != canonical(value):
                raise ValueError("Conflicting duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads("".join(texts), object_pairs_hook=unique_keys)


class Runner:
    def __init__(self, output, config, transport, resume=False):
        config = json.loads(canonical(config))
        self.output, self.config, self.transport = output, config, transport
        self.lock = threading.RLock()
        manifest = output / "manifest.json"
        if manifest.exists():
            if not resume or json.loads(manifest.read_text())["config"] != config:
                raise ValueError("Resume requires identical frozen run configuration")
        elif output.exists():
            raise FileExistsError("Incomplete output directory; use a fresh run path")
        else:
            output.mkdir(parents=True)
            (output / "traces").mkdir()
            write_json(manifest, {"version": "openai-teacher-smoke-v1", "created_at": now(), "config": config})

    def traces(self):
        return [json.loads(p.read_text()) for p in sorted((self.output / "traces").glob("*.json"))]

    def assess(self, record_id, model, stage, task, requirements=None):
        task = prepare(task)
        body = api_payload(task, model, self.config["reasoning_effort"])
        body_hash = sha256(canonical(body).encode())
        existing = [t for t in self.traces() if t["record_id"] == record_id and t["model"] == model
                    and t["stage"] == stage and t["base_request_sha256"] == body_hash]
        valid = [t for t in existing if t.get("validation_status") == "valid"]
        if valid:
            return valid[-1]["label"]
        # Never repeat an ambiguous network call or restart more than one repair.
        if any(t.get("execution_status") == "pending" for t in existing):
            raise RuntimeError("Ambiguous/failed transport call retained; inspect it before a new run")
        if any(t.get("execution_status") == "transport_error" for t in existing) and not self.config.get("allow_transport_retry"):
            raise RuntimeError("Ambiguous/failed transport call retained; inspect it before a new run")
        for attempt in range(len(existing), 2):
            payload = dict(body)
            if attempt and existing[-1].get("execution_status") != "transport_error":
                previous = existing[-1]
                repair = {"validation_error": previous.get("validation_error"),
                          "previous_output": previous.get("provider_selection", previous.get("label")),
                          "instruction": "Correct the validation failure. Do not invent evidence. Return a complete replacement matching the original schema."}
                payload["input"] = canonical({"original_input": task["input"], "repair": repair})
            token_request = {k: payload[k] for k in ("model", "instructions", "input")}
            token_response = self.transport.post("responses/input_tokens", token_request)
            # Count the actual instructions/input. Add a conservative schema/overhead
            # reserve because token-count endpoint text-format accounting can differ.
            base_tokens = token_response["input_tokens"]
            upper_tokens = base_tokens + len(canonical(task["response_schema"]).encode()) + 1024
            if upper_tokens > self.config["max_input_tokens"]:
                raise ValueError("Input exceeds frozen token budget; no content is silently truncated")
            reserve = estimated_cost(model, upper_tokens, payload["max_output_tokens"])
            with self.lock:
                traces = self.traces()
                spent = sum(t.get("estimated_cost_usd", t["reserved_cost_usd"]) for t in traces)
                if len(traces) >= self.config["max_calls"] or spent + reserve > self.config["budget_usd"]:
                    raise RuntimeError("Frozen call/spend cap reached")
                trace = {"record_id": record_id, "model": model, "stage": stage, "attempt": attempt + 1,
                     "base_request_sha256": body_hash, "request_sha256": sha256(canonical(payload).encode()),
                     "request": payload, "token_count_request": token_request, "token_count_response": token_response,
                     "input_tokens_reserved": upper_tokens, "reserved_cost_usd": reserve, "started_at": now(),
                     "execution_status": "pending", "validation_status": "pending"}
                path = self.output / "traces" / f"{len(traces):04d}-{record_id[:12]}-{model}-{stage}-{attempt + 1}.json"
                if attempt and existing[-1].get("execution_status") == "transport_error":
                    trace["retry_reason"] = "Explicit bounded transport recovery; previous unknown call keeps its full cost reservation"
                write_json(path, trace)  # Reserve budget durably before issuing the request.
            start = time.monotonic()
            try:
                response = self.transport.post("responses", payload)
                trace.update(response=response, execution_status="returned", latency_seconds=time.monotonic() - start,
                             completed_at=now(), returned_model=response.get("model"), response_id=response.get("id"))
                usage = response.get("usage")
                if usage is not None:
                    trace["usage"] = usage
                    trace["estimated_cost_usd"] = estimated_cost(model, usage["input_tokens"], usage["output_tokens"])
                try:
                    selection = response_label(response)
                    trace["provider_selection"] = selection
                    label = assemble(task, selection)
                    trace["label"] = label
                    validate_response(stage, label, task["input"], requirements)
                    trace["validation_status"] = "valid"
                except (ValueError, KeyError, TypeError) as error:
                    trace.update(validation_status="invalid", validation_error=str(error))
            except Exception as error:
                trace.update(execution_status="transport_error", validation_status="unavailable",
                             transport_error=str(error), latency_seconds=time.monotonic() - start, completed_at=now())
                write_json(path, trace)
                existing.append(trace)
                if self.config.get("allow_transport_retry") and attempt == 0:
                    continue
                raise
            write_json(path, trace)
            existing.append(trace)
            print(json.dumps({"record": record_id[:12], "model": model, "stage": stage,
                              "validation": trace["validation_status"], "seconds": round(trace["latency_seconds"], 1)}), flush=True)
            if trace["validation_status"] == "valid":
                return trace["label"]
        return None


def annotate_case(runner, item, model, rubric):
    packet = item["packet"]
    result = {"record_id": item["record_id"], "split": item["split"], "model": model,
              "packet_sha256": item["packet_sha256"], "coverage": packet["coverage"], "stages": {}}
    errors = {}
    def assess(stage, task, requirements=None):
        try:
            return runner.assess(item["record_id"], model, stage, task, requirements)
        except (RuntimeError, ValueError, TimeoutError) as error:
            errors[stage] = str(error)
            return None
    req = assess("requirements", request("requirements", packet, rubric))
    result["stages"]["requirements"] = req
    if req is not None:
        result["stages"]["body"] = assess("body", request("body", packet, rubric, requirements=req), req)
    result["stages"]["title"] = assess("title", request("title", packet, rubric, title=item["title"]))
    result["errors"] = errors
    # No evidence pack in the smoke packets: honest abstention requires no paid call.
    result["stages"]["support"] = {"schema_version": SCHEMA_VERSION, "claims": [], "components": {
        "evidence_support": {"score": None, "applicability": "unassessable", "reason": "No separately supplied evidence pack in this smoke packet.", "evidence": []}},
        "limitations": ["Deterministic missing-evidence abstention, not a teacher judgment"]}
    result["support_origin"] = "deterministic_missing_evidence_abstention"
    return result


def seed_valid_traces(runner, source):
    """Reuse matching completed calls across a code revision with explicit lineage."""
    if runner.traces():
        return
    previous = json.loads((source / "manifest.json").read_text())
    old, new = previous["config"], json.loads(canonical(runner.config))
    comparable = lambda c: {k: v for k, v in c.items() if k not in {"code_sha256", "seed_manifest_sha256", "allow_transport_retry", "concurrency"}}
    if comparable(old) != comparable(new):
        raise ValueError("Seed run has different model, inputs, rubric, prices, budget, or decoding settings")
    for path in sorted((source / "traces").glob("*.json")):
        trace = json.loads(path.read_text())
        if trace["execution_status"] == "pending":
            raise ValueError("A pending call must be inspected before migration")
        if trace["request_sha256"] != sha256(canonical(trace["request"]).encode()):
            raise ValueError("Seed request identity mismatch")
        trace["seed_source_trace_sha256"] = sha256(path.read_bytes())
        trace["seed_source_manifest_sha256"] = sha256((source / "manifest.json").read_bytes())
        write_json(runner.output / "traces" / path.name, trace)


def run(packets_dir, output, model, review_model=None, review_count=0, effort="medium", budget=10., max_cases=12,
        resume=False, transport=None, stop_after=None, seed_from=None, allow_transport_retry=False, concurrency=1):
    if budget <= 0:
        raise ValueError("A positive explicit smoke budget is required")
    if model not in PRICES or (review_model and review_model not in PRICES):
        raise ValueError("Model needs verified explicit pricing; no automatic substitution")
    if not 1 <= max_cases <= 12 or not 0 <= review_count <= max_cases:
        raise ValueError("Smoke run is bounded to 12 cases")
    if review_count and (not review_model or review_model == model):
        raise ValueError("Independent comparison needs a different explicit model")
    packets_path = packets_dir / "packets.jsonl"
    packet_manifest = json.loads((packets_dir / "manifest.json").read_text())
    if packet_manifest.get("serialization") != MARKDOWN_RECIPE or not packet_manifest.get("source_run_identity"):
        raise ValueError("New annotations require versioned markdownify packets; old-source labels remain separate")
    if sha256(packets_path.read_bytes()) != packet_manifest["packets_sha256"]:
        raise ValueError("Packets changed after preparation")
    items = [json.loads(line) for line in packets_path.open()][:max_cases]
    if any(i["split"] != "train" for i in items):
        raise ValueError("Smoke execution is restricted to training packets")
    rubric_path = Path("evaluation/teacher/rubric.md")
    rubric = rubric_path.read_text()
    if sha256(rubric.encode()) != packet_manifest["rubric_sha256"]:
        raise ValueError("Rubric changed; prepare a new packet version")
    for item in items:
        if sha256(canonical(item["packet"]).encode()) != item["packet_sha256"]:
            raise ValueError("Packet identity mismatch")
    review_ids = sorted(i["record_id"] for i in sorted(items, key=lambda i: sha256(("independent-teacher-v1" + i["record_id"]).encode()))[:review_count])
    config = {"primary_model": model, "review_model": review_model, "review_ids": review_ids,
              "record_ids": [i["record_id"] for i in items], "packets_sha256": packet_manifest["packets_sha256"],
              "rubric_sha256": packet_manifest["rubric_sha256"], "reasoning_effort": effort,
              "budget_usd": budget, "max_calls": 2 * 3 * (len(items) + review_count),
              "max_input_tokens": 100000, "output_limits": OUTPUT_LIMITS, "prices": PRICES,
              "allow_transport_retry": allow_transport_retry, "concurrency": concurrency,
              "provider_contract": CONTRACT, "evidence_granularity": EVIDENCE_GRANULARITY,
              "price_date": "2026-10-01", "price_policy": "uncached standard input/output estimate, not billing invoice",
              "code_sha256": {str(p): sha256(p.read_bytes()) for p in sorted(Path("encoder_scorer").glob("*.py"))}}
    if seed_from is not None:
        config["seed_manifest_sha256"] = sha256((seed_from / "manifest.json").read_bytes())
    runner = Runner(output, config, transport or OpenAITransport(), resume)
    if seed_from is not None:
        seed_valid_traces(runner, seed_from)
    results = []
    try:
        active = items if stop_after is None else items[:stop_after]
        def worker(item):
            labels = [annotate_case(runner, item, model, rubric)]
            if item["record_id"] in review_ids:
                labels.append(annotate_case(runner, item, review_model, rubric))
            return labels
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(worker, item) for item in active]
            for future in as_completed(futures):
                results.extend(future.result())
                order = {i["record_id"]: n for n, i in enumerate(items)}
                results.sort(key=lambda r: (order[r["record_id"]], r["model"] != model))
                write_json(output / "labels.json", results)
    finally:
        traces = runner.traces()
        write_json(output / "summary.json", {"started_cases_completed": len(results), "primary_model": model,
            "review_model": review_model, "generation_calls": len(traces),
            "planned_primary_cases": len(items), "completed_primary_cases": sum(r["model"] == model for r in results),
            "valid_calls": sum(t.get("validation_status") == "valid" for t in traces),
            "invalid_calls": sum(t.get("validation_status") == "invalid" for t in traces),
            "estimated_cost_usd": sum(t.get("estimated_cost_usd", t["reserved_cost_usd"]) for t in traces),
            "cost_is_estimate": True, "human_reviewed_cases": 0,
            "returned_models": sorted({t["returned_model"] for t in traces if t.get("returned_model")}),
            "limitations": ["Teacher labels awaiting human review; no reliability certification or student training",
                            f"{sum(bool(i['packet']['coverage']['omitted_block_ids']) for i in items)} prepared smoke views are partial; scores concern available views",
                            "Evidence support abstains deterministically because no evidence pack was supplied"]})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True, choices=PRICES)
    parser.add_argument("--review-model", choices=PRICES)
    parser.add_argument("--review-count", type=int, default=0)
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--budget-usd", type=float, default=10)
    parser.add_argument("--max-cases", type=int, default=12)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int, help="Pause after this many primary cases without changing the frozen 12-case plan")
    parser.add_argument("--seed-from", type=Path, help="Reuse validated calls from an identical-input run, recording code-revision lineage")
    parser.add_argument("--allow-transport-retry", action="store_true", help="Allow one recorded retry while preserving unknown-call cost reservations")
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    run(args.packets, args.output, args.model, args.review_model, args.review_count, args.effort,
        args.budget_usd, args.max_cases, args.resume, stop_after=args.stop_after, seed_from=args.seed_from,
        allow_transport_retry=args.allow_transport_retry, concurrency=args.concurrency)


if __name__ == "__main__":
    main()
