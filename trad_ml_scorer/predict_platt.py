"""Explicit v8 inference exposing both uncalibrated and calibrated class scores."""
from pathlib import Path
import joblib
from trad_ml_scorer.markdownify_context import FEATURE_ORDER, feature_row
from trad_ml_scorer.predict_markdownify import load_model
from trad_ml_scorer.platt_calibration import VERSION, calibrate
from trad_ml_scorer.prepare_semantic import digest


def load_calibrated_model(calibration_path, base_model_path=None):
    """Only load trusted local joblib files. Bind calibration to the exact base."""
    calibration=joblib.load(calibration_path)
    if calibration.get('version')!=VERSION or calibration.get('feature_names')!=FEATURE_ORDER:
        raise ValueError('Wrong v8 calibration version or feature contract')
    path=Path(base_model_path or calibration['base_model_path'])
    if digest(path)!=calibration['base_model_sha256']:
        raise ValueError('Base-model checksum mismatch; calibration belongs to another model')
    root=Path(__file__).resolve().parents[1]
    for name,sha in calibration['inference_code_hashes'].items():
        if digest(root/name)!=sha:raise ValueError('Calibration implementation drift: '+name)
    calibrate([0.],calibration['parameters']['slope'],calibration['parameters']['intercept'])
    return {'calibration':calibration,'base':load_model(path)}


def predict_calibrated_document(loaded, prompt, document, semantic_scores):
    """Caller must rebuild derived fields/embeddings for the current revision."""
    features=feature_row(prompt,document,semantic_scores)
    raw=float(loaded['base']['pipeline'].decision_function(features[None,:])[0])
    return scores_from_logit(loaded['calibration'],raw)


def scores_from_logit(calibration, raw):
    if calibration.get('version')!=VERSION:
        raise ValueError('Wrong calibration contract')
    p=calibration['parameters']
    return {'model_version':'v8','base_model_version':'v7.1','raw_logit':float(raw),
            'uncalibrated_high_class_probability':float(calibrate(raw,1.,0.)),
            'calibrated_high_class_probability':float(calibrate(raw,p['slope'],p['intercept']))}
