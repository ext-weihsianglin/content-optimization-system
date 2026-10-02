import copy
import numpy as np
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.evidence_features import evidence_features


def test_repeated_prose_does_not_multiply_sentence_features():
    doc=parse_snapshot('<p>Running shoes cost 50 dollars and weigh 300 grams.</p>','https://example.com/shoes')
    repeated=copy.deepcopy(doc)
    repeated['blocks']*=4
    a=evidence_features('running shoes cost',doc)
    b=evidence_features('running shoes cost',repeated)
    assert a==b
    assert a['evidence_number_coverage']>0
    assert a['answer_best_sentence_coverage']==1


def test_table_data_and_headers_are_separate():
    doc=parse_snapshot('<table><tr><th>Running shoes price</th></tr><tr><td>Unrelated equipment 100</td></tr></table>','https://example.com/')
    row=evidence_features('running shoes price',doc)
    assert row['table_header_best_coverage']==1
    assert row['table_best_value_row_coverage']==0
    assert row['table_numeric_row_coverage']==0


def test_provenance_and_empty_query():
    doc=parse_snapshot('<p>Running shoes have cushioned soles for everyday walking.</p>','https://example.com/a')
    changed=copy.deepcopy(doc)
    changed['source'].update(hostname='different.example',source_row=999)
    changed['is_cited_high']=1
    assert evidence_features('running shoes',doc)==evidence_features('running shoes',changed)
    values=evidence_features('the and',doc)
    assert all(np.isfinite(v) for v in values.values())
    assert values['answer_best_sentence_coverage']==0


def test_distinct_table_rows_and_ordered_steps():
    doc=parse_snapshot('<ol><li>Choose running shoes that fit your feet comfortably.</li><li>Try running shoes while wearing your usual socks.</li></ol>','https://example.com/')
    values=evidence_features('how to choose running shoes',doc)
    assert values['steps_best_coverage']==1
    assert values['steps_howto_alignment']==1


def test_v5_public_inference_and_code_fingerprint():
    import hashlib
    from pathlib import Path
    import pytest
    from trad_ml_scorer.predict_frontier import predict_frontier
    class RecordingModel:
        def predict_proba(self, matrix):
            np.testing.assert_allclose(matrix, [[1.]])
            return np.array([[.25,.75]])
    filename='trad_ml_scorer/evidence_features.py'
    bundle={'feature_version':'lr-evidence-v5', 'feature_names':['answer_best_sentence_coverage'],
            'pipeline':RecordingModel(), 'code_hashes':{filename:hashlib.sha256(Path(filename).read_bytes()).hexdigest()}}
    html='<p>Running shoes should fit comfortably for daily training.</p>'
    result=predict_frontier(bundle,'running shoes',html,'https://example.com/')
    assert result['p_is_cited_high']==.75
    assert result['feature_version']=='lr-evidence-v5'
    assert predict_frontier(bundle,'running shoes','','https://example.com/')['p_is_cited_high'] is None
    bundle['code_hashes'][filename]='incorrect'
    with pytest.raises(ValueError,match='code changed'):
        predict_frontier(bundle,'running shoes',html,'https://example.com/')
