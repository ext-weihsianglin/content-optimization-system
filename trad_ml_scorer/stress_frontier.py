"""Validation document-level stress tests; edits simulate post-parser content additions."""
import copy
import gzip
import json
import argparse
from pathlib import Path
import joblib
import numpy as np
from trad_ml_scorer.frontier_features import richer_features
from trad_ml_scorer.retention_features import features_from_document


def vector(prompt, doc, names, version="v3"):
    if version == "v4":
        from trad_ml_scorer.robust_features import robust_features
        values = robust_features(prompt, doc)
        return [values[n] for n in names]
    values = {**features_from_document(prompt,doc), **richer_features(prompt,doc)}
    return [values[n] for n in names]


def altered(doc, prompt, attack):
    result = copy.deepcopy(doc)
    if attack == 'query_repetition':
        texts, kind = [' '.join([prompt]*30)], 'paragraph'
    elif attack == 'query_headings':
        texts, kind = [prompt]*20, 'heading'
    else:
        texts, kind = [' '.join(['Generic unrelated introductory information.']*200)], 'paragraph'
    for i,text in enumerate(texts):
        result['blocks'].append({'block_id':f'stress-{i}', 'type':kind, 'text':text, 'heading_level':2 if kind=='heading' else None, 'links':[], 'parent_id':None})
    extra = '\n'.join(texts)
    result['text'] += '\n' + extra
    from scripts.analyze_content import words
    result['scorer_source_word_count'] += len(words(extra))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v3", "v4"), default="v3")
    version = parser.parse_args().version
    root = Path('trad_ml_scorer') / version
    if (root/'stress.json').exists():
        raise FileExistsError('Stress results already frozen')
    audit = json.loads((root/'audit.json').read_text())
    data = dict(np.load(f'data/trad_ml_scorer/{version}/features.npz'))
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:
        records = {r['record_id']:r for r in map(json.loads,stream)}
    # Deterministic hash ordering, no selection by label, probability or success.
    indices = sorted(np.flatnonzero(data['splits']=='validation'), key=lambda i:str(data['ids'][i]))[:120]
    bundles = {v:joblib.load(f'data/trad_ml_scorer/{version}/{v}.joblib') for v in [r['variant'] for r in audit['audits']]}
    changes = {v:{a:[] for a in ('query_repetition','query_headings','irrelevant_padding')} for v in bundles}
    names = json.loads(Path(f'data/trad_ml_scorer/{version}/manifest.json').read_text())['feature_names']
    for i in indices:
        row = records[str(data['ids'][i])]
        with gzip.open(f'data/trad_ml_scorer/v2/documents/{row["snapshot_id"]}.json.gz','rt') as stream:
            doc = json.load(stream)
        original = vector(row['prompt'],doc,names,version)
        np.testing.assert_allclose(original,data['X'][i],equal_nan=True)
        edits = {a:vector(row['prompt'],altered(doc,row['prompt'],a),names,version) for a in changes[next(iter(bundles))]}
        for variant,bundle in bundles.items():
            cols = [names.index(n) for n in bundle['feature_names']]
            predict = lambda values: float(bundle['pipeline'].predict_proba(np.asarray(values)[cols].reshape(1,-1))[0,1])
            before = predict(original)
            for attack,values in edits.items():
                changes[variant][attack].append(predict(values)-before)
    result = {'rows':len(indices),'split':'validation','selection':'first 120 record hashes in ascending order',
              'scope':'Post-parser document edits, not end-to-end raw HTML robustness; cached feature parity checked on all sampled rows',
              'variants':{v:{a:{'mean_delta':float(np.mean(d)), 'median_delta':float(np.median(d)), 'p95_increase':float(np.quantile(d,.95)), 'max_increase':float(np.max(d)), 'fraction_increase_above_0_10':float(np.mean(np.asarray(d)>.1))} for a,d in attacks.items()} for v,attacks in changes.items()}}
    (root/'stress.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
