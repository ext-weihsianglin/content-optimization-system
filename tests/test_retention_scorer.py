"""Retention source identity, structure, and scoring contract checks."""

import unittest

import numpy as np

from trad_ml_scorer.retention_features import FEATURE_NAMES, features_from_document, parse_snapshot, sections_from_blocks

HTML = '''<html lang="en"><head><title>Shoe comparison</title>
<script type="application/ld+json">{"@type":"Article"}</script></head><body>
<nav>Discard this navigation</nav><header>Brand introduction</header>
<main><h1>Running shoes</h1><p>Running shoes for training.</p>
<h2>Prices</h2><table><tr><th>Shoes</th><th>Price</th></tr><tr><td>A</td><td>$10</td></tr></table>
<h2>How to choose</h2><ol><li>Measure feet</li><li>Try shoes<ul><li>Check fit</li></ul></li></ol></main>
<aside><h2>Extra sizing advice</h2><p>Measure foot width.</p></aside></body></html>'''


class RetentionScorerTests(unittest.TestCase):
    def test_new_parser_is_authoritative_and_retains_structure(self):
        doc = parse_snapshot(HTML, "https://example.com/shoes")
        self.assertEqual(doc["selection"]["policy"], "retention-first-v1")
        self.assertEqual(doc["selection"]["method"], "conservative_dom")
        self.assertIn("Extra sizing advice", doc["text"])
        self.assertNotIn("Discard this navigation", doc["text"])
        self.assertEqual(doc["source_metadata"]["title"], "Shoe comparison")
        self.assertTrue(doc["source_metadata"]["jsonld"])
        self.assertEqual([b for c in doc["chunks"] for b in c["block_ids"]], [b["block_id"] for b in doc["blocks"]])

    def test_snapshot_identity_includes_payload_and_url(self):
        first = parse_snapshot(HTML, "https://example.com/a")
        changed = parse_snapshot(HTML + " ", "https://example.com/a")
        other_url = parse_snapshot(HTML, "https://example.com/b")
        self.assertEqual(len({first["snapshot_id"], changed["snapshot_id"], other_url["snapshot_id"]}), 3)

    def test_sections_and_ordered_steps_do_not_double_count(self):
        doc = parse_snapshot(HTML, "https://example.com/shoes")
        row = features_from_document("how to compare running shoes", doc)
        self.assertEqual(list(row), FEATURE_NAMES)
        self.assertAlmostEqual(row["log_ordered_steps"], np.log1p(2))
        self.assertAlmostEqual(row["log_list_items"], np.log1p(3))
        self.assertGreater(row["coverage_h1"], 0)
        self.assertGreater(row["coverage_table_headers"], 0)
        sections = sections_from_blocks(doc["blocks"])
        combined = " ".join(" ".join(s["texts"]) for s in sections)
        self.assertEqual(combined.count("Measure feet"), 1)

    def test_prompt_features_change_without_reparsing(self):
        doc = parse_snapshot(HTML, "https://example.com/shoes")
        good = features_from_document("running shoes", doc)
        bad = features_from_document("database replication", doc)
        self.assertGreater(good["best_section_coverage"], bad["best_section_coverage"])
        self.assertEqual(good["log_word_count"], bad["log_word_count"])

    def test_native_markdown_preserves_heading_and_list(self):
        doc = parse_snapshot("# Running shoes\n\n1. Measure feet\n2. Try shoes\n", "https://example.com/guide")
        self.assertEqual(doc["selection"]["method"], "markdown_text")
        features = features_from_document("running shoes", doc)
        self.assertEqual(features["coverage_h1"], 1)
        self.assertAlmostEqual(features["log_ordered_steps"], np.log1p(2))

    def test_insufficient_source_abstains_instead_of_old_parser_fallback(self):
        doc = parse_snapshot("", "https://example.com/")
        with self.assertRaises(ValueError):
            features_from_document("anything", doc)
        self.assertIsNone(doc["selection"]["method"])

    def test_question_and_label_do_not_enter_document(self):
        doc = parse_snapshot(HTML, "https://example.com/")
        self.assertNotIn("prompt", doc)
        self.assertNotIn("is_cited_high", doc)
        self.assertTrue(all(np.isfinite(v) or np.isnan(v) for v in features_from_document("", doc).values()))


if __name__ == "__main__":
    unittest.main()
