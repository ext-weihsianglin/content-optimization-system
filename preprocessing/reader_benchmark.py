"""Benchmark a localhost MLX Reader-LM server against saved frozen snapshots."""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from markdown_it import MarkdownIt

from preprocessing.blocks import blocks_to_text, html_to_blocks
from preprocessing.schema import CandidateResult, snapshot_identity, stable_hash


def local_endpoint(endpoint):
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password:
        raise ValueError("Only an explicit loopback HTTP endpoint is allowed")
    return endpoint


def prepare_prompt(tokenizer, payload, budget):
    tokens = tokenizer.encode(payload, add_special_tokens=False)
    overhead = len(tokenizer.apply_chat_template([{"role": "user", "content": ""}], tokenize=True, add_generation_prompt=False))
    available = budget - overhead
    if available <= 0:
        raise ValueError("Input budget is smaller than chat template")
    truncated = len(tokens) > available
    while True:
        selected = tokenizer.decode(tokens[:available]) if truncated else payload
        prompt = tokenizer.apply_chat_template([{"role": "user", "content": selected}], tokenize=False, add_generation_prompt=False)
        prompt_tokens = len(tokenizer.encode(prompt, add_special_tokens=False))
        if prompt_tokens <= budget:
            break
        available -= prompt_tokens - budget + 8
        truncated = True
        if available <= 0:
            raise ValueError("Cannot fit tokenized payload into input budget")
    return prompt, {"source_tokens": len(tokens), "input_tokens": prompt_tokens, "input_truncated": truncated}


def output_result(response, href, diagnostics):
    choice = response["choices"][0]
    markdown = choice["text"]
    prefix = "<|im_start|>assistant\n"
    diagnostics["assistant_prefix_removed"] = markdown.startswith(prefix)
    if markdown.startswith(prefix):
        markdown = markdown[len(prefix):]
    html = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    blocks = html_to_blocks(html, href)
    for block in blocks:
        block["source_locator"] = None
        block["mapping_status"] = "unavailable"
    text = blocks_to_text(blocks)
    diagnostics.update(finish_reason=choice.get("finish_reason"), output_capped=choice.get("finish_reason") == "length", usage=response.get("usage", {}), source_mapping="Generated output is not assumed to be a faithful copy")
    return CandidateResult("reader_lm", status="ok" if text.strip() else "empty", text=text, markdown=markdown, html=html, blocks=blocks, diagnostics=diagnostics)


def main():
    from transformers import AutoTokenizer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/processed/reader-lm-v1")
    parser.add_argument("--config", default="preprocessing/reader_config.json")
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--snapshot-id", action="append")
    args = parser.parse_args()
    configuration = json.loads(Path(args.config).read_text())
    endpoint = local_endpoint(configuration["endpoint"])
    manifest = json.loads(Path("evaluation/extraction/manifest.json").read_text())
    assert stable_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}) == manifest["manifest_hash"]
    references = json.loads(Path("evaluation/extraction/annotations.json").read_text())
    assert stable_hash({key: value for key, value in references.items() if key != "reference_hash"}) == references["reference_hash"]
    paths = [Path(__file__), Path("preprocessing/blocks.py"), Path("preprocessing/schema.py"), Path("preprocessing/evaluate.py")]
    paths += sorted(Path(configuration["model_path"]).glob("*.json")) + sorted(Path(configuration["model_path"]).glob("*.safetensors"))
    if not list(Path(configuration["model_path"]).glob("*.safetensors")):
        raise ValueError("Pinned local model weights are missing")
    fingerprints = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    dependencies = {name: version(name) for name in ["mlx", "mlx-lm", "transformers", "tokenizers", "markdown-it-py", "beautifulsoup4"]}
    identity = stable_hash({"config": configuration, "files": fingerprints, "dependencies": dependencies, "manifest": manifest["manifest_hash"], "references": references["reference_hash"]})
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    results_path = output / "results.jsonl"
    run_path = output / "manifest.json"
    if results_path.exists() and not args.resume:
        raise ValueError("Existing results; use --resume or another output directory")
    if run_path.exists() and json.loads(run_path.read_text())["run_identity"] != identity:
        raise ValueError("Frozen run changed; cannot reuse results")
    done = set()
    if results_path.exists():
        for line in results_path.open():
            row = json.loads(line)
            if row["run_identity"] != identity or row["snapshot_id"] in done:
                raise ValueError("Mixed or duplicate results")
            done.add(row["snapshot_id"])
    run = {"run_identity": identity, "configuration": configuration, "fingerprints": fingerprints, "dependencies": dependencies, "manifest_hash": manifest["manifest_hash"], "reference_hash": references["reference_hash"], "status": "running", "split": args.split, "limit": args.limit}
    run_path.write_text(json.dumps(run, indent=2) + "\n")
    tokenizer = AutoTokenizer.from_pretrained(configuration["model_path"], local_files_only=True, trust_remote_code=False)
    entries = [entry for entry in manifest["snapshots"] if args.split == "all" or entry["split"] == args.split]
    if args.snapshot_id:
        entries = [entry for entry in entries if entry["snapshot_id"] in args.snapshot_id]
    if args.limit:
        entries = entries[:args.limit]
    with results_path.open("a") as stream:
        for entry in entries:
            if entry["snapshot_id"] in done:
                continue
            started = time.perf_counter()
            diagnostics = {}
            try:
                payload = Path("data/evaluation", entry["snapshot_id"] + ".txt").read_text()
                if snapshot_identity(payload, entry["href"]) != (entry["payload_hash"], entry["snapshot_id"]):
                    raise ValueError("Snapshot hash mismatch")
                if entry["format"] != "html":
                    result = CandidateResult("reader_lm", "unsupported_format")
                else:
                    prompt, diagnostics = prepare_prompt(tokenizer, payload, configuration["max_input_tokens"])
                    body = {"model": "default_model", "prompt": prompt, "max_tokens": configuration["max_output_tokens"], "temperature": configuration["temperature"], "repetition_penalty": configuration["repetition_penalty"], "repetition_context_size": configuration["repetition_context_size"], "stream": False}
                    request = Request(endpoint, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                    with urlopen(request, timeout=configuration["timeout_seconds"]) as response:
                        result = output_result(json.load(response), entry["href"], diagnostics)
            except TimeoutError as error:
                result = CandidateResult("reader_lm", "timeout", diagnostics={**diagnostics, "error": str(error)})
            except Exception as error:
                result = CandidateResult("reader_lm", "error", diagnostics={**diagnostics, "error": f"{type(error).__name__}: {error}"})
            row = {"snapshot_id": entry["snapshot_id"], **result.to_dict(), "runtime_ms": round((time.perf_counter() - started) * 1000, 3), "run_identity": identity}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            done.add(entry["snapshot_id"])
            print(f"{len(done)}/100 {entry['split']} {entry['hostname']} {result.status} {row['runtime_ms']/1000:.1f}s", flush=True)
    run.update(status="complete" if len(done) == 100 else "partial", outcomes=len(done))
    run_path.write_text(json.dumps(run, indent=2) + "\n")


if __name__ == "__main__":
    main()
