import numpy as np
import pytest
from trad_ml_scorer.semantic_features import original_cosines, section_summary, validate_join


def test_cosine_uses_common_space_and_is_scale_invariant():
    q = np.array([1., 0., 0.])
    docs = np.array([[1.,0.,0.], [0.,1.,0.], [-1.,0.,0.]])
    np.testing.assert_allclose(original_cosines(q,docs),[1,0,-1])
    np.testing.assert_allclose(original_cosines(5*q,3*docs),[1,0,-1])
    with pytest.raises(ValueError):original_cosines(q,np.ones((2,2)))
    with pytest.raises(ValueError):original_cosines(np.zeros(3),docs)
    with pytest.raises(ValueError):original_cosines(q,np.array([[np.nan,0,1]]))


def test_sections_handle_missing_and_fewer_than_three():
    assert all(np.isnan(v) for v in section_summary([]).values())
    result = section_summary([.2,.8])
    assert result['section_max'] == .8
    assert result['section_top3_mean'] == .5
    assert result['section_median'] == .5
    assert section_summary([.2,.8,.4,.6]) == section_summary([.6,.2,.4,.8])
    with pytest.raises(ValueError):section_summary([np.nan])


def test_same_url_is_not_sufficient_for_join():
    record = {'source_file_hash':'file','source_row':7,'snapshot_id':'snapshot','prompt':'question',
              'href':'https://example.com','hostname':'example.com','split':'train','html_sha256':'payload','is_cited_high':1}
    association = {**record,'payload_hash':'payload','citation_category':'top'}
    validate_join(record,association)
    for field,replacement in [('source_row',8),('source_file_hash','other'),('snapshot_id','other'),('prompt','other'),
                              ('split','test'),('hostname','other'),('payload_hash','other'),('citation_category','bottom')]:
        with pytest.raises(ValueError):validate_join(record,{**association,field:replacement})
