"""Publish exact raw-row, document, embedding shard and projection joins."""

from collections import Counter, defaultdict
import fcntl
import json
from pathlib import Path
import sqlite3

from .cache import default_cache_root, embedding_config, request_key
from .corpus import FIELDS
from .storage import atomic_bytes, digest, file_hash, load_run, read_json, read_rows, write_json, write_rows


def publish(run, model_name, output, *, sample_limit=50):
    run, output = Path(run).resolve(), Path(output)
    manifest = load_run(run)
    model = manifest['models'][model_name]
    if model['status'] != 'complete':
        raise ValueError('Lineage publication requires completed embeddings')
    upstream = manifest['upstream']
    source = Path(upstream['path'])
    recipe = None
    if (source / 'run_identity.json').exists():
        identity = read_json(source / 'run_identity.json')
        if digest(identity) != upstream['manifest']['run_identity']:
            raise ValueError('Preprocessing recipe identity differs from manifest')
        recipe = {'path':str(source / 'run_identity.json'), 'sha256':file_hash(source / 'run_identity.json'),
                  'configuration':identity}
    for relative, expected in upstream['hashes'].items():
        if file_hash(source / relative) != expected:
            raise ValueError(f'Preprocessed lineage artifact changed: {relative}')
    raw = source.parent.parent / 'raw'
    for name, expected in upstream['manifest']['source_files'].items():
        if file_hash(raw / name) != expected:
            raise ValueError('Raw lineage source hash differs')
    units = read_rows(run / 'units.parquet')
    associations = read_rows(run / 'associations.parquet')
    index = {r['unit_id']:r for r in read_json(run / 'vectors' / model['config_id'] / 'index.json')}
    cache = Path(model.get('cache_root') or default_cache_root(run)).resolve()
    with sqlite3.connect((cache / 'catalog.sqlite3').as_uri()+'?mode=ro', uri=True) as connection:
        locations = {rid:(shard,row,sha) for rid,shard,row,sha in connection.execute(
            'SELECT request_id,shard,row_number,sha256 FROM vectors WHERE model_identity=?', (model['embedding_identity'],))}
    checked_shards = {}
    projection_fields = {}
    for name, view, subview in FIELDS:
        for identity, info in manifest.get('projections', {}).items():
            if info['model_config_id'] == model['config_id'] and info['view'] == view and info.get('subview') == subview:
                projection_fields[name] = {'projection_id':identity,'path':info['path'],
                    'dimensions':info['components'],'scope':info['scope'],
                    'fit_sha256':manifest['artifacts'][info['path']+'/pca.npz'],
                    'coordinates_sha256':manifest['artifacts'][info['path']+'/pca.parquet']}
    if len(projection_fields) != len(FIELDS):
        raise ValueError('Require all seven field projections before publishing lineage')
    rows, grouped, queries = [], defaultdict(list), {}
    for unit in units:
        uid = unit['unit_id']
        exported = index[uid]
        rid = request_key(unit, manifest['configuration']['models'][model_name]) if unit['status']=='ready' else None
        location = locations.get(rid)
        if unit['status']=='ready' and exported['status']=='success' and location is None:
            raise ValueError('Successful unit missing from shared cache lineage')
        if unit['status']=='ready' and exported.get('request_id') != rid:
            raise ValueError('Export request identity differs from exact embedding input')
        if location and location[0] not in checked_shards:
            if file_hash(cache / location[0]) != location[2]:
                raise ValueError('Lineage vector shard checksum mismatch')
            path = (cache / location[0]).with_suffix('.json')
            metadata = read_json(path)
            if metadata['sha256'] != location[2] or metadata['model_identity'] != model['embedding_identity']:
                raise ValueError('Lineage shard manifest identity mismatch')
            checked_shards[location[0]] = (metadata['request_ids'], file_hash(path))
        if location:
            ids = checked_shards[location[0]][0]
            if location[1] < 0 or location[1] >= len(ids) or ids[location[1]] != rid:
                raise ValueError('Lineage catalog row differs from shard request identity')
        fields = [name for name, view, subview in FIELDS if unit['view']==view
                  and (subview is None or unit['subview'].startswith(subview))
                  and not unit['subview'].endswith(':chunk') and exported['status']=='success']
        row = {'unit_id':uid,'snapshot_id':unit['snapshot_id'],'extraction_id':unit['extraction_id'],
               'view':unit['view'],'subview':unit['subview'],'role':unit['role'],
               'input_status':unit['status'],'vector_status':exported['status'],
               'text_hash':unit['text_hash'],'request_id':rid,
               'block_ids':unit['block_ids'],'source_chunk_ids':unit['source_chunk_ids'],
               'serialized_start':unit['serialized_start'],'serialized_end':unit['serialized_end'],
               'serialized_range_basis':'Unicode character offsets in serialized view/chunk body, excluding heading-prefix context',
               'content_weight':unit['content_weight'],'diagnostics_json':unit['diagnostics_json'],
               'pool_member_ids':json.loads(unit['diagnostics_json']).get('members', []),
               'pool_recipe':'byte-weighted mean, then L2 normalization' if unit['status']=='derived' else None,
               'shard':location[0] if location else None,'shard_row':location[1] if location else None,
               'shard_sha256':location[2] if location else None,
               'shard_manifest_sha256':checked_shards[location[0]][1] if location else None,
               'export_row':exported.get('row'), 'projection_fields':fields}
        rows.append(row)
        if unit['snapshot_id']:
            grouped[unit['snapshot_id']].append(row)
        else:
            queries[uid] = row
    documents = {r['snapshot_id']:r for r in read_rows(source / 'documents.parquet')}
    record_rows, previews = [], []
    for association in associations:
        sid = association['snapshot_id']
        document = documents[sid]
        related = grouped[sid]
        row = {**association, 'raw_path':str(raw / Path(association['source_file']).name),
               'document_path':str(source / document['document_path']),
               'document_sha256':document['sha256'], 'document_blocks':document['blocks'],
               'document_chunks':document['chunks'], 'embedding_run':str(run),
               'query_request_id':queries[association['query_unit_id']]['request_id'],
               'source_unit_count':len(related),
               'successful_source_vectors':sum(r['vector_status']=='success' for r in related)}
        record_rows.append(row)
        examples = []
        for name, view, subview in FIELDS:
            candidates = [queries[association['query_unit_id']]] if name=='query' else [r for r in related if r['view']==view and (subview is None or r['subview'].startswith(subview)) and not r['subview'].endswith(':chunk')]
            example = next((r for r in candidates if r['vector_status']=='success'), None)
            if example:
                example = {**{key:example[key] for key in ('unit_id','request_id','shard','shard_row','export_row')},
                           'source_chunk_ids':example['source_chunk_ids'][:3],
                           'source_chunk_count':len(example['source_chunk_ids']),
                           'pool_member_ids':example['pool_member_ids'][:3],
                           'pool_member_count':len(example['pool_member_ids'])}
            examples.append({'field':name,'units':len(candidates),'vectors':sum(r['vector_status']=='success' for r in candidates),
                             'example':example})
        previews.append({**row,'fields':examples})
    folder = run / 'lineage'
    write_rows(folder / 'records.parquet', record_rows)
    write_rows(folder / 'units.parquet', rows)
    summary = {'schema_version':'data-lineage-v1','status':'complete','run':str(run),
               'raw_root':str(raw),'preprocessed_root':str(source),
               'preprocessing_run_identity':upstream['manifest']['run_identity'],
               'preprocessing_pipeline':upstream['manifest']['pipeline_version'],
               'preprocessing_manifest_sha256':upstream['hashes']['manifest.json'],
               'preprocessing_recipe':recipe,
               'raw_source_hashes':upstream['manifest']['source_files'],
               'split_reference':upstream.get('split_reference'),
               'embedding_serializer':manifest['serializer_version'],
               'model':{**model,'dimensions':manifest['configuration']['models'][model_name]['dimensions']},
               'cache_preflight':read_json(run / 'cache-preflight.json') if (run / 'cache-preflight.json').exists() else None,
               'embedding_model_configuration':embedding_config(manifest['configuration']['models'][model_name]),
               'embedding_input_recipe':{key:manifest['configuration'][key] for key in ('chunk_bytes','page_bytes','counting_policy','seed')},
               'scope':manifest['scope'],'upstream_records':upstream['source_records'],
               'records':len(associations),'snapshots':len(documents),'units':len(units),
               'vector_statuses':dict(Counter(r['vector_status'] for r in rows)),
               'projection_fields':projection_fields,'cache_root':str(cache),
               'joins':{'raw_to_record':['source_file_hash','source_row'],
                       'record_to_document':['snapshot_id','document_sha256'],
                       'document_to_units':['extraction_id','block_ids','source_chunk_ids'],
                       'query_to_records':['query_unit_id'],
                       'unit_to_cache':['request_id','shard','shard_row','shard_sha256'],
                       'unit_to_export':['unit_id','export_row'],
                       'unit_to_projection':['unit_id','projection_fields']},
               'artifacts':{name:file_hash(folder / name) for name in ('records.parquet','units.parquet')},
               'verified_vector_shards':len(checked_shards),
               'limitations':['Source row offsets and shard/export rows are zero-based.',
                   'Query/title/path vectors may reuse previous runs when exact text, role and model identity match.',
                   'Derived pooled units have member lineage rather than a direct API request.',
                   'Independent field PCA bases cannot be compared with cross-field cosine.',
                   'Mechanical source integrity is not human relevance or citation-uplift evidence.']}
    write_json(folder / 'manifest.json', summary)
    data = {'summary':summary,'records':previews,'sample':False}
    render(folder / 'tracker.html', data)
    render(output, {**data,'records':previews[:sample_limit],'sample':True})
    write_json(output.with_suffix('.json'), summary)
    for name in ('records.parquet','units.parquet','manifest.json','tracker.html'):
        manifest['artifacts']['lineage/'+name] = file_hash(folder / name)
    manifest['lineage'] = {'path':'lineage/manifest.json', 'tracker':'lineage/tracker.html'}
    write_json(run / 'manifest.json', manifest)
    registry_folder = raw.parent / 'lineage'
    registry_folder.mkdir(exist_ok=True)
    with (registry_folder / '.registry.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        registry_path = registry_folder / 'registry.json'
        registry = read_json(registry_path) if registry_path.exists() else {'schema_version':'data-lineage-registry-v1','runs':{}}
        registry['runs'][run.name] = {'run':str(run),'preprocessed_root':str(source),
            'preprocessing_run_identity':summary['preprocessing_run_identity'],
            'model':model['model'],'embedding_identity':model['embedding_identity'],
            'lineage_manifest':str(folder / 'manifest.json'),
            'lineage_manifest_sha256':file_hash(folder / 'manifest.json'),
            'tracker':str(folder / 'tracker.html'),'feature_bundle':str(run / 'features/openai-v1.json'),
            'status':'complete'}
        registry['latest_complete_run'] = run.name
        write_json(registry_path, registry)
        atomic_bytes(registry_folder / 'index.html', (folder / 'tracker.html').read_bytes())
        fcntl.flock(guard, fcntl.LOCK_UN)
    return summary


def render(output, data):
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    template = Path(__file__).with_name('lineage_template.html').read_text()
    atomic_bytes(output, template.replace('__LINEAGE_DATA__',payload).encode())
