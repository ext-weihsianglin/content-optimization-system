"""Frozen-split field projections and descriptive full-corpus summaries."""

from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from . import SERIALIZER_VERSION
from .storage import content_identity, load_run, read_json, read_rows, write_json

FIELDS = (("query", "query", None), ("document_title", "title", "document_title"),
          ("h1", "title", "h1"), ("outline", "outline", None),
          ("page", "page", None), ("section", "section", None), ("path", "path", None))


def training_manifests(run, model_name):
    """Fit only eligible train-only sources; exclude repeated held-out content."""
    run = Path(run)
    manifest = load_run(run)
    if manifest['models'][model_name]['status'] != 'complete':
        raise ValueError('Require completed corpus embeddings')
    units = read_rows(run / 'units.parquet')
    lookup = {u['unit_id']:u for u in units}
    associations = read_rows(run / 'associations.parquet')
    sources = defaultdict(list)
    for row in associations:
        sources[row['snapshot_id']].append(row)
        sources[row['query_unit_id']].append(row)
    available = {row['unit_id'] for row in read_json(run / 'vectors' / manifest['models'][model_name]['config_id'] / 'index.json') if row['status']=='success'}
    result = {}
    for name, view, subview in FIELDS:
        eligible = [u for u in units if u['view']==view and u['unit_id'] in available
                    and not u['subview'].endswith(':chunk') and (subview is None or u['subview'].startswith(subview))]
        train, heldout = [], []
        counts = Counter()
        for unit in eligible:
            rows = sources[unit['snapshot_id'] or unit['unit_id']]
            all_splits = {r['split'] for r in rows}
            usable = any(not r.get('upstream_exclusions') for r in rows)
            if not usable:
                counts['upstream_excluded_units'] += 1
            elif all_splits == {'train'}:
                train.append(unit)
            elif all_splits and all_splits <= {'validation','test'}:
                heldout.append(unit)
            else:
                counts['mixed_or_unknown_split_units'] += 1
        heldout_hashes = {content_identity(u, lookup) for u in heldout}
        fit = []
        for unit in train:
            if content_identity(unit, lookup) in heldout_hashes:
                counts['duplicate_heldout_content_units'] += 1
            else:
                fit.append(unit['unit_id'])
        if len(fit) < 33:
            raise ValueError(f'Insufficient training variation for field {name}')
        data = {'scope':'training','unit_ids':sorted(fit), 'heldout_unit_ids':sorted(u['unit_id'] for u in heldout),
                'field':name,'view':view,'subview':subview,'split_policy':'Original PR #2 hostname split assignments',
                'exclusions':dict(counts),'eligible_view_units':len(eligible),
                'input_hashes':{k:manifest['artifacts'][k] for k in ('units.parquet','associations.parquet')},
                'policy':'Eligible train-only source units; remove exact held-out content; mixed-split queries stay outside the fit.'}
        path = run / 'fit-manifests' / (name+'.json')
        write_json(path, data)
        result[name] = {'path':str(path), 'training_units':len(fit),'heldout_units':len(heldout), **dict(counts)}
    write_json(run / 'fit-manifests' / 'summary.json', result)
    return result


def summarize(run, model_name, output):
    run = Path(run)
    manifest = load_run(run)
    rows = read_rows(run / manifest['alignment'][model_name]['path'])
    features = ('title_similarity','h1_similarity','outline_similarity','page_similarity','path_similarity',
                'section_max','section_top3_mean','section_median','section_q25','section_q75')
    distributions = {}
    for feature in features:
        values = [r[feature] for r in rows if r[feature] is not None]
        distributions[feature] = {'available_records':len(values),'missing_records':len(rows)-len(values),
            'quantiles':dict(zip(('min','q25','median','q75','max'), np.quantile(values,[0,.25,.5,.75,1]).tolist())) if values else None}
    projections = []
    for identity, info in manifest.get('projections',{}).items():
        if info['model_config_id'] != manifest['models'][model_name]['config_id']:
            continue
        projections.append({'projection_id':identity,'view':info['view'],'subview':info.get('subview'),
                            'scope':info['scope'],'components':info['components'], 'solver':info.get('solver','full'),
                            'training_units':len(info['fit_unit_ids']),
                            'projected_units':len(read_rows(run / info['path'] / 'pca.parquet')),
                            'explained_variance_fraction':sum(info['explained_variance_ratio']),
                            'path':str((run / info['path']).resolve())})
    result = {'scope':'Descriptive full-corpus embedding coverage/alignment and training-only PCA; not relevance or citation-uplift evidence',
              'model':manifest['models'][model_name], 'records':len(rows),
              'alignment_statuses':dict(Counter(r['status'] for r in rows)),
              'selection_statuses':dict(Counter(r['extraction_status'] for r in rows)),
              'splits':dict(Counter(r['split'] for r in rows)), 'similarity_distributions':distributions,
              'projections':projections, 'vector_hash':manifest['alignment'][model_name]['vector_hash'],
              'artifacts_root':str(run.resolve()), 'schema_version':manifest['schema_version'],
              'serializer_version':SERIALIZER_VERSION,
              'limitations':['Original scorer split assignments are reused, not a fresh independent holdout.',
                             'PCA coordinates from different field fits cannot be used for cross-field cosine.',
                             'Higher maximum section similarity can reflect more section chunks.',
                             'Retained needs_review content remains flagged; no human relevance judgments were added.']}
    write_json(output,result)
    return result
