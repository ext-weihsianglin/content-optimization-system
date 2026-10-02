import copy
import numpy as np
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.control_features import control_features, normalized_tokens, window_coverage, METADATA_MATCHES


def test_conservative_normalization_and_numeric_formats():
    assert normalized_tokens('Shoes policies boxes 1,000.00 kilograms 10% e-mail')==['shoe','policy','box','1000','kg','10','percent','email']
    assert normalized_tokens('news analysis status species')==['news','analysis','status','species']
    assert normalized_tokens('centimetres hours dollars')==['cm','h','usd']
    assert normalized_tokens('10.50')==['10.5']
    assert normalized_tokens('1,000,000')==['1000000']


def test_sliding_window_boundaries_and_duplicates():
    assert window_coverage({'red','shoe'},['red','x','shoe'],2)==.5
    assert window_coverage({'red','shoe'},['red','x','shoe'],3)==1
    assert window_coverage({'red','shoe'},['red','red','shoe'],2)==1
    assert window_coverage(set(),['x'],10)==0


def test_long_prose_recovery_is_separate_from_normalization():
    text='running shoes '+' '.join(['unrelated']*90)
    doc=parse_snapshot('<p>'+text+'</p>','https://example.com/')
    row=control_features('running shoes',doc)
    assert row['long_window_10_best']==1
    assert row['normalized_prose_window_10']==0
    repeated=copy.deepcopy(doc); repeated['blocks']*=2
    assert control_features('running shoes',repeated)['long_window_10_mean']==row['long_window_10_mean']


def test_metadata_requires_lexical_body_support():
    doc=parse_snapshot('<title>running shoes</title><p>Database replication uses multiple nodes to store information safely.</p>','https://example.com/running-shoes')
    row=control_features('running shoes',doc)
    assert all(row['supported_'+n]==0 for n in METADATA_MATCHES)
    assert row['supported_normalized_title_coverage']==0
    assert row['normalized_title_coverage']==1
    assert all(np.isfinite(v) or np.isnan(v) for v in row.values())
