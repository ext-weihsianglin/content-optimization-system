"""Load the corrected v7 bundle and score canonical documents with supplied cosines."""
import hashlib
from pathlib import Path
import joblib
from trad_ml_scorer.markdownify_context import VERSION, FEATURE_ORDER, feature_row


def load_model(path):
    """Load trusted local joblib artifacts only; reject mixed-parser v7 bundles."""
    bundle = joblib.load(path)
    if bundle.get('version') != VERSION or bundle.get('feature_names') != FEATURE_ORDER:
        raise ValueError('Expected the retrained Markdownify v7 model and exact feature order')
    root = Path(__file__).resolve().parents[1]
    for relative, expected in bundle['code_hashes'].items():
        with (root / relative).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError('Feature implementation drift: ' + relative)
    return bundle


def predict_document(bundle, prompt, document, semantic_scores):
    """The caller supplies scores regenerated for this prompt/document revision.

    Use load_model once at startup. Edited structured documents must have their
    derived text, outline, chunks and semantic vectors rebuilt by the caller.
    """
    if bundle.get('version') != VERSION or bundle.get('feature_names') != FEATURE_ORDER:
        raise ValueError('Wrong model contract; legacy v7 must not consume these inputs')
    vector = feature_row(prompt, document, semantic_scores)
    return float(bundle['pipeline'].predict_proba(vector.reshape(1, -1))[0, 1])
