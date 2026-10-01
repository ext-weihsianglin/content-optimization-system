"""Issue #10 development serializer comparison and separate held-out diagnostics.

Read only local snapshots. Always choose a fresh report directory. Markdownify is
compared only on development fixtures; held-out evidence cannot select serializers.
"""
import argparse
from collections import Counter
import hashlib
from html import escape
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
import types

from bs4 import BeautifulSoup
from markdownify import markdownify

from preprocessing.adapters.local import extract_conservative
from preprocessing.blocks import BLOCK_SCHEMA_VERSION, PRESERVE_WHITESPACE_TAGS, dom_path
from preprocessing.evaluate import normalize_anchor
from preprocessing.offline import network_disabled
from preprocessing.schema import Snapshot, snapshot_identity, stable_hash

BASELINE = '3d4d35d3c32ac5b8c14983f99f92c2f633669417'
OPTIONS = {'heading_style': 'ATX', 'bs4_options': 'html.parser'}
ROOT = Path(__file__).resolve().parents[1]


def old_extractor():
    blocks = types.ModuleType('issue10_baseline_blocks')
    adapter = types.ModuleType('issue10_baseline_adapter')
    sys.modules[blocks.__name__] = blocks
    for path, module in [('preprocessing/blocks.py', blocks), ('preprocessing/adapters/local.py', adapter)]:
        code = subprocess.check_output(['git', 'show', f'{BASELINE}:{path}'], cwd=ROOT, text=True)
        code = code.replace('from preprocessing.blocks import', 'from issue10_baseline_blocks import')
        exec(compile(code, f'{BASELINE}:{path}', 'exec'), module.__dict__)
    return adapter.extract_conservative


def annotations(blocks):
    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get('children', []))
    for block in blocks:
        yield from walk(block.get('inline_nodes', []))
        for cell in (block.get('table') or {}).get('cells', []):
            yield from walk(cell.get('inline_nodes', []))


def location_diagnostics(blocks, payload):
    soup = BeautifulSoup(payload, 'html.parser', preserve_whitespace_tags=PRESERVE_WHITESPACE_TAGS)
    paths = {dom_path(tag): tag for tag in [soup, *soup.find_all(True)]}
    counts = Counter()
    for node in [*blocks, *annotations(blocks)]:
        counts[node['mapping_status']] += 1
        locator = node.get('source_locator')
        if locator is None:
            continue
        original = paths.get(locator['dom_path'])
        valid = original is not None
        if valid and 'child_index' in locator:
            index = locator['child_index']
            valid = index < len(original.contents) and str(original.contents[index]) == node['text']
        if valid and 'tag' in node:
            valid = original.name == node['tag'] and dict(original.attrs) == node['attributes']
        counts['valid_locators' if valid else 'invalid_locators'] += 1
    return dict(counts)


def fingerprints():
    paths = ['preprocessing/blocks.py', 'preprocessing/adapters/local.py', 'preprocessing/downstream.py', 'preprocessing/inline_fidelity.py', 'evaluation/inline-fidelity/development.json', 'uv.lock']
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def development(old):
    fixtures = json.loads((ROOT / 'evaluation/inline-fidelity/development.json').read_text())
    rows = []
    for case in fixtures['cases']:
        payload_hash, identity = snapshot_identity(case['html'], fixtures['href'])
        snapshot = Snapshot(identity, payload_hash, fixtures['href'], 'example.test', case['html'], 'html')
        result = extract_conservative(snapshot)
        rows.append({**case, 'baseline_markdown': old(snapshot).markdown, 'structured_v2_markdown': result.markdown,
                     'markdownify_markdown': markdownify(case['html'], **OPTIONS),
                     'v2_expected_output_matches': result.markdown == case['expected_markdown'],
                     'source_locations': location_diagnostics(result.blocks, case['html']), 'blocks': result.blocks})
    return {'scope': 'Hand-authored development fixtures only; used for implementation and serializer decision, not held-out accuracy.',
            'markdownify_options': OPTIONS, 'results': rows}


def heldout(old, cache):
    manifest = json.loads((ROOT / 'evaluation/extraction/manifest.json').read_text())
    claimed = manifest.pop('manifest_hash')
    if stable_hash(manifest) != claimed:
        raise ValueError('Frozen manifest hash mismatch')
    references = {row['snapshot_id']: row for row in json.loads((ROOT / 'evaluation/extraction/annotations.json').read_text())['documents']}
    rows = []
    for entry in manifest['snapshots']:
        if entry['split'] != 'heldout' or entry['format'] != 'html':
            continue
        payload = (cache / f"{entry['snapshot_id']}.txt").read_text()
        payload_hash, identity = snapshot_identity(payload, entry['href'])
        if (payload_hash, identity) != (entry['payload_hash'], entry['snapshot_id']):
            raise ValueError(f'Snapshot hash mismatch: {identity}')
        snapshot = Snapshot(identity, payload_hash, entry['href'], entry['hostname'], payload, 'html')
        previous, result = old(snapshot), extract_conservative(snapshot)
        ref = references.get(identity, {})
        scores = {}
        for field in ['required', 'unwanted']:
            anchors = [normalize_anchor(anchor['text']) for anchor in ref.get(field, []) if normalize_anchor(anchor['text'])] if ref.get('evaluable') else []
            scores[field] = {'total': len(anchors), 'baseline_hits': sum(anchor in normalize_anchor(previous.text) for anchor in anchors), 'v2_hits': sum(anchor in normalize_anchor(result.text) for anchor in anchors)}
        rows.append({'snapshot_id': identity, 'hostname': entry['hostname'], 'evaluable': ref.get('evaluable', False),
                     'anchors': scores, 'text_changed': previous.text != result.text, 'markdown_changed': previous.markdown != result.markdown,
                     'baseline_blocks': len(previous.blocks), 'v2_blocks': len(result.blocks),
                     'inline_types': dict(Counter(node['type'] for node in annotations(result.blocks))),
                     'source_locations': location_diagnostics(result.blocks, payload)})
        print(f"Diagnosed {len(rows)} held-out HTML snapshots", flush=True)
    totals = {field: {key: sum(row['anchors'][field][key] for row in rows) for key in ['total', 'baseline_hits', 'v2_hits']} for field in ['required', 'unwanted']}
    return {'scope': 'Separate held-out HTML diagnostics after development implementation; no markdownify comparison, serializer selection or tuning on these snapshots.',
            'limitations': 'AI-assisted sparse selected anchors, not human gold, structural precision/recall or causal citation uplift. Native held-out inputs are excluded.',
            'manifest_hash': claimed, 'snapshots': len(rows), 'evaluable_snapshots': sum(row['evaluable'] for row in rows),
            'anchors': totals, 'source_locations': dict(sum((Counter(row['source_locations']) for row in rows), Counter())), 'results': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh output directory; existing directories rejected')
    parser.add_argument('--heldout-cache', type=Path, help='Read-only snapshot cache; switches to held-out diagnostics')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a fresh output directory; existing reports are never overwritten')
    old = old_extractor()
    frozen = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / 'evaluation/extraction').glob('*.json')}
    with network_disabled():
        result = heldout(old, args.heldout_cache) if args.heldout_cache else development(old)
    assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest for path, digest in frozen.items())
    result.update(baseline_revision=BASELINE, block_schema_version=BLOCK_SCHEMA_VERSION,
                  dependencies={name: version(name) for name in ['markdownify', 'beautifulsoup4', 'markdown-it-py']},
                  source_fingerprints=fingerprints(), frozen_evaluation_hashes=frozen)
    args.output.mkdir(parents=True)
    (args.output / 'results.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    page = '<!doctype html><meta charset="utf-8"><title>Issue 10 inline fidelity</title><style>body{font:16px system-ui;max-width:1200px;margin:32px auto}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:10px;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    page += '<h1>Inline fidelity: ' + ('held-out diagnostics' if args.heldout_cache else 'development comparison') + '</h1><p>' + escape(result['scope']) + '</p>'
    if args.heldout_cache:
        page += '<p>' + escape(result['limitations']) + '</p><pre>' + escape(json.dumps({key: result[key] for key in ['snapshots', 'evaluable_snapshots', 'anchors', 'source_locations']}, indent=2)) + '</pre>'
    else:
        page += '<table><tr><th>Fixture / HTML</th><th>Baseline</th><th>Structured v2</th><th>Markdownify 1.2.3</th></tr>'
        for row in result['results']:
            page += '<tr><td>' + escape(row['id']) + '<pre>' + escape(row['html']) + '</pre></td>' + ''.join('<td><pre>' + escape(row[key]) + '</pre></td>' for key in ['baseline_markdown', 'structured_v2_markdown', 'markdownify_markdown']) + '</tr>'
        page += '</table>'
    (args.output / 'report.html').write_text(page + '<p>Full structured evidence: results.json</p>')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
