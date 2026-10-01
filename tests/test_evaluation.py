import json
import unittest

from preprocessing.evaluate import evaluate, normalize_anchor
from preprocessing.report import render_report


def snapshot(identity, source_format="html", split="heldout", **extra):
    return {"snapshot_id": identity, "format": source_format, "split": split,
            "stratum": "article", "hostname": identity + ".example", "href": "https://example.test/",
            "payload_hash": "hash-" + identity, "source_file": "source.parquet", "source_row": 0, **extra}


def annotation(identity, required=("fact",), unwanted=("cookie",), evaluable=True):
    return {"snapshot_id": identity, "evaluable": evaluable,
            "required": [{"text": text, "kind": "fact", "reason": "source"} for text in required],
            "unwanted": [{"text": text, "reason": "boilerplate"} for text in unwanted],
            "notes": "source only", "reviewer_type": "ai"}


def result(identity, method="baseline", status="ok", text="fact", runtime_ms=10):
    return {"snapshot_id": identity, "method": method, "status": status,
            "text": text, "runtime_ms": runtime_ms, "markdown": "", "html": "",
            "metadata": {}, "diagnostics": {}, "blocks": []}


def inputs(snapshots, documents):
    return {"version": "test", "sampling": {}, "snapshots": snapshots}, {
        "annotation_type": "ai_source_only", "documents": documents}


def group(metrics, method="baseline", subset="all", split="heldout", stratum=None):
    return next(row for row in metrics["groups"] if
                (row["method"], row["subset"], row["split"], row["stratum"]) == (method, subset, split, stratum))


class EvaluationTests(unittest.TestCase):
    def test_unsupported_excluded_error_and_missing_are_zero(self):
        manifest, annotations = inputs([snapshot(name) for name in ("good", "bad", "unsupported", "missing")],
                                       [annotation(name) for name in ("good", "bad", "unsupported", "missing")])
        metrics = evaluate(manifest, annotations, [result("good"), result("bad", status="error", text="fact cookie"),
                                                   result("unsupported", status="unsupported_format")])
        summary = group(metrics)
        self.assertEqual(summary["retention"]["denominator"], 3)
        self.assertEqual(summary["retention"]["micro"], 1 / 3)
        self.assertEqual(summary["retention"]["macro"], 1 / 3)
        self.assertEqual(summary["leakage"]["numerator"], 0)
        self.assertEqual(summary["output_failure_rate"], 2 / 3)
        self.assertEqual(summary["unsupported_documents"], 1)
        self.assertEqual(summary["missing_result_documents"], 1)
        self.assertEqual(summary["latency_ms"]["count"], 2)

    def test_unicode_typography_is_exact_not_fuzzy(self):
        self.assertEqual(normalize_anchor('ＣＡＦÉ\u00a0“Straße” — １２…'), 'café "strasse" - 12...')
        manifest, annotations = inputs([snapshot("unicode")], [annotation("unicode", required=(
            'CAFÉ “Straße” — １２…', "10 mg", "cafe", "ab"))])
        metrics = evaluate(manifest, annotations, [result("unicode", text='cafe\u0301 "STRASSE" - 12... 100 mg a-b')])
        self.assertEqual(group(metrics)["retention"]["numerator"], 1)
        self.assertEqual(group(metrics)["retention"]["denominator"], 4)

    def test_empty_references_missing_annotations_and_non_evaluable(self):
        manifest, annotations = inputs([snapshot(name) for name in ("empty", "missing", "shell")],
                                       [annotation("empty", (" \u00a0",), ()), annotation("shell", evaluable=False)])
        metrics = evaluate(manifest, annotations, [result(name, status="empty", text="") for name in ("empty", "missing", "shell")])
        summary = group(metrics)
        self.assertIsNone(summary["retention"]["micro"])
        self.assertIsNone(summary["leakage"]["macro"])
        self.assertIsNone(summary["paired_baseline_retention"]["micro_delta"])
        self.assertEqual(summary["retention"]["blank_anchors_excluded"], 1)
        self.assertEqual(summary["missing_annotation_documents"], 1)
        self.assertEqual(summary["source_non_evaluable_documents"], 1)
        self.assertEqual(summary["content_evaluable_documents"], 1)
        self.assertEqual(summary["output_failure_rate"], 1)

    def test_micro_macro_pairing_routing_and_latency(self):
        manifest, annotations = inputs([snapshot("short"), snapshot("long"), snapshot("native", "markdown")],
                                       [annotation("short", ("one",)), annotation("long", ("one", "two", "three")), annotation("native")])
        metrics = evaluate(manifest, annotations, [
            result("short", text="one", runtime_ms=10), result("long", text="absent", runtime_ms=30),
            result("native"), result("short", "trafilatura", text="absent"),
            result("long", "trafilatura", text="one two three"), result("native", "markdown_text")])
        baseline = group(metrics, subset="html")
        self.assertEqual(baseline["retention"]["micro"], .25)
        self.assertEqual(baseline["retention"]["macro"], .5)
        self.assertEqual(baseline["latency_ms"], {"count": 2, "median": 20, "p95": 29})
        paired = group(metrics, "trafilatura", "html")["paired_baseline_retention"]
        self.assertEqual(paired["micro_delta"], .5)
        self.assertEqual(paired["macro_delta"], 0)
        self.assertEqual(paired["documents"], 2)
        self.assertEqual(group(metrics, "trafilatura", "native_non_html")["supported_documents"], 0)
        self.assertEqual(group(metrics, "markdown_text", "native_non_html")["retention"]["micro"], 1)
        self.assertEqual(group(metrics, "markdown_text", "html")["supported_documents"], 0)

    def test_blank_ok_timeout_and_nonfinite_latency(self):
        manifest, annotations = inputs([snapshot("blank"), snapshot("timeout")], [annotation("blank"), annotation("timeout")])
        metrics = evaluate(manifest, annotations, [result("blank", text=" \n", runtime_ms=float("nan")),
                                                  result("timeout", status="timeout", text="fact", runtime_ms=-1)])
        self.assertEqual(group(metrics)["retention"]["micro"], 0)
        self.assertEqual(group(metrics)["output_failures"], 2)
        self.assertIsNone(group(metrics)["latency_ms"]["median"])
        json.dumps(metrics, allow_nan=False)

    def test_paired_denominator_requires_both_methods_and_text_only(self):
        manifest, annotations = inputs([snapshot("shared"), snapshot("excluded")],
                                       [annotation("shared"), annotation("excluded")])
        candidate = result("shared", "readability", text="unrelated")
        candidate.update(html="fact", markdown="fact", metadata={"title": "fact"}, blocks=[{"text": "fact"}])
        metrics = evaluate(manifest, annotations, [result("shared"), candidate,
                                                  result("excluded", status="unsupported_format"),
                                                  result("excluded", "readability")])
        summary = group(metrics, "readability")
        self.assertEqual(summary["retention"]["micro"], .5)
        paired = summary["paired_baseline_retention"]
        self.assertEqual(paired["documents"], 1)
        self.assertEqual(paired["anchor_denominator"], 1)
        self.assertEqual(paired["micro_delta"], -1)
        self.assertEqual(paired["macro_delta"], -1)

    def test_hostname_overlap_warns_without_hiding_actual_counts(self):
        manifest, annotations = inputs([
            snapshot("dev", split="dev", hostname="EXAMPLE.test."),
            snapshot("held", hostname="example.test"),
        ], [])
        metrics = evaluate(manifest, annotations, [])
        self.assertEqual(metrics["sample"]["unique_hostnames"], 1)
        self.assertTrue(any("Hostname leakage" in warning for warning in metrics["warnings"]))
        self.assertEqual(metrics["sample"]["split_counts"], {"dev": 1, "heldout": 1})

    def test_duplicate_unknown_records_fail_and_split_isolation(self):
        manifest, annotations = inputs([snapshot("dev", split="dev"), snapshot("held")], [annotation("dev"), annotation("held")])
        with self.assertRaises(ValueError):
            evaluate(manifest, annotations, [result("dev"), result("dev")])
        with self.assertRaises(ValueError):
            evaluate(manifest, annotations, [result("unknown")])
        metrics = evaluate(manifest, annotations, [result("dev"), result("held", text="absent")])
        self.assertEqual(group(metrics, split="dev")["retention"]["micro"], 1)
        self.assertEqual(group(metrics)["retention"]["micro"], 0)
        self.assertEqual(group(metrics, stratum="article")["retention"]["micro"], 0)

    def test_html_is_inert_and_report_has_traceability(self):
        attack = '</pre><script>alert("source")</script><img src="https://evil.test/x">'
        manifest, annotations = inputs([snapshot("sample", href="javascript:alert(1)", stratum=attack)], [annotation("sample", (attack,))])
        manifest["declared_date"] = "2026-09-30"
        output = result("sample", text=attack)
        output["html"] = attack
        metrics = evaluate(manifest, annotations, [output])
        report = render_report(metrics, manifest, annotations, [output])
        self.assertNotIn(attack, report)
        self.assertNotIn('<img ', report)
        self.assertNotIn('href="javascript:', report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn('href="#sample-0"', report)
        self.assertIn('id="method"', report)
        self.assertIn('source.parquet', report)
        self.assertIn('2026-09-30', report)
        self.assertIn('NOT human gold', report)
        self.assertIn('NOT ASSESSED', report)
        self.assertIn('Content-Security-Policy', report)
        self.assertEqual(report.count('<script>'), 1)
        self.assertEqual(report, render_report(metrics, manifest, annotations, [output]))


if __name__ == "__main__":
    unittest.main()
