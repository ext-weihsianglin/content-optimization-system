import copy
import numpy as np
import pytest
from trad_ml_scorer.markdownify_context import FEATURE_ORDER, CONTEXT_NAMES, context_features, feature_row
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.semantic_features import NAMES


def document():
    return parse_snapshot('<html><head><title>Running shoe care</title></head><body><h1>Running shoes</h1><p>Clean your running shoes with a soft brush and water.</p></body></html>','https://example.com/care')


def test_canonical_assembly_preserves_semantics_and_document():
    doc=document();before=copy.deepcopy(doc)
    scores=dict(zip(NAMES,np.linspace(.1,.9,10)))
    vector=feature_row('How to clean running shoes?',doc,scores)
    assert len(FEATURE_ORDER)==55 and len(CONTEXT_NAMES)==45
    np.testing.assert_array_equal(vector[:10],list(scores.values()))
    assert vector[FEATURE_ORDER.index('prompt_how_to')]==1
    assert vector[FEATURE_ORDER.index('path_homepage')]==0
    assert doc==before


def test_reject_legacy_documents_and_missing_inventory():
    doc=document();doc['representation']['serializer']='legacy'
    with pytest.raises(ValueError,match='Markdownify'):context_features('shoes',doc)
    doc=document();del doc['scorer_source_word_count']
    with pytest.raises(ValueError,match='source inventory'):context_features('shoes',doc)


def test_missing_cosines_are_explicit_not_zero():
    doc=document();scores=dict.fromkeys(NAMES,None)
    assert np.isnan(feature_row('shoes',doc,scores)[:10]).all()
    del scores[NAMES[0]]
    with pytest.raises(ValueError,match='explicit'):feature_row('shoes',doc,scores)
    scores=dict.fromkeys(NAMES,.5);scores[NAMES[0]]=2
    with pytest.raises(ValueError,match='cosine'):feature_row('shoes',doc,scores)


def test_context_changes_when_page_structure_changes():
    doc=document();before=context_features('shoes',doc)
    changed=copy.deepcopy(doc)
    changed['blocks']=[b for b in changed['blocks'] if b['type']!='heading']
    changed['text']='\n'.join(b.get('text','') for b in changed['blocks'])
    after=context_features('shoes',changed)
    assert after['log_heading_count']<before['log_heading_count']


def test_predictor_rejects_mixed_parser_model():
    from trad_ml_scorer.predict_markdownify import predict_document
    with pytest.raises(ValueError,match='Wrong model contract'):
        predict_document({'version':'lr-semantic-v7','feature_names':FEATURE_ORDER},'shoes',document(),dict.fromkeys(NAMES,.5))


def test_loader_rejects_feature_code_drift(tmp_path):
    import joblib
    from trad_ml_scorer.markdownify_context import VERSION
    from trad_ml_scorer.predict_markdownify import load_model
    path=tmp_path/'model.joblib'
    joblib.dump({'version':VERSION,'feature_names':FEATURE_ORDER,
                 'code_hashes':{'trad_ml_scorer/markdownify_context.py':'wrong-hash'}},path)
    with pytest.raises(ValueError,match='Feature implementation drift'):
        load_model(path)
