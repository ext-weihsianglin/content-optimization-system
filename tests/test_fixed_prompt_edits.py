import numpy as np
import pytest
from trad_ml_scorer.fixed_prompt_edits import make_edit,feature_group,contrast
from trad_ml_scorer.train_lr import pipeline


def test_dependencies_keep_interactions_and_fixed_url_separate():
    assert feature_group('prompt_question')=='Fixed prompt'
    assert feature_group('path_query_precision')=='Fixed URL'
    assert feature_group('how_to_x_ordered_steps')=='Prompt × HTML'
    assert feature_group('answer_best_sentence_coverage')=='Prompt × HTML'
    assert feature_group('missingindicator_coverage_body')=='Prompt × HTML'
    assert feature_group('log_heading_count')=='HTML document'


def test_existing_title_content_and_paragraph_edits():
    p='<html><head><title>Generic</title></head><body><h1>Running shoe fit</h1><main><p>'+('Unrelated database information. '*8)+'</p><p>'+('Running shoes fit your feet comfortably. '*8)+'</p></main></body></html>'
    title,_=make_edit(p,'running shoes','title_from_existing_h1')
    assert '<title>Running shoe fit</title>' in title
    moved,_=make_edit(p,'running shoes','relevant_paragraph_first')
    assert moved.index('Running shoes fit')<moved.index('Unrelated database')
    split,_=make_edit('<p id="one">'+('A sentence with enough words for this paragraph. '*20)+'</p>','query','split_long_paragraph')
    assert split.count('<p')==2 and split.count('id="one"')==1


def test_non_applicability_is_explicit():
    assert make_edit('<p>Short.</p>','query','split_long_paragraph')[0] is None
    with pytest.raises(ValueError):make_edit('<p>x</p>','q','unknown')


def test_exact_delta_cancels_fixed_context_including_missing_indicators():
    names=['prompt_question','path_homepage','coverage_body','log_heading_count']
    x=np.array([[0,0,.1,1],[1,0,.5,2],[0,1,np.nan,1],[1,1,.9,4],[0,0,.6,3],[1,1,.2,2]])
    model=pipeline(.1).fit(x,[0,1,0,1,1,0])
    result=contrast(model,names,[1,0,np.nan,2],[1,0,.9,3])
    assert abs(sum(r['delta_log_odds'] for r in result['contributions'])-result['delta_log_odds'])<1e-10
    assert all(r['delta_log_odds']==0 for r in result['contributions'] if r['group'].startswith('Fixed'))
