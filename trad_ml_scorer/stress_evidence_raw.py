"""Diagnostic raw-HTML and metadata edits on development snapshots only."""
import argparse
import gzip
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote
import duckdb
import joblib
import numpy as np
from bs4 import BeautifulSoup
from trad_ml_scorer.evidence_features import evidence_features
from trad_ml_scorer.robust_features import robust_features
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.finalize_frontier import sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=Path('data/raw'))
    args=parser.parse_args()
    root=Path('trad_ml_scorer/v5'); cache=Path('data/trad_ml_scorer/v5')
    if (root/'raw_stress.json').exists():
        raise FileExistsError('Raw stress already frozen')
    selection=json.loads((root/'selection.json').read_text())
    assert sha(cache/'model.joblib')==selection['model_sha256']
    bundle=joblib.load(cache/'model.joblib')
    assert all(sha(p)==h for p,h in bundle['code_hashes'].items())
    baseline=joblib.load('data/trad_ml_scorer/v4/model.joblib')
    data=dict(np.load(cache/'features.npz'))
    manifest=json.loads((cache/'manifest.json').read_text())
    records={r['record_id']:r for r in map(json.loads,open('data/trad_ml_scorer/v2/records.jsonl'))}
    indices=sorted(np.flatnonzero(data['splits']=='validation'),key=lambda i:str(data['ids'][i]))
    changes={v:{a:[] for a in ('raw_query_headings','raw_query_evidence','title_query','url_query')} for v in ('selected','v4')}
    examples=[]; con=duckdb.connect()
    def score(doc,prompt,model):
        values={**robust_features(prompt,doc),**evidence_features(prompt,doc)}
        return float(model['pipeline'].predict_proba([[values[n] for n in model['feature_names']]])[0,1])
    for i in indices:
        record=records[str(data['ids'][i])]
        with gzip.open(f'data/trad_ml_scorer/v2/documents/{record["snapshot_id"]}.json.gz','rt') as stream:
            archived=json.load(stream)
        if archived['source']['format']!='html':
            continue
        prompt,payload,href=con.execute('SELECT prompt,html_content,href FROM read_parquet(?,file_row_number=true) WHERE file_row_number=?',[str(args.input_dir/record['source_file']),record['source_row']]).fetchone()
        fresh=parse_snapshot(payload,href)
        assert fresh['snapshot_id']==record['snapshot_id']
        values={**robust_features(prompt,fresh),**evidence_features(prompt,fresh)}
        np.testing.assert_allclose([values[n] for n in manifest['feature_names']],data['X'][i],equal_nan=True)
        before={v:score(fresh,prompt,m) for v,m in [('selected',bundle),('v4',baseline)]}
        from trad_ml_scorer.predict_frontier import predict_frontier
        actual=predict_frontier(bundle,prompt,payload,href)
        np.testing.assert_allclose(actual['p_is_cited_high'],before['selected'],atol=1e-12)
        for attack in changes['selected']:
            soup=BeautifulSoup(payload,'html.parser'); new_url=href
            if attack=='url_query':
                parts=urlsplit(href)
                new_url=urlunsplit((parts.scheme,parts.netloc,'/'+quote('-'.join(prompt.split())),parts.query,parts.fragment))
            elif attack=='title_query':
                if soup.title:
                    soup.title.string=prompt
                else:
                    title=soup.new_tag('title'); title.string=prompt
                    (soup.head or soup).insert(0,title)
            else:
                for _ in range(20 if attack=='raw_query_headings' else 1):
                    tag=soup.new_tag('h2' if attack=='raw_query_headings' else 'p')
                    tag.string=prompt if attack=='raw_query_headings' else f'{prompt}. The value is 100 kg and 50 percent because this is an example.'
                    (soup.body or soup).append(tag)
            # URL-only manipulation leaves HTML bytes untouched.
            changed=parse_snapshot(payload if attack=='url_query' else str(soup),new_url)
            for v,m in [('selected',bundle),('v4',baseline)]:
                changes[v][attack].append(score(changed,prompt,m)-before[v])
        examples.append({'record_id':record['record_id'],'snapshot_id':record['snapshot_id'],'split':'validation'})
        if len(examples)==20:
            break
    result={'rows':len(examples),'selection':'first 20 hash-sorted validation HTML snapshots','examples':examples,
            'scope':'Small diagnostic, not a selection gate or robustness certification; raw parsing/feature parity verified for every original sample.',
            'variants':{v:{a:{'mean_delta':float(np.mean(d)),'p95_increase':float(np.quantile(d,.95)),'max_increase':float(np.max(d))} for a,d in attacks.items()} for v,attacks in changes.items()}}
    (root/'raw_stress.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['variants'],indent=2))

if __name__=='__main__':
    main()
