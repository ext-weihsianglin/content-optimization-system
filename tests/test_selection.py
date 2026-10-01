"""Diagnostic selection is independent of downstream citation measurements."""

from preprocessing.schema import Snapshot
from preprocessing.select import select_candidate, select_precision_candidate


def test_selection_needs_independent_agreement():
    source = Snapshot("id", "hash", "https://example.com", "example.com", "<p>useful content</p>", "html")
    candidates = [{"method": "trafilatura", "status": "ok", "text": "one two three"}, {"method": "readability", "status": "ok", "text": "four five six"}]
    assert select_precision_candidate(source, candidates, {"body_text": "useful content"})["status"] == "needs_review"


def test_unimplemented_is_source_insufficient():
    source = Snapshot("id", "hash", "https://example.com", "example.com", "not-implemented", "text")
    assert select_candidate(source, [], {"body_text": "not-implemented"})["status"] == "source_insufficient"


def test_native_format_does_not_depend_on_query_or_label():
    source = Snapshot("id", "hash", "https://example.com", "example.com", "Useful details", "text")
    candidate = {"method": "markdown_text", "status": "ok", "text": "Useful details"}
    inventory = {"body_text": "Useful details"}
    expected = select_candidate(source, [candidate], inventory)
    assert expected == select_candidate(source, [{**candidate, "citation_category": "top", "prompt": "misleading prompt"}], inventory)


def test_successful_diagnostic_proposal_is_not_human_certification():
    source = Snapshot("id", "hash", "https://example.com", "example.com", "<p>useful content</p>", "html")
    candidates = [{"method": method, "status": "ok", "text": "useful content"} for method in ["readability", "trafilatura"]]
    result = select_precision_candidate(source, candidates, {"body_text": "useful content"})
    assert result["method"] == "trafilatura"
    assert result["human_validated"] is False
