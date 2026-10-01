"""Pinned local Voyage nano inference on Apple silicon; no remote model code."""

from importlib.metadata import distribution, version
from pathlib import Path
import platform
import time

import numpy as np

from .providers import ProviderError
from .storage import digest, file_hash, read_json


class MLXProvider:
    def __init__(self, config):
        self.config = config
        if platform.system() != 'Darwin' or platform.machine() != 'arm64':
            raise ProviderError('mlx_requires_apple_silicon', fatal=True)
        if config['concurrency'] != 1:
            raise ProviderError('mlx_requires_single_worker', fatal=True)
        from .cache import default_cache_root
        path = Path(config.get('model_path') or default_cache_root('.').parent.parent / 'models' / 'voyage-4-nano').expanduser()
        if not path.is_dir():
            raise ProviderError('local_model_directory_missing', fatal=True)
        metadata = read_json(path / 'source.json')
        if metadata['revision'] != config['revision'] or metadata['model'] != config['model']:
            raise ProviderError('local_checkpoint_revision_mismatch', fatal=True)
        hashes = {name: file_hash(path / name) for name in config['checkpoint_files']}
        if digest(hashes) != config['checkpoint_hash']:
            raise ProviderError('local_checkpoint_checksum_mismatch', fatal=True)
        import mlx.core as mx
        if not mx.metal.is_available():
            raise ProviderError('metal_gpu_unavailable', fatal=True)
        mx.set_default_device(mx.gpu)
        from voyage_4_nano_mlx import load
        from voyage_4_nano_mlx.embedder import set_memory_budget
        if version('voyage-4-nano-mlx') != config['backend_version'] or version('mlx') != config['mlx_version']:
            raise ProviderError('local_backend_version_mismatch', fatal=True)
        import json
        provenance = json.loads(distribution('voyage-4-nano-mlx').read_text('direct_url.json') or '{}')
        if provenance.get('vcs_info', {}).get('commit_id') != config['backend_revision']:
            raise ProviderError('local_backend_revision_mismatch', fatal=True)
        set_memory_budget(limit_gb=config.get('memory_limit_gb', 8), cache_gb=.5)
        self.model = load(path, dtype=config['compute_dtype'])
        if self.model._backend != 'tokenizers':
            raise ProviderError('require_local_json_tokenizer', fatal=True)
        if self.model.prompts != config['role_prompts']:
            raise ProviderError('local_role_prompt_mismatch', fatal=True)
        self.tokenizer = self.model.tokenizer
        if config['dimensions'] not in self.model.args.matryoshka_dims:
            raise ProviderError('unsupported_local_dimension', fatal=True)

    def embed(self, texts, role):
        if role not in {'query','document'}:
            raise ProviderError('unsupported_input_role', fatal=True)
        cfg = self.config
        if any(not text.strip() or len(text.encode()) > cfg['max_input_bytes'] for text in texts):
            raise ProviderError('empty_or_oversized_input')
        self.tokenizer.no_truncation(); self.tokenizer.no_padding()
        tokens = [len(e.ids) for e in self.tokenizer.encode_batch([cfg['role_prompts'][role] + text for text in texts])]
        if max(tokens, default=0) > min(cfg['max_input_tokens'], self.model.args.max_seq_length):
            raise ProviderError('local_input_exceeds_context')
        start = time.monotonic()
        result = self.model.encode(texts, prompt_name=role, dims=cfg['dimensions'],
                                   batch_size=cfg['batch_size'], max_length=cfg['max_input_tokens'],
                                   max_tokens_per_batch=cfg.get('max_tokens_per_batch', 8192), output_dtype='float32')
        return [np.asarray(row, dtype=np.float32) for row in result], {
            'local':True, 'device':'metal_gpu', 'input_tokens_with_role_prefix':sum(tokens),
            'elapsed_seconds':time.monotonic()-start, 'inputs':len(texts)}
