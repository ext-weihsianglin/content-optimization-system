"""Check the audited inventory against extractor outputs and prompt invariance."""
import json
from pathlib import Path
import numpy as np
import pytest
from trad_ml_scorer.feature_dependencies import REGISTRY, feature_group, fixed_for_html_edit
from trad_ml_scorer.retention_features import parse_snapshot
from trad_ml_scorer.robust_features import robust_features
from trad_ml_scorer.evidence_features import evidence_features
from trad_ml_scorer.control_features import control_features


def extract(prompt, doc):
    base = {**robust_features(prompt, doc), **evidence_features(prompt, doc)}
    return {**base, **control_features(prompt, doc, base)}


def test_registry_exhaustive_and_document_features_ignore_prompt():
    doc = parse_snapshot('<title>Running shoes</title><h1>Which running shoes?</h1><p>Running shoes cost 50 dollars because they support comfortable running.</p><h2>Care</h2><p>Clean shoes carefully after each run with water.</p>', 'https://example.com/running-shoes')
    first = extract('What running shoes cost 50 dollars?', doc)
    second = extract('How to clean shoes with water?', doc)
    assert set(first) == set(REGISTRY) == set(second)
    for name in first:
        if feature_group(name) == 'doc':
            np.testing.assert_equal(first[name], second[name], err_msg=name)
    other_doc = parse_snapshot('<h1>Database systems</h1><p>Manage data safely.</p>', 'https://other.example/')
    third = extract('What running shoes cost 50 dollars?', other_doc)
    for name in first:
        if feature_group(name) == 'prompt':
            np.testing.assert_equal(first[name], third[name], err_msg=name)


def test_dependency_and_editability_are_distinct():
    for name in ('path_homepage', 'question_heading_fraction', 'needs_review', 'format_html'):
        assert feature_group(name) == 'doc'
    for name in ('path_query_precision', 'normalized_path_gain', 'best_section_log_words', 'evidence_number_fraction', 'table_numeric_row_coverage', 'supported_path_query_precision'):
        assert feature_group(name) == 'promptXdoc'
    assert fixed_for_html_edit('path_homepage')
    assert fixed_for_html_edit('path_query_precision')
    assert fixed_for_html_edit('normalized_path_gain')
    assert not fixed_for_html_edit('supported_path_query_precision')
    assert not fixed_for_html_edit('supported_normalized_path_gain')
    for name in REGISTRY:
        assert feature_group('missingindicator_' + name) == feature_group(name)
    with pytest.raises(KeyError):
        feature_group('new_unreviewed_feature')


def test_selected_and_transformed_model_inventory_is_covered():
    source = Path('trad_ml_scorer/interpretation/fixed_prompt/analysis.json')
    selected = json.loads(source.read_text())['feature_groups']
    assert {g: sum(feature_group(n) == g for n in selected) for g in ('prompt', 'doc', 'promptXdoc')} == {'prompt': 4, 'doc': 41, 'promptXdoc': 51}
    coefficients = json.loads(Path('trad_ml_scorer/v5/coefficients.json').read_text())
    assert all(feature_group(r['feature']) in ('prompt', 'doc', 'promptXdoc') for r in coefficients)
