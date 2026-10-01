"""Behavior checks for inference consistency, split leakage, and train-only preprocessing."""

from pathlib import Path
import tempfile
import unittest


import joblib
import numpy as np

from trad_ml_scorer.lr_features import FEATURE_NAMES, FEATURE_VERSION, extract_features, predict
from trad_ml_scorer.prepare_lr_data import assign_hosts, extract_record, leakage_audit, prepare
from trad_ml_scorer.train_lr import pipeline, response_grid

HTML = '<html><head><title>Running shoes</title></head><body><main><h1>Running shoes</h1><p>Comfortable running shoes for daily training.</p></main></body></html>'


class FeatureTests(unittest.TestCase):
    def test_prompt_alignment_is_row_specific(self):
        aligned = extract_features("running shoes", HTML, "https://a.test/shoes")
        unrelated = extract_features("database replication", HTML, "https://a.test/shoes")
        self.assertEqual(aligned["coverage_title"], 1)
        self.assertEqual(unrelated["coverage_title"], 0)
        self.assertEqual(aligned["log_word_count"], unrelated["log_word_count"])
        self.assertEqual(list(aligned), FEATURE_NAMES)

    def test_training_inference_feature_parity(self):
        row = extract_record(("running shoes", "top", "https://a.test/shoes", "a.test", HTML, "fixture.parquet", 0))
        actual = extract_features("running shoes", HTML, "https://a.test/shoes")
        np.testing.assert_allclose(list(row["features"].values()), list(actual.values()), equal_nan=True)

    def test_empty_content_and_missing_query_are_defined(self):
        row = extract_features("", "", "")
        self.assertTrue(np.isnan(row["coverage_title"]))
        self.assertEqual(row["failure_page"], 1)
        self.assertTrue(all(np.isfinite(v) or np.isnan(v) for v in row.values()))

    def test_rare_binary_sensitivity_uses_both_states(self):
        np.testing.assert_array_equal(response_grid(np.array([0.] * 99 + [1.])), [0., 1.])

    def test_save_load_prediction(self):
        rows = [extract_features(prompt, HTML) for prompt in ["running shoes", "database", "shoes", "sql"]]
        x = np.array([[r[f] for f in FEATURE_NAMES] for r in rows])
        fitted = pipeline(1).fit(x, [1, 0, 1, 0])
        bundle = {"pipeline": fitted, "feature_names": FEATURE_NAMES, "feature_version": FEATURE_VERSION}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            joblib.dump(bundle, path)
            score = predict(joblib.load(path), "running shoes", HTML)
        self.assertAlmostEqual(score, fitted.predict_proba(x[:1])[0, 1])


class SplitTests(unittest.TestCase):
    def test_host_assignment_order_independent(self):
        hosts = [f"host{i}.test" for i in range(970)]
        assignment = assign_hosts(hosts)
        self.assertEqual(assignment, assign_hosts(reversed(hosts)))
        self.assertEqual([sum(v == split for v in assignment.values()) for split in ("train", "validation", "test")], [776, 97, 97])

    def test_shared_snapshots_and_conflicting_urls_excluded(self):
        a = extract_record(("shoes", "top", "https://a.test/", "a.test", HTML, "fixture", 0))
        b = extract_record(("shoes", "bottom", "https://b.test/", "b.test", HTML, "fixture", 1))
        c = extract_record(("shoes", "bottom", "https://a.test/", "a.test", HTML + ' ', "fixture", 2))
        rows = prepare([a, b, c], {"a.test": "train", "b.test": "test"})
        self.assertIn("html_shared_across_hosts", rows[0]["exclusions"])
        self.assertIn("conflicting_url_labels", rows[0]["exclusions"])
        self.assertTrue(all(r["exclusions"] for r in rows))
        leakage_audit(rows)

    def test_audit_rejects_leaked_host(self):
        row = extract_record(("shoes", "top", "https://a.test/", "a.test", HTML, "fixture", 0))
        with self.assertRaises(AssertionError):
            leakage_audit([{**row, "split": "train", "exclusions": []}, {**row, "split": "test", "exclusions": []}])

    def test_preprocessing_does_not_refit_on_prediction(self):
        model = pipeline(1).fit(np.array([[1., 0.], [3., 1.], [np.nan, 0.], [5., 1.]]), [0, 1, 0, 1])
        self.assertEqual(model[0].statistics_[0], 3.)
        before = model[1].mean_.copy()
        model.predict_proba([[999999., 1.]])
        np.testing.assert_array_equal(before, model[1].mean_)


if __name__ == "__main__":
    unittest.main()
