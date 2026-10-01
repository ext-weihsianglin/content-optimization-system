"""Three-page development-only MLX diagnostic; no full benchmark or live pages."""

from collections import Counter
from html import escape
import hashlib
import json
from pathlib import Path
import time

from preprocessing.evaluate import _score
from preprocessing.reader_benchmark import output_result, prepare_prompt
from preprocessing.schema import snapshot_identity


HOSTS = ["www.digitalocean.com", "www.visitphoenix.com", "wisernotify.com"]


def repetition_detected(tokens):
    for width in range(16, min(256, len(tokens) // 3) + 1):
        if tokens[-width:] == tokens[-2 * width:-width] == tokens[-3 * width:-2 * width]:
            return width
    return None


def main():
    import mlx.core as mx
    from mlx_lm import load, stream_generate
    from mlx_lm.sample_utils import make_logits_processors, make_sampler

    directory = Path("data/processed/reader-lm-pilot-v2")
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "results.json").exists():
        raise ValueError("Pilot already exists; preserve results rather than overwrite")
    manifest = json.loads(Path("evaluation/extraction/manifest.json").read_text())
    annotations = {row["snapshot_id"]: row for row in json.loads(Path("evaluation/extraction/annotations.json").read_text())["documents"]}
    entries = [next(row for row in manifest["snapshots"] if row["hostname"] == host and row["split"] == "dev") for host in HOSTS]
    configuration = {"model": "jinaai/reader-lm-0.5b", "revision": "46cb69fff9d100f9c3c2a135d59f365fb99a0121", "input_budget": 98304, "output_budget": 32768, "prefill_step_size": 2048, "seconds_per_page": 180, "temperature": 0, "repetition_penalty": 1.08, "repetition_context_size": 131072, "backend": "Direct MLX streaming, BF16 weights, full precision KV, fresh KV per page", "input_policy": "Raw saved HTML, prefix truncation only if over budget; model-card template", "stop_guard": "Three consecutive identical token spans, span lengths 16 through 256, checked every 16 generated tokens", "selection": "Three purposively selected development examples; diagnostic only, not a fresh heldout benchmark", "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (directory / "configuration.json").write_text(json.dumps(configuration, indent=2) + "\n")
    model, tokenizer = load("data/models/reader-lm-0.5b")
    results = []
    for source in entries:
        payload = Path("data/evaluation", source["snapshot_id"] + ".txt").read_text()
        assert snapshot_identity(payload, source["href"]) == (source["payload_hash"], source["snapshot_id"])
        prompt, diagnostics = prepare_prompt(tokenizer, payload, configuration["input_budget"])
        print(f"Starting {source['hostname']}: {diagnostics['input_tokens']} tokens", flush=True)
        mx.reset_peak_memory()
        started = time.perf_counter()
        chunks, tokens = [], []
        reason, last = "stop", None
        generator = stream_generate(model, tokenizer, prompt, max_tokens=configuration["output_budget"], sampler=make_sampler(temp=0), logits_processors=make_logits_processors(repetition_penalty=1.08, repetition_context_size=131072), prefill_step_size=2048)
        try:
            for response in generator:
                last = response
                chunks.append(response.text)
                tokens.append(response.token)
                reason = response.finish_reason or "stop"
                if len(tokens) % 16 == 0 and repetition_detected(tokens):
                    reason = "repetition_guard"
                    break
                if time.perf_counter() - started >= configuration["seconds_per_page"]:
                    reason = "time_budget"
                    break
        finally:
            generator.close()
        elapsed = time.perf_counter() - started
        diagnostics.update(stop_reason=reason, requires_review=reason != "stop", prompt_tps=last.prompt_tps if last else None, generation_tps=last.generation_tps if last else None, peak_memory_gb=mx.get_peak_memory() / 1e9, generated_tokens=len(tokens), seconds=elapsed)
        result = output_result({"choices": [{"text": ''.join(chunks), "finish_reason": reason}], "usage": {"completion_tokens": len(tokens)}}, source["href"], diagnostics).to_dict()
        result.update(snapshot_id=source["snapshot_id"], runtime_ms=elapsed * 1000)
        score = _score(source, annotations[source["snapshot_id"]], result, "reader_lm")
        results.append({"source": source, "result": result, "score": score, "annotations": annotations[source["snapshot_id"]]})
        (directory / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        print(f"{source['hostname']}: {reason}; {len(tokens)} tokens; {elapsed:.1f}s; anchors {score['required_matches']}/{score['required_count']}", flush=True)
        mx.clear_cache()
    report(results, configuration)


def report(results, configuration):
    originals = {}
    for path in [Path("data/processed/reader-lm-v1/results.jsonl"), Path("data/processed/eval-v2/results.jsonl")]:
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                originals[(row["snapshot_id"], row["method"])] = row
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'"><title>Reader-LM three-page diagnostic</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:15px}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #ccc}</style><h1>Reader-LM: three development pages</h1><p>Diagnostic only. Same AI-assisted anchors; no human gold or heldout claim. Scores inspect returned text even if stopped early; nonempty output does not imply a valid extraction. Inference stops on repetition or a three-minute budget checked after each yielded token.</p><pre>' + escape(json.dumps(configuration, indent=2)) + '</pre>']
    comparisons = []
    for example in results:
        source, annotation = example["source"], example["annotations"]
        parts.append('<h2>' + escape(source["hostname"]) + '</h2><table><tr><th>Candidate</th><th>Required anchors</th><th>Unwanted anchors</th></tr>')
        candidates = [("Reader-LM expanded pilot", example["result"])]
        for method in ["reader_lm", "readability", "trafilatura"]:
            previous = originals.get((source["snapshot_id"], method))
            if previous:
                candidates.append((method + " original", previous))
        for label, candidate in candidates:
            score = _score(source, annotation, candidate, candidate["method"])
            comparisons.append({"hostname": source["hostname"], "candidate": label, "score": score})
            parts.append('<tr><td>' + escape(label) + f"</td><td>{score['required_matches']}/{score['required_count']}</td><td>{score['unwanted_matches']}/{score['unwanted_count']}</td></tr>")
        parts.append('</table><pre>' + escape(json.dumps(example["result"]["diagnostics"], indent=2)) + '</pre><details><summary>Full generated Markdown</summary><pre>' + escape(example["result"]["markdown"]) + '</pre></details><details><summary>Reference anchors</summary><pre>' + escape(json.dumps(annotation, ensure_ascii=False, indent=2)) + '</pre></details>')
    parts.append('</html>')
    Path("analysis/reader-lm-pilot.html").write_text('\n'.join(parts))
    Path("analysis/reader-lm-pilot.json").write_text(json.dumps({"configuration": configuration, "comparisons": comparisons, "examples": results}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
