import joblib
import numpy as np
import pytest
from scipy.special import expit
from sklearn.metrics import log_loss
from trad_ml_scorer.platt_calibration import VERSION, calibrate, fit_platt, reliability, assign_oof_scores
from trad_ml_scorer.predict_platt import load_calibrated_model, scores_from_logit
from trad_ml_scorer.markdownify_context import FEATURE_ORDER


def test_fit_recovers_orientation_and_improves_miscalibrated_example():
    rng=np.random.default_rng(32)
    scores=np.linspace(-1,1,2000)
    labels=rng.binomial(1,expit(2*scores-.3))
    result=fit_platt(scores,labels)
    assert 1.5<result['slope']<2.5
    assert -.5<result['intercept']<-.1
    prediction=calibrate(scores,result['slope'],result['intercept'])
    assert log_loss(labels,prediction)<log_loss(labels,expit(scores))
    assert np.all(np.diff(prediction)>0)


def test_extreme_logits_are_stable_and_invalid_parameters_fail():
    p=calibrate([-1e308,-1000.,0.,1000.,1e308],2.,0.)
    assert np.isfinite(p).all()
    np.testing.assert_array_equal(p,[0.,0.,.5,1.,1.])
    for slope in (0.,-1.,np.nan):
        with pytest.raises(ValueError):calibrate([0.],slope,0.)
    with pytest.raises(ValueError):calibrate([np.nan],1.,0.)
    with pytest.raises(ValueError):fit_platt([0.,0.],[0,1])
    with pytest.raises(ValueError):fit_platt([-1.,1.],[0,0])
    with pytest.raises(ValueError,match='reverse ranking'):fit_platt([-2.,-1.,1.,2.],[1,1,0,0])


def test_oof_guards_host_isolation_and_one_score_per_row():
    hosts=np.array(['a','a','b','b'])
    scores=np.full(4,np.nan);assigned=np.zeros(4,dtype=bool)
    with pytest.raises(ValueError,match='Host leakage'):
        assign_oof_scores(scores,assigned,[0],[1],hosts,[.1])
    assign_oof_scores(scores,assigned,[0,1],[2,3],hosts,[.2,.3])
    with pytest.raises(ValueError,match='more than once'):
        assign_oof_scores(scores,assigned,[0,1],[2,3],hosts,[.2,.3])
    assign_oof_scores(scores,assigned,[2,3],[0,1],hosts,[.4,.5])
    assert assigned.all() and np.isfinite(scores).all()


def test_reliability_includes_endpoints_and_empty_bins():
    result=reliability([0,1],[0.,1.])
    assert result['ece']==0
    assert result['bins'][0]['count']==1 and result['bins'][-1]['count']==1
    assert sum(r['count'] for r in result['bins'])==2
    assert result['bins'][5]['observed_positive_fraction'] is None


def test_model_checksum_prevents_wrong_base(tmp_path):
    base=tmp_path/'base.joblib';base.write_bytes(b'wrong model')
    path=tmp_path/'calibration.joblib'
    joblib.dump({'version':VERSION,'feature_names':FEATURE_ORDER,'base_model_path':str(base),
                 'base_model_sha256':'incorrect'},path)
    with pytest.raises(ValueError,match='checksum mismatch'):load_calibrated_model(path)


def test_api_exposes_raw_and_calibrated_values_separately():
    artifact={'version':VERSION,'parameters':{'slope':2.,'intercept':-.1}}
    result=scores_from_logit(artifact,.5)
    assert result['raw_logit']==.5
    assert result['uncalibrated_high_class_probability']==pytest.approx(expit(.5))
    assert result['calibrated_high_class_probability']==pytest.approx(expit(.9))
    with pytest.raises(ValueError):scores_from_logit({'version':'v7.1'},.5)
