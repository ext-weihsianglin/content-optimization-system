"""Canonical v7 feature assembly from a Markdownify document and semantic scores.

Callers must recompute the semantic scores for the same prompt/current document.
This adapter does not fetch embeddings, repair stale edited documents or infer
whether a supplied score came from a different document revision.
"""
import numpy as np
from trad_ml_scorer.feature_dependencies import REGISTRY
from trad_ml_scorer.retention_features import FEATURE_NAMES
from trad_ml_scorer.robust_features import robust_features
from trad_ml_scorer.semantic_features import NAMES

VERSION = 'lr-semantic-v7.1'
# Preserve v7 order: retention names, then v3 composition names in registry order.
CONTEXT_NAMES = [n for n in FEATURE_NAMES if REGISTRY[n]['dependency'] in ('prompt', 'doc')]
CONTEXT_NAMES += [n for n, meta in REGISTRY.items() if meta['source']=='frontier_features.py' and meta['dependency']=='doc']
FEATURE_ORDER = NAMES + CONTEXT_NAMES


def context_features(prompt, document):
    if document.get('representation', {}).get('serializer') != 'markdownify-structured-v1':
        raise ValueError('Expected Markdownify document; legacy parser inputs are unsupported')
    if 'scorer_source_word_count' not in document:
        raise ValueError('Preserve the source inventory word count; do not substitute retained text length')
    values = robust_features(prompt, document)
    return {name: np.nan if values[name] is None else float(values[name]) for name in CONTEXT_NAMES}


def feature_row(prompt, document, semantic_scores):
    """55 ordered inputs for training and request-level scoring; missing = NaN."""
    if not set(NAMES) <= set(semantic_scores):
        raise ValueError('All ten semantic fields must be explicit, including missing fields')
    semantic = [np.nan if semantic_scores[n] is None else float(semantic_scores[n]) for n in NAMES]
    if any(np.isinf(v) or (np.isfinite(v) and abs(v)>1.00001) for v in semantic):
        raise ValueError('Expected finite cosine similarities in [-1,1] or explicit missing values')
    context = context_features(prompt, document)
    result = np.asarray(semantic + [context[n] for n in CONTEXT_NAMES], dtype=float)
    if np.isinf(result).any():
        raise ValueError('Infinite context value')
    return result
