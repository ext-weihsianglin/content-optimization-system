"""Feature provenance and matching behavior independent of fitted outcomes."""
import copy
import numpy as np
from trad_ml_scorer.frontier_features import richer_features
from trad_ml_scorer.retention_features import parse_snapshot


def test_provenance_and_host_identity_do_not_affect_features():
    doc = parse_snapshot('# Running shoes\n\nRunning shoes fit well.\n', 'https://one.example/shoes')
    changed = copy.deepcopy(doc)
    changed['source'].update(hostname='other.example', href='https://other.example/shoes', source_row=999, source_file='labels.parquet')
    changed['is_cited_high'] = 1
    changed['split'] = 'test'
    assert richer_features('running shoes', doc) == richer_features('running shoes', changed)


def test_adjacent_query_words_and_saturated_repetition():
    doc = parse_snapshot('# Running shoes\n\nRunning shoes fit well.\n', 'https://example.com/shoes')
    good = richer_features('running shoes', doc)
    unrelated = richer_features('database replication', doc)
    assert good['body_query_bigram'] == 1
    assert unrelated['body_query_bigram'] == 0
    assert 0 < good['body_query_saturated_tf'] < 1
    assert good['top_three_section_coverage'] > unrelated['top_three_section_coverage']


def test_empty_query_and_missing_metadata_are_finite():
    doc = parse_snapshot('Simple plain text content.', 'https://example.com/')
    assert all(np.isfinite(v) for v in richer_features('', doc).values())


def test_robust_scoring_ignores_repeated_unsupported_headings_without_mutating_source():
    from trad_ml_scorer.robust_features import scoring_view, robust_features
    from trad_ml_scorer.stress_frontier import altered
    doc = parse_snapshot('# Shoes\n\nRunning shoes should fit comfortably for daily training.\n', 'https://example.com/shoes')
    original = copy.deepcopy(doc)
    attack = altered(doc, 'running shoes', 'query_headings')
    a, b = robust_features('running shoes', doc), robust_features('running shoes', attack)
    # Source-retention fraction legitimately changes with appended discarded content.
    for key in a:
        if key != 'retained_text_fraction':
            np.testing.assert_allclose(a[key],b[key],equal_nan=True)
    assert doc == original
    assert len(scoring_view(attack)['blocks']) == len(scoring_view(doc)['blocks'])
