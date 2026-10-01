import pytest

from preprocessing.blocks import html_to_blocks
from preprocessing.downstream import structure_chunks
from preprocessing.schema import Snapshot
from preprocessing.select import select_candidate


def test_chunks_preserve_every_block_and_nested_lists():
    blocks = html_to_blocks('<h1>Title</h1><p>Introduction</p><ul><li>Parent<ul><li>Child</li></ul></li></ul><h2>Next</h2><pre>  code\n</pre>', 'https://example.com')
    outline, chunks = structure_chunks('snapshot', 'conservative_dom', blocks, 15)
    assert [identity for chunk in chunks for identity in chunk['block_ids']] == [block['block_id'] for block in blocks]
    owners = {identity: chunk['chunk_id'] for chunk in chunks for identity in chunk['block_ids']}
    for block in blocks:
        if block['parent_id']:
            assert owners[block['block_id']] == owners[block['parent_id']]
    assert outline[1]['parent_heading_id'] == outline[0]['block_id']
    assert structure_chunks('snapshot', 'conservative_dom', blocks, 15) == (outline, chunks)


def test_oversized_table_is_not_truncated():
    blocks = html_to_blocks('<table><tr><th colspan="2">Limits</th></tr><tr><td>10</td><td>20</td></tr></table>', 'https://example.com')
    _, chunks = structure_chunks('snapshot', 'conservative_dom', blocks, 5)
    assert len(chunks) == 1
    assert chunks[0]['oversized']
    assert 'colspan="2"' in chunks[0]['markdown']


def test_dangling_parents_rejected():
    with pytest.raises(ValueError):
        structure_chunks('snapshot', 'conservative_dom', [{'block_id': 'child', 'parent_id': 'missing'}])


def test_retention_selection_preserves_flagged_content_without_article_agreement():
    snapshot = Snapshot('id', 'hash', 'https://example.com', 'example.com', '<p>Useful</p>', 'html')
    candidate = {'method': 'conservative_dom', 'status': 'ok', 'text': 'Useful'}
    result = select_candidate(snapshot, [candidate], {'body_text': 'Useful', 'quality_flags': ['possible_error_response']})
    assert result['method'] == 'conservative_dom'
    assert result['status'] == 'needs_review'
    assert result['human_validated'] is False


def test_no_silent_fallback_to_cleaner_candidate():
    snapshot = Snapshot('id', 'hash', 'https://example.com', 'example.com', '<p>Useful</p>', 'html')
    result = select_candidate(snapshot, [{'method': 'readability', 'status': 'ok', 'text': 'Useful'}], {'body_text': 'Useful'})
    assert result['method'] is None
    assert result['status'] == 'needs_review'
