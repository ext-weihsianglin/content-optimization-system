import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from preprocessing.evaluate import METHODS, _aggregate, _score, evaluate
from preprocessing.reader_report import evaluate_reader, main, render_reader_report
from preprocessing.schema import stable_hash


def fixture():
    snapshots = [{"snapshot_id": identity, "split": split, "format": source_format,
                  "stratum": "article", "hostname": identity + ".test", "href": "https://example.test",
                  "payload_hash": identity, "source_file": "source.parquet", "source_row": 0}
                 for identity, split, source_format in (("dev", "dev", "html"), ("held", "heldout", "html"),
                                                         ("native", "heldout", "markdown"))]
    manifest = {"version": "test", "snapshots": snapshots}
    annotations = {"annotation_type": "ai_source_only", "documents": [
        {"snapshot_id": row["snapshot_id"], "evaluable": True,
         "required": [{"text": "ＣＡＦÉ — 12", "kind": "fact", "reason": "source"}],
         "unwanted": [{"text": "cookie", "reason": "boilerplate"}], "notes": "AI", "reviewer_type": "ai"}
        for row in snapshots]}
    original_results = [{"snapshot_id": row["snapshot_id"], "method": method, "status": "ok",
                         "text": "café - 12", "runtime_ms": 1} for row in snapshots for method in METHODS]
    original = evaluate(manifest, annotations, original_results)
    results = [{"snapshot_id": row["snapshot_id"], "method": "reader_lm",
                "status": "ok" if row["format"] == "html" else "unsupported_format",
                "text": "café - 12 cookie", "runtime_ms": 15,
                "diagnostics": {"input_tokens": 20, "input_truncated": False, "output_capped": True}}
               for row in snapshots]
    return manifest, annotations, results, original, {"endpoint": "http://127.0.0.1:8080/v1", "max_tokens": 100}


class ReaderReportTests(unittest.TestCase):
    def test_frozen_scores_and_aggregation_identical(self):
        manifest, annotations, results, original, run = fixture()
        before = copy.deepcopy(original)
        metrics = evaluate_reader(manifest, annotations, results, original, run)
        source = manifest["snapshots"][0]
        score = _score(source, annotations["documents"][0], results[0], "reader_lm")
        self.assertEqual(metrics["per_document"][0], score)
        group = next(row for row in metrics["groups"] if row["split"] == "dev" and row["subset"] == "html" and row["stratum"] is None)
        baselines = {row["snapshot_id"]: row for row in original["per_document"] if row["method"] == "baseline"}
        self.assertEqual({key: value for key, value in group.items() if key not in {"split", "subset", "stratum", "method"}},
                         _aggregate([score], baselines))
        self.assertEqual(metrics["original_groups"], original["groups"])
        self.assertEqual(original, before)
        self.assertTrue(metrics["complete"])
        self.assertEqual(metrics["coverage"]["recorded"], 3)

    def test_partial_requires_flag_and_missing_html_scores_zero(self):
        manifest, annotations, results, original, run = fixture()
        results = [results[0]]
        with self.assertRaisesRegex(ValueError, "allow-partial"):
            evaluate_reader(manifest, annotations, results, original, run)
        metrics = evaluate_reader(manifest, annotations, results, original, run, True)
        self.assertFalse(metrics["complete"])
        self.assertEqual(metrics["coverage"]["missing"], ["held", "native"])
        held = next(row for row in metrics["per_document"] if row["snapshot_id"] == "held")
        self.assertEqual(held["retention"], 0)
        self.assertTrue(held["output_failure"])
        page = render_reader_report(metrics, manifest, annotations, results)
        self.assertIn("PARTIAL RUN", page)
        self.assertIn("not an explicit runner outcome", page)

    def test_supported_error_and_native_coverage(self):
        manifest, annotations, results, original, run = fixture()
        results[1]["status"] = "error"
        metrics = evaluate_reader(manifest, annotations, results, original, run)
        indexed = {row["snapshot_id"]: row for row in metrics["per_document"]}
        self.assertEqual(indexed["held"]["retention"], 0)
        self.assertFalse(indexed["native"]["supported"])
        self.assertIsNone(indexed["native"]["retention"])
        self.assertEqual(metrics["resources"]["input_tokens"]["total"], 40)
        self.assertEqual(metrics["resources"]["output_capped"]["true"], 2)

    def test_resource_unknowns_are_not_false_or_zero(self):
        manifest, annotations, results, original, run = fixture()
        results[0]["diagnostics"] = {}
        results[1]["diagnostics"]["input_tokens"] = float("nan")
        results[1]["diagnostics"]["usage"] = {"completion_tokens": 42}
        results[1]["diagnostics"]["source_tokens"] = 100
        results[1]["diagnostics"]["finish_reason"] = "length"
        metrics = evaluate_reader(manifest, annotations, results, original, run)
        self.assertEqual(metrics["resources"]["input_truncated"]["unknown"], 1)
        self.assertEqual(metrics["resources"]["input_tokens"]["unknown"], 2)
        self.assertIsNone(metrics["resources"]["input_tokens"]["total"])
        self.assertEqual(metrics["resources"]["output_tokens"]["total"], 42)
        self.assertEqual(metrics["resources"]["source_tokens"]["total"], 100)
        self.assertEqual(metrics["resources"]["finish_reason_counts"], {"unknown": 1, "length": 1})

    def test_invalid_results_rejected(self):
        for change in ("duplicate", "unknown", "method", "status", "native"):
            manifest, annotations, results, original, run = fixture()
            if change == "duplicate":
                results.append(results[0])
            elif change == "unknown":
                results[0]["snapshot_id"] = "unknown"
            elif change == "method":
                results[0]["method"] = "baseline"
            elif change == "status":
                results[0]["status"] = "missing"
            else:
                results[2]["status"] = "ok"
            with self.subTest(change=change), self.assertRaises(ValueError):
                evaluate_reader(manifest, annotations, results, original, run)

    def test_nonlocal_endpoint_rejected_without_fetching(self):
        for endpoint in ("https://example.com/v1", "http://localhost.evil/v1", "file:///tmp/model", "http://user@localhost"):
            manifest, annotations, results, original, run = fixture()
            run["endpoint"] = endpoint
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                evaluate_reader(manifest, annotations, results, original, run)
        for endpoint in ("http://localhost:8080", "http://[::1]:8080"):
            manifest, annotations, results, original, run = fixture()
            run["endpoint"] = endpoint
            self.assertTrue(evaluate_reader(manifest, annotations, results, original, run)["complete"])

    def test_original_population_and_denominators_checked(self):
        for field, value in (("split", "heldout"), ("required_count", 99), ("result_present", False)):
            manifest, annotations, results, original, run = fixture()
            original["per_document"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate_reader(manifest, annotations, results, original, run)

    def test_report_escaped_bounded_and_honest(self):
        manifest, annotations, results, original, run = fixture()
        results[0]["text"] = '<script>alert(1)</script><img src="https://evil.test">' * 10000
        metrics = evaluate_reader(manifest, annotations, results, original, run)
        page = render_reader_report(metrics, manifest, annotations, results)
        self.assertNotIn('<script>', page)
        self.assertNotIn('<img', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('TRUNCATED PREVIEW', page)
        self.assertIn('AFTER the original heldout results were known', page)
        self.assertIn('NOT human gold', page)
        self.assertIn("script-src 'none'", page)
        self.assertIn('source.parquet', page)
        self.assertLess(len(page.encode()), 250000)

    def test_cli_unicode_jsonl_provenance_partial_guard_and_separate_artifacts(self):
        manifest, annotations, results, original, run = fixture()
        manifest["manifest_hash"] = stable_hash(manifest)
        annotations["manifest_hash"] = manifest["manifest_hash"]
        annotations["reference_hash"] = stable_hash(annotations)
        evaluation_hash = hashlib.sha256(Path("preprocessing/evaluate.py").read_bytes()).hexdigest()
        freeze = {"manifest_hash": manifest["manifest_hash"], "reference_hash": annotations["reference_hash"],
                  "evaluation_sha256": evaluation_hash}
        original["provenance"] = {"manifest_hash": manifest["manifest_hash"], "reference_hash": annotations["reference_hash"],
                                  "evaluation_source_sha256": evaluation_hash}
        run["input_manifest_hash"] = manifest["manifest_hash"]
        run["reference_hash"] = annotations["reference_hash"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("sources", manifest), ("annotations", annotations), ("original", original),
                                ("manifest", run), ("freeze", freeze)):
                (root / f"{name}.json").write_text(json.dumps(value))
            result_path = root / "results.jsonl"
            results[0]["text"] += '\u2028line separator\u2029paragraph separator\u0085next line'
            result_path.write_text(json.dumps(results[0], ensure_ascii=False) + '\n\n', encoding="utf-8")
            self.assertIn('\u2028', result_path.read_text(encoding="utf-8"))
            args = ["--results", str(result_path), "--manifest", str(root / "sources.json"),
                    "--annotations", str(root / "annotations.json"), "--original-metrics", str(root / "original.json"),
                    "--freeze", str(root / "freeze.json"), "--output", str(root / "supplement")]
            with self.assertRaisesRegex(ValueError, "allow-partial"):
                main(args)
            self.assertFalse((root / "supplement.html").exists())
            before = (root / "original.json").read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                main([*args, "--allow-partial"])
            self.assertFalse(json.loads((root / "supplement.json").read_text())["complete"])
            self.assertIn("PARTIAL RUN", (root / "supplement.html").read_text())
            self.assertIn(results[0]["text"], (root / "supplement.html").read_text())
            self.assertEqual(json.loads((root / "supplement.json").read_text())["coverage"]["recorded"], 1)
            self.assertEqual(before, (root / "original.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "overwrite"):
                main([*args, "--allow-partial", "--output", str(root / "original")])
            annotations["documents"][0]["required"][0]["text"] = "changed"
            (root / "annotations.json").write_text(json.dumps(annotations))
            with self.assertRaisesRegex(ValueError, "reference_hash"):
                main([*args, "--allow-partial"])


if __name__ == "__main__":
    unittest.main()
