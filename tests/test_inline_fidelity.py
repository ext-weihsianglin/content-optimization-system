"""Development regressions for issue #10; no network or frozen artifact writes."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
import pytest

from preprocessing.adapters.local import extract_conservative, extract_markdown_text
from preprocessing.blocks import PRESERVE_WHITESPACE_TAGS, blocks_to_markdown, dom_path, html_to_blocks
from preprocessing.downstream import structure_chunks
from preprocessing.schema import Snapshot

FIXTURES = json.loads(Path('evaluation/inline-fidelity/development.json').read_text())


def snapshot(html, format='html'):
    return Snapshot('snapshot', 'hash', FIXTURES['href'], 'example.test', html, format)


def inline_nodes(blocks):
    def descendants(nodes):
        for node in nodes:
            yield node
            yield from descendants(node.get('children', []))
    for block in blocks:
        yield from descendants(block.get('inline_nodes', []))
        for cell in (block.get('table') or {}).get('cells', []):
            yield from descendants(cell.get('inline_nodes', []))


def assert_original_locations(blocks, html):
    soup = BeautifulSoup(html, 'html.parser', preserve_whitespace_tags=PRESERVE_WHITESPACE_TAGS)
    paths = {dom_path(tag): tag for tag in [soup, *soup.find_all(True)]}
    for item in [*blocks, *inline_nodes(blocks)]:
        locator = item.get('source_locator')
        if locator is None:
            assert item['mapping_status'] in {'ambiguous', 'unavailable'}
            continue
        original = paths[locator['dom_path']]
        if 'child_index' in locator:
            assert str(original.contents[locator['child_index']]) == item['text']
        elif 'tag' in item:
            assert original.name == item['tag']
            assert dict(original.attrs) == item['attributes']


@pytest.mark.parametrize('case', FIXTURES['cases'], ids=lambda case: case['id'])
def test_issue_examples_and_edge_cases(case):
    result = extract_conservative(snapshot(case['html']))
    assert result.markdown == case['expected_markdown']
    assert_original_locations(result.blocks, case['html'])
    assert result.diagnostics['block_schema_version'] == 'dom-blocks-v2'
    assert blocks_to_markdown(json.loads(json.dumps(result.blocks))) == result.markdown
    # Structured inline nodes, rather than a cached Markdown string, drive rendering.
    for block in result.blocks:
        block.pop('inline_markdown', None)
    assert blocks_to_markdown(result.blocks) == result.markdown


@pytest.mark.parametrize('value', ['a`b', '`x`', '``x``', ' x ', 'a  b', '*x*', 'a\\b'])
def test_code_roundtrip_inside_emphasis(value):
    html = f'<p><em><code>{value}</code></em></p>'
    result = extract_conservative(snapshot(html))
    rendered = MarkdownIt('commonmark').render(result.markdown)
    parsed = BeautifulSoup(rendered, 'html.parser', preserve_whitespace_tags=PRESERVE_WHITESPACE_TAGS)
    assert parsed.em.code.get_text() == value


def test_inline_image_stays_in_paragraph_and_link_with_neighbors():
    html = '<p>Look <a href="/details"><img src="/diagram.png" alt="Diagram"></a> here.</p>'
    result = extract_conservative(snapshot(html))
    assert len(result.blocks) == 1
    paragraph = result.blocks[0]
    assert paragraph['type'] == 'paragraph'
    assert paragraph['text'] == 'Look Diagram here.'
    assert paragraph['inline_nodes'][1]['type'] == 'link'
    assert paragraph['inline_nodes'][1]['children'][0]['type'] == 'inline_image'
    assert result.markdown == 'Look [![Diagram](<https://example.test/diagram.png>)](<https://example.test/details>) here.'
    assert_original_locations(result.blocks, html)


def test_definition_relationships_and_chunks_stay_atomic():
    html = '<dl><dt>A</dt><dt>B</dt><dd>Shared</dd><dd><p>More</p><ul><li>Detail</li></ul></dd><dt>C</dt><dd>Last</dd></dl><hr>'
    blocks = html_to_blocks(html, '')
    root = blocks[0]
    terms = [block for block in blocks if block['type'].startswith('definition_') and block is not root]
    assert [block['type'] for block in terms] == ['definition_term', 'definition_term', 'definition_description', 'definition_description', 'definition_term', 'definition_description']
    assert all(block['parent_id'] == root['block_id'] for block in terms)
    assert blocks[-1]['type'] == 'thematic_break'
    _, chunks = structure_chunks('s', 'conservative_dom', blocks, target_characters=10)
    assert chunks[0]['block_ids'] == [block['block_id'] for block in blocks[:-1]]
    assert chunks[0]['oversized']
    assert_original_locations(blocks, html)


def test_repeated_inline_tags_located_by_unique_enclosing_source():
    source = '<nav>Menu</nav><p>First <code>x</code></p><p>Second <code>x</code></p>'
    result = extract_conservative(snapshot(source))
    code = [node for node in inline_nodes(result.blocks) if node['type'] == 'inline_code']
    assert [node['source_locator']['dom_path'] for node in code] == ['/p[1]/code[1]', '/p[2]/code[1]']
    assert_original_locations(result.blocks, source)


def test_transformed_semantics_never_mapped_by_flattened_text():
    blocks = html_to_blocks('<p>Price <del>$100</del></p>', '', '<main><p>Price $100</p></main>')
    assert blocks[0]['mapping_status'] == 'normalized_match'
    deletion = next(node for node in inline_nodes(blocks) if node['type'] == 'deletion')
    assert deletion['source_locator'] is None
    assert deletion['mapping_status'] == 'unavailable'
    ambiguous = html_to_blocks('<p><code>x</code></p>', '', '<p><code>x</code></p><p><code>x</code></p>')
    assert all(node['source_locator'] is None for node in inline_nodes(ambiguous))


def test_break_only_and_nested_empty_alt_media_are_not_dropped():
    result = extract_conservative(snapshot('<p><br></p><p><span><img src="/a.png" alt=""></span></p>'))
    assert len(result.blocks) == 2
    assert result.markdown == '\\\n\n\n![](<https://example.test/a.png>)'
    assert_original_locations(result.blocks, '<p><br></p><p><span><img src="/a.png" alt=""></span></p>')


def test_native_inline_nodes_do_not_claim_generated_html_source_paths():
    result = extract_markdown_text(snapshot('*Use `x`*\n\n|A|\n|--|\n|B|', format='markdown'))
    assert list(inline_nodes(result.blocks))
    assert all(node['source_locator'] is None and node['mapping_status'] == 'unavailable' for node in inline_nodes(result.blocks))


def test_inline_semantics_and_locations_inside_authoritative_table():
    html = '<table><tr><td colspan="2"><em><code>a`b</code></em><br><del>Old</del><img src="/x.png" alt=""></td></tr></table>'
    result = extract_conservative(snapshot(html))
    assert result.blocks[0]['table']['cells'][0]['colspan'] == 2
    assert {'inline_code', 'emphasis', 'hard_break', 'deletion', 'inline_image'} <= {node['type'] for node in inline_nodes(result.blocks)}
    assert result.markdown == result.blocks[0]['table']['html']
    assert_original_locations(result.blocks, html)


def test_schema_version_prevents_chunk_identity_collision_with_legacy():
    blocks = html_to_blocks('<p>Run <code>x</code></p>', '')
    _, current = structure_chunks('s', 'conservative_dom', blocks)
    legacy = json.loads(json.dumps(blocks))
    for block in legacy:
        block.pop('schema_version')
    _, previous = structure_chunks('s', 'conservative_dom', legacy)
    assert current[0]['chunk_id'] != previous[0]['chunk_id']
    assert current[0]['block_schema_versions'] == ['dom-blocks-v2']
