"""Measure corpus token/storage volume without invoking embedding APIs."""

from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path
import sqlite3

import pyarrow.parquet as pq
import tiktoken
from tokenizers import Tokenizer

from .cache import default_cache_root, embedding_config, request_key
from .storage import digest, file_hash, load_run, write_json


def measure(run, output, *, voyage_tokenizer, cache_root=None, tokenizer_revision=None):
    run = Path(run)
    manifest = load_run(run)
    config = manifest['configuration']['models']
    models = {name: cfg for name, cfg in config.items() if cfg['provider'] in {'openai', 'voyage', 'mlx'}}
    if not models:
        raise ValueError('Require configured OpenAI or Voyage models')
    openai = tiktoken.get_encoding('cl100k_base')
    voyage = Tokenizer.from_file(str(voyage_tokenizer))
    # Tokenizer configs may declare truncation/padding; counts must be lossless.
    voyage.no_truncation(); voyage.no_padding()
    root = Path(cache_root or default_cache_root(run)).resolve()
    from datetime import datetime, timezone
    cache_snapshot_time = datetime.now(timezone.utc).isoformat()
    catalog = root / 'catalog.sqlite3'
    cached = defaultdict(set)
    if catalog.is_file():
        connection = sqlite3.connect(catalog.as_uri() + '?mode=ro', uri=True)
        try:
            for identity, rid in connection.execute('SELECT model_identity, request_id FROM vectors'):
                cached[identity].add(rid)
        finally:
            connection.close()
    seen = {name: {} for name in models}
    totals = {name: Counter() for name in models}
    logical = Counter()
    for batch in pq.ParquetFile(run / 'units.parquet').iter_batches(batch_size=1024):
        for unit in batch.to_pylist():
            logical[unit['status']] += 1
            if unit['status'] != 'ready':
                continue
            for name, cfg in models.items():
                key = request_key(unit, cfg)
                if key in seen[name]:
                    continue
                text = (cfg.get('query_instruction', '') if unit['role'] == 'query' else '') + unit['text']
                if cfg['provider'] == 'openai':
                    count = len(openai.encode(text, disallowed_special=()))
                    with_role = count
                    limit = 8192
                else:
                    count = len(voyage.encode(text, add_special_tokens=False).ids)
                    prefix = cfg['role_prompts'][unit['role']] if cfg['provider']=='mlx' else ('Represent the query for retrieving supporting documents: ' if unit['role']=='query' else 'Represent the document for retrieval: ')
                    with_role = len(voyage.encode(prefix + text, add_special_tokens=False).ids)
                    limit = 32000
                identity = digest(embedding_config(cfg))
                hit = key in cached[identity]
                seen[name][key] = (unit['role'], len(text.encode()), count, with_role, hit)
                totals[name]['unique_inputs'] += 1
                totals[name]['text_tokens'] += count
                totals[name]['tokens_with_role_context'] += with_role
                totals[name]['cached_inputs'] += hit
                totals[name]['pending_inputs'] += not hit
                totals[name]['pending_text_tokens'] += count if not hit else 0
                totals[name]['pending_tokens_with_role_context'] += with_role if not hit else 0
                totals[name]['over_context_inputs'] += with_role > limit
                totals[name]['max_input_tokens'] = max(totals[name]['max_input_tokens'], with_role)
    results = {}
    estimated_vectors = manifest['units'] - manifest['statuses'].get('unavailable', 0)
    for name, cfg in models.items():
        counts = totals[name]
        # Counts match runner grouping/order and both item and byte batch ceilings.
        groups = defaultdict(list)
        for key, (role, size, _, _, hit) in seen[name].items():
            if not hit:
                groups[role].append((key, size))
        batches = 0
        for values in groups.values():
            number = bytes_used = 0
            for _, size in sorted(values):
                if size > cfg['batch_bytes']:
                    raise ValueError('An input exceeds configured batch budget')
                if number and (number >= cfg['batch_size'] or bytes_used + size > cfg['batch_bytes']):
                    batches += 1
                    number = bytes_used = 0
                number += 1; bytes_used += size
            batches += bool(number)
        price = .13 if cfg['provider']=='openai' else .12 if cfg['provider']=='voyage' else 0
        results[name] = {**counts, 'model':cfg['model'], 'dimensions':cfg['dimensions'],
                         'pending_batches':batches, 'execution':'local_mlx' if cfg['provider']=='mlx' else 'hosted_api', 'batch_size':cfg['batch_size'], 'concurrency':cfg['concurrency'],
                         'unique_vector_bytes_float32':counts['unique_inputs'] * cfg['dimensions'] * 4,
                         'run_matrix_bytes_float32_upper_bound':estimated_vectors * cfg['dimensions'] * 4,
                         'list_price_usd_per_million_tokens':price,
                         'full_text_list_cost_usd':round(counts['text_tokens'] / 1e6 * price, 4),
                         'pending_text_list_cost_usd':round(counts['pending_text_tokens'] / 1e6 * price, 4),
                         'pending_with_role_context_list_cost_usd':round(counts['pending_tokens_with_role_context'] / 1e6 * price, 4)}
    result = {'scope':'full prepared corpus sizing; no embedding API calls', 'records':manifest['records'],
              'snapshots':manifest['upstream']['source_snapshots'], 'units':manifest['units'], 'unit_statuses':dict(logical),
              'views':manifest['views'], 'models':results, 'shared_cache':str(root), 'cache_snapshot_time':cache_snapshot_time,
              'tokenizers':{'openai':'cl100k_base', 'voyage':'Voyage 4 tokenizer (shared large/nano vocabulary)',
                            'voyage_revision':tokenizer_revision, 'voyage_sha256':file_hash(voyage_tokenizer),
                            'packages':{name:version(name) for name in ('tiktoken','tokenizers')}},
              'input_hashes':manifest['artifacts'],
              'price_sources':{'openai':'https://developers.openai.com/api/docs/models/text-embedding-3-large',
                               'voyage':'https://docs.voyageai.com/docs/pricing'},
              'pricing_checked':'2026-10-01',
              'limitations':['Tokenizer counts are local measurements; final billing follows provider-reported usage.',
                             'Voyage role-prefix counts are shown separately; no free allowance assumed.',
                             'Matrix storage excludes metadata, filesystem overhead, backups and projection artifacts.',
                             'HTTP batch counts exclude retries; runtime depends on account limits and measured throughput.']}
    write_json(output, result)
    return result
