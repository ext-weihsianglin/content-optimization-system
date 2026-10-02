"""Preselection raw-input robustness comparison for every controlled v6 finalist."""
import argparse
import gzip
import json
from pathlib import Path
from urllib.parse import quote,urlsplit,urlunsplit
import duckdb
import joblib
import numpy as np
from bs4 import BeautifulSoup
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.robust_features import robust_features
from trad_ml_scorer.evidence_features import evidence_features
from trad_ml_scorer.control_features import control_features
from trad_ml_scorer.finalize_frontier import sha


def all_features(prompt,doc):
    base={**robust_features(prompt,doc),**evidence_features(prompt,doc)}
    return {**base,**control_features(prompt,doc,base)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=Path('data/raw'))
    args=parser.parse_args()
    root=Path('trad_ml_scorer/v6');cache=Path('data/trad_ml_scorer/v6')
    if (root/'raw_stress.json').exists():raise FileExistsError('Raw audit frozen')
    manifest=json.loads((cache/'manifest.json').read_text())
    assert all(sha(p)==h for p,h in manifest['code_hashes'].items())
    search=json.loads((root/'search.json').read_text())
    bundles={r['variant']:joblib.load(cache/(r['variant']+'.joblib')) for r in search['finalists']}
    data=dict(np.load(cache/'features.npz'))
    with open('data/trad_ml_scorer/v2/records.jsonl') as stream:
        records={r['record_id']:r for r in map(json.loads,stream)}
    indices=sorted(np.flatnonzero(data['splits']=='validation'),key=lambda i:str(data['ids'][i]))
    attacks=('raw_query_headings','raw_query_evidence','title_query','url_query')
    changes={v:{a:[] for a in attacks} for v in bundles};examples=[];con=duckdb.connect()
    predict=lambda values,b:float(b['pipeline'].predict_proba([[values[n] for n in b['feature_names']]])[0,1])
    for i in indices:
        record=records[str(data['ids'][i])]
        with gzip.open(f'data/trad_ml_scorer/v2/documents/{record["snapshot_id"]}.json.gz','rt') as stream:archived=json.load(stream)
        if archived['source']['format']!='html':continue
        prompt,payload,href=con.execute('SELECT prompt,html_content,href FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(args.input_dir/record['source_file']),record['source_row']]).fetchone()
        fresh=parse_snapshot(payload,href)
        assert fresh['snapshot_id']==record['snapshot_id']
        values=all_features(prompt,fresh)
        np.testing.assert_allclose([values[n] for n in manifest['feature_names']],data['X'][i],equal_nan=True)
        before={v:predict(values,b) for v,b in bundles.items()}
        for attack in attacks:
            soup=BeautifulSoup(payload,'html.parser');new_url=href
            if attack=='url_query':
                parts=urlsplit(href);new_url=urlunsplit((parts.scheme,parts.netloc,'/'+quote('-'.join(prompt.split())),parts.query,parts.fragment))
            elif attack=='title_query':
                if soup.title:soup.title.string=prompt
                else:
                    tag=soup.new_tag('title');tag.string=prompt;(soup.head or soup).insert(0,tag)
            else:
                for _ in range(20 if attack=='raw_query_headings' else 1):
                    tag=soup.new_tag('h2' if attack=='raw_query_headings' else 'p')
                    tag.string=prompt if attack=='raw_query_headings' else f'{prompt}. The value is 100 kg and 50 percent because this is an example.'
                    (soup.body or soup).append(tag)
            values=all_features(prompt,parse_snapshot(payload if attack=='url_query' else str(soup),new_url))
            for v,b in bundles.items():changes[v][attack].append(predict(values,b)-before[v])
        examples.append({'record_id':record['record_id'],'snapshot_id':record['snapshot_id'],'split':'validation'})
        if len(examples)==20:break
    prior=json.loads(Path('trad_ml_scorer/v5/raw_stress.json').read_text())
    assert examples==prior['examples']
    result={'rows':len(examples),'examples':examples,'selection':'Same 20 hash-selected validation HTML snapshots as v5',
            'scope':'Preselection relative non-regression gate; small reused development sample, not general adversarial certification.',
            'variants':{v:{a:{'mean_delta':float(np.mean(d)),'p95_increase':float(np.quantile(d,.95)),'max_increase':float(np.max(d)),'deltas':d} for a,d in edits.items()} for v,edits in changes.items()}}
    (root/'raw_stress.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({v:{a:{k:r[k] for k in ('mean_delta','p95_increase')} for a,r in edits.items()} for v,edits in result['variants'].items()},indent=2))

if __name__=='__main__':main()
