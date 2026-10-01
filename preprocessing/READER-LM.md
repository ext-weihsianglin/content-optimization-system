# Local Reader-LM benchmark (Apple Silicon)

This is an additive benchmark of `jinaai/reader-lm-0.5b`, not the hosted Jina
Reader API. No API key is needed. Model weights are downloaded once from Hugging
Face; inference sends stored HTML only to a loopback MLX server. No source page
is fetched, rendered, or allowed to execute code.

The weights are CC-BY-NC-4.0. Resolve commercial licensing before adopting this
model in a commercial pipeline. The upstream model card is at
https://huggingface.co/jinaai/reader-lm-0.5b .

## Install and download

Run from the repository root. The separate environment preserves the original
benchmark's frozen dependencies.

```sh
.tools/uv venv --python 3.12 .venv-reader
.tools/uv pip install --python .venv-reader/bin/python -r preprocessing/reader-requirements.txt
.tools/uv run --python .venv-reader/bin/python --no-project python -c \
  "from huggingface_hub import snapshot_download; snapshot_download('jinaai/reader-lm-0.5b', revision='46cb69fff9d100f9c3c2a135d59f365fb99a0121', local_dir='data/models/reader-lm-0.5b', allow_patterns=['*.json','*.safetensors','*.txt','README.md'])"
```

## Serve locally

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.tools/uv run --python .venv-reader/bin/python --no-project python -m mlx_lm server \
  --model data/models/reader-lm-0.5b --host 127.0.0.1 --port 8087 \
  --max-tokens 2048 --temp 0 --decode-concurrency 1 --prompt-concurrency 1 \
  --prefill-step-size 512 --prompt-cache-size 1 --prompt-cache-bytes 1000000000 \
  --allowed-origins http://127.0.0.1:8087
```

Health check: `curl http://127.0.0.1:8087/health`. Stop the foreground server with
Ctrl-C. MLX's development HTTP server is not a production service; do not expose
this unauthenticated endpoint publicly. Weights retain their original bfloat16
precision rather than using a community quantization.

## Benchmark and report

With the server running in another terminal:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.tools/uv run --python .venv-reader/bin/python --no-project python \
  -m preprocessing.reader_benchmark --output data/processed/reader-lm-v1
.tools/uv run --offline python -m preprocessing.reader_report
open analysis/reader-lm-evaluation.html
```

Use `--resume` to continue the same run; changed code, model weights, dependency
versions, configuration, source manifest, or reference hashes invalidate it.
Full candidate Markdown/text/blocks and diagnostics live in the run's JSONL.

## Interpretation

- Same 100 snapshots, 60/40 development/held-out split, frozen AI-assisted anchors,
  and existing scoring functions. HTML is supported; 12 native-format snapshots
  receive explicit unsupported outcomes.
- This candidate was added after the original held-out results were visible. It
  is a disclosed add-on, not a newly blinded selection exercise. Original reports
  and frozen five-candidate results are left unchanged.
- Raw saved HTML enters the model through its documented user-message template.
  No query, citation label, or anchor is included in model input.
- Local input budget: **65,536 total prompt tokens**. Larger sources are prefix
  truncated, and those cases remain in score denominators. This is a local
  resource-constrained profile, not a test of the advertised full context window.
- Output budget: **2,048 generated tokens**, greedy decoding and repetition
  penalty 1.08. Output caps and input truncation are reported per document.
- An emitted leading assistant control header is removed, but content is not
  repaired or supplied from another extractor. Markdown is converted to the same
  canonical block text for anchor scoring. Source mappings are unavailable: model
  generation is not assumed to be a faithful copy.
- Retention/leakage do not detect hallucinations, changed facts, or correctly
  reconstructed table relationships. Model output is escaped in the report.
- Loopback HTTP timing includes tokenization and canonicalization but excludes
  initial weight download/server startup. MLX prefix caching can affect latency;
  timings are not directly comparable to the original in-process parser timings.
