"""The default pipeline actually invokes markdownify while keeping source truth."""
import duckdb
from markdown_it import MarkdownIt
import pytest

from preprocessing.adapters.local import extract_conservative
from preprocessing.blocks import html_to_blocks, blocks_to_markdown
from preprocessing.corpus import parse_one, read_document, run, validate_document
from preprocessing.quality import classify_payload
from preprocessing.schema import Snapshot, snapshot_identity


def test_default_extraction_calls_markdownify_library(monkeypatch):
    from markdownify import MarkdownConverter
    original = MarkdownConverter.process_tag
    called = []
    def spy(self, node, parent_tags=None):
        called.append(node.name)
        return original(self, node, parent_tags)
    monkeypatch.setattr(MarkdownConverter, 'process_tag', spy)
    html = '<p>Use <em><code>a`b</code></em><br><del>old</del><img src="/a.png" alt=""></p>'
    result = extract_conservative(Snapshot('s', 'p', 'https://example.test/', 'example.test', html, 'html'))
    assert 'p' in called and 'em' in called and 'del' in called
    assert result.diagnostics['serializer'] == 'markdownify-structured-v1'
    assert result.diagnostics['markdownify_version'] == '1.2.3'
    assert '~~old~~' in result.markdown
    assert result.blocks[0]['inline_nodes'][1]['children'][0]['type'] == 'inline_code'


@pytest.mark.parametrize('html', ['<dl><dt>API</dt><dd>Definition</dd></dl>', '<del>Old</del>', '<kbd>Ctrl</kbd>'])
def test_semantic_html_is_routed_to_html_parser(html):
    assert classify_payload(html) == 'html'


def test_terminal_break_and_literal_markdown_are_preserved():
    blocks = html_to_blocks('<p>Literal `x` *stars* [link] \\</p><p>End<br></p>', '')
    rendered = MarkdownIt('commonmark').render(blocks_to_markdown(blocks))
    assert 'Literal `x` *stars* [link] \\' in rendered
    assert 'End<br' in rendered


def test_converter_keeps_pre_backticks_whitespace_and_missing_media_target():
    html = '<pre>  x\n```\n</pre><p><img alt="Only description" data-src="/lazy.png"></p>'
    markdown = blocks_to_markdown(html_to_blocks(html, 'https://example.test/'))
    assert '````\n  x\n```\n````' in markdown
    assert 'data-src="/lazy.png"' in markdown
    assert 'https://example.test/' not in markdown


def source_parquet(path, rows):
    connection = duckdb.connect()
    connection.execute('CREATE TABLE input(prompt VARCHAR,citation_category VARCHAR,href VARCHAR,hostname VARCHAR,html_content VARCHAR)')
    connection.executemany('INSERT INTO input VALUES (?,?,?,?,?)', rows)
    connection.execute('COPY input TO ? (FORMAT PARQUET)', [str(path)])
    connection.close()


def test_full_export_preserves_duplicate_row_references_metadata_and_chunks(tmp_path):
    source = tmp_path / 'input'; source.mkdir()
    html = '<html><head><title>T</title><script type="application/ld+json">{"@type":"Article"}</script></head><body><p>Price <del>$100</del> $80.</p></body></html>'
    rows = [('Q', 'top', 'https://example.test/a', 'example.test', html),
            ('Q2', 'bottom', 'https://example.test/a', 'example.test', html),
            ('Q', 'top', 'https://example.test/b', 'example.test', '# Native\n\nBody')]
    source_parquet(source / 'fixtures.parquet', rows)
    output = tmp_path / 'export'
    manifest = run(source, output, workers=1)
    assert manifest['raw_rows'] == 3 and manifest['unique_snapshots'] == 2
    assert manifest['shared_snapshot_references'] == 1
    assert manifest['source_location_validation'].get('invalid_locators', 0) == 0
    _, identity = snapshot_identity(html, 'https://example.test/a')
    doc = read_document(output / 'documents' / f'{identity}.json.gz')
    assert doc['source_metadata']['jsonld'][0]['raw'] == '{"@type":"Article"}'
    assert doc['markdown'] == 'Price ~~$100~~ $80.'
    assert [key for chunk in doc['chunks'] for key in chunk['block_ids']] == [block['block_id'] for block in doc['blocks']]
    doc['markdown'] += 'invented'
    with pytest.raises(ValueError, match='checksum'):
        validate_document(doc, identity, snapshot_identity(html, 'https://example.test/a')[0], manifest['run_identity'])
    with pytest.raises(FileExistsError, match='Completed'):
        run(source, output, workers=1, resume=True)


def test_empty_source_export_has_explicit_outcome_and_empty_chunk_parquet(tmp_path):
    source = tmp_path / 'input'; source.mkdir()
    source_parquet(source / 'fixtures.parquet', [('Q', 'top', 'https://example.test/', 'example.test', '')])
    manifest = run(source, tmp_path / 'export', workers=1)
    assert manifest['snapshot_statuses'] == {'unsupported_format': 1}
    assert manifest['chunks'] == 0
    connection = duckdb.connect()
    assert connection.execute('SELECT COUNT(*) FROM read_parquet(?)', [str(tmp_path / 'export/chunks.parquet')]).fetchone()[0] == 0


def test_worker_failure_keeps_raw_source_and_resumes_without_replacing(tmp_path, monkeypatch):
    from trad_ml_scorer import retention_features
    def fail(*args, **kwargs):
        raise RuntimeError('Deliberate test failure')
    monkeypatch.setattr(retention_features, 'parse_snapshot', fail)
    payload = '<p>Original source</p>'
    payload_hash, identity = snapshot_identity(payload, 'https://example.test/')
    source = {'source_file': 'fixtures.parquet', 'source_file_hash': 'sourcehash', 'source_row': 0}
    item = (identity, payload_hash, payload, 'https://example.test/', 'example.test', source, str(tmp_path), 'run', 5)
    assert parse_one(item)[1:] == ('parse_error', False)
    path = tmp_path / f'{identity}.json.gz'
    saved = path.read_bytes()
    doc = read_document(path)
    assert doc['raw_payload_reference']['payload_hash'] == payload_hash
    assert 'Deliberate test failure' in doc['error']
    assert parse_one(item)[1:] == ('parse_error', True)
    assert path.read_bytes() == saved
    with pytest.raises(ValueError, match='version mismatch'):
        parse_one((*item[:7], 'different-run', 5))


def test_multifile_export_and_interrupted_finalization_resume_are_lossless(tmp_path):
    source = tmp_path / 'input'; source.mkdir()
    shared = ('Q', 'top', 'https://example.test/a', 'example.test', '<p>Shared <code>x</code></p>')
    source_parquet(source / 'one.parquet', [shared])
    source_parquet(source / 'two.parquet', [shared, ('Q2', 'bottom', 'https://example.test/b', 'example.test', '<p>Other</p>')])
    output = tmp_path / 'export'
    manifest = run(source, output, workers=1)
    assert (manifest['raw_rows'], manifest['unique_snapshots']) == (3, 2)
    cached = {path.name: path.read_bytes() for path in (output / 'documents').glob('*.gz')}
    # Simulate interruption after publishing indexes but before completion marker.
    (output / 'manifest.json').unlink()
    resumed = run(source, output, workers=1, resume=True)
    assert resumed['resumed_snapshots'] == 2
    assert cached == {path.name: path.read_bytes() for path in (output / 'documents').glob('*.gz')}
    from preprocessing.markdownify_report import corpus_report
    evidence = corpus_report(output)
    assert evidence['verification']['raw_rows_payload_url_and_metadata_verified'] == 3
    assert not evidence['errors']


def test_ordered_starts_outside_commonmark_range_use_html_without_renumbering():
    blocks = html_to_blocks('<ol start="-2"><li>First</li><li>Second</li></ol>', '')
    assert '<ol start="-2">' in blocks_to_markdown(blocks)
    assert '1. First' not in blocks_to_markdown(blocks)


def test_indexed_locations_match_independent_paths_in_wide_mixed_dom():
    from bs4 import BeautifulSoup
    from preprocessing.blocks import _dom_index, dom_path
    html = '<main>' + ''.join(f'<p>Text<!-- comment --><span>{i}</span><br><span>Tail</span></p>' for i in range(150)) + '</main>'
    soup = BeautifulSoup(html, 'html.parser')
    paths, positions = _dom_index(soup)
    for tag in [soup, *soup.find_all(True)]:
        assert paths[id(tag)] == dom_path(tag)
        for index, child in enumerate(tag.contents):
            assert positions[id(child)] == index


def test_native_plain_text_chunks_are_versioned_for_the_new_serializer():
    from preprocessing.adapters.local import extract_markdown_text
    from preprocessing.downstream import structure_chunks
    result = extract_markdown_text(Snapshot('s', 'p', 'https://example.test/', 'example.test', '  Original spaces', 'text'))
    _, chunks = structure_chunks('s', 'markdown_text', result.blocks)
    assert result.text == '  Original spaces'
    assert chunks[0]['block_schema_versions'] == ['dom-blocks-v3']
    assert result.diagnostics['serializer'] == 'markdownify-structured-v1'
