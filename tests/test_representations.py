"""Offline integration tests using a deterministic provider, never model claims."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from representations.alignment import align
from representations.analysis import analyze
from representations.chunking import split_text
from representations.config import load_config
from representations.evaluation import evaluate, review_manifest
from representations.inputs import prepare
from representations.projection import apply_pca, project
from representations.providers import HTTPProvider, ProviderError, validated_vectors
from representations.report import build_report
from representations.runner import embed, request_identity
from representations.storage import digest, file_hash, read_json, read_rows, write_json, write_rows
from representations.url_path import normalize_path


class FakeProvider:
    def __init__(self, dimensions=8):
        self.calls, self.dimensions = 0, dimensions

    def embed(self, texts, role):
        self.calls += 1
        arrays = []
        for text in texts:
            seed = int(hashlib.sha256((role + text).encode()).hexdigest()[:8], 16)
            arrays.append(np.random.default_rng(seed).normal(size=self.dimensions).astype(np.float32))
        return arrays, {"test_only": True}


def fixture(root, count=8):
    write_json(root / "manifest.json", {"schema_version": "1.0.0", "status": "complete", "run_identity": "fixture"})
    records, snapshots, extracts, blocks, features, selections = [], [], [], [], [], []
    for i in range(count):
        sid = f"s{i}"
        snapshot = {"snapshot_id": sid, "payload_hash": f"payload{i}", "href": f"https://host{i}.example/journal/running-shoes-{i}", "hostname": f"host{i}.example"}
        snapshots.append(snapshot)
        records.append({**snapshot, "record_id": f"r{i}", "prompt": f"What shoes are useful for runner {i}?", "citation_category": "top" if i % 2 else "bottom"})
        selected = [
            {"block_id": "b0", "order": 0, "parent_id": None, "type": "paragraph", "text": "Preamble " + str(i)},
            {"block_id": "b1", "order": 1, "parent_id": None, "type": "heading", "heading_level": 1, "text": "Running " + str(i)},
            {"block_id": "b2", "order": 2, "parent_id": None, "type": "paragraph", "text": f"Useful shoes for runner {i}. </script><img src=x onerror=alert(1)>"},
            {"block_id": "b3", "order": 3, "parent_id": None, "type": "heading", "heading_level": 2, "text": "Specifications"},
            {"block_id": "b4", "order": 4, "parent_id": None, "type": "table", "text": "Weight 100g", "table": {"caption": "Weights", "cells": [{"row": 0, "column": 0, "text": "Weight", "is_header": True, "rowspan": 2, "colspan": 1}, {"row": 1, "column": 1, "text": "100g", "headers": ["weight"], "rowspan": 1, "colspan": 1}]}},
            {"block_id": "b5", "order": 5, "parent_id": None, "type": "code", "text": "  code\n    indentation\n"},
        ]
        extracts.append({"snapshot_id": sid, "method": "fixture", "status": "ok", "text": "source", "metadata": "{}"})
        blocks.extend({"snapshot_id": sid, "method": "fixture", "block_json": json.dumps(b)} for b in selected)
        features.append({"snapshot_id": sid, "inventory_json": json.dumps({"title": f"Shoes {i}", "language": "en"})})
        selections.append({"snapshot_id": sid, "status": "selected", "method": "fixture", "quality_flags": []})
    for name, rows in (("records", records), ("snapshots", snapshots), ("extractions", extracts), ("blocks", blocks), ("source_features", features), ("selection", selections)):
        write_rows(root / (name + ".parquet"), rows)


class RepresentationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source, self.run = self.root / "source", self.root / "run"
        fixture(self.source)
        self.config = load_config()
        self.config["models"] = {"test": {**self.config["models"]["openai-large"], "model": "test-only", "dimensions": 8, "concurrency": 1}}

    def tearDown(self):
        self.tmp.cleanup()

    def prepared(self):
        return prepare(self.source, self.run, self.config)

    def embedded(self):
        self.prepared()
        return embed(self.run, "test", provider=FakeProvider())

    def test_path_rules(self):
        self.assertEqual(normalize_path("https://stride.example/journal/running-shoes?a=secret#x")["text"], "journal / running shoes")
        self.assertEqual(normalize_path("https://x.example/a%2Fb/c_d")["segments"], ["a/b", "c d"])
        self.assertEqual(normalize_path("https://x.example/a+b/%E9%9E%8B")["text"], "a+b / 鞋")
        for bad in ("https://x.example/", "javascript:alert(1)", "https://x.example/%FF", "https://x.example/%G0", "https://x.example/%00", "https://x.example:bad/a"):
            self.assertEqual(normalize_path(bad)["status"], "unavailable")
        self.assertEqual(normalize_path("https://x.example//12/")["text"], "12")

    def test_chunking_lossless_unicode(self):
        text = "你好 world\n" * 100
        parts = list(split_text(text, 64))
        self.assertEqual("".join(p[0] for p in parts), text)
        self.assertTrue(all(len(p[0].encode()) <= 64 for p in parts))
        self.assertEqual([p[1] for p in parts][1:], [p[2] for p in parts][:-1])
        bounded = list(split_text("aaaaa\n\nbbbbb\n\nccccc", 14, boundaries=[7, 14]))
        self.assertEqual(bounded[0][2], 14)

    def test_inputs_structure_and_label_independence(self):
        self.prepared()
        original = read_rows(self.run / "units.parquet")
        views = {u["view"] for u in original}
        self.assertEqual(views, {"query", "title", "outline", "section", "page", "path"})
        page = next(u for u in original if u["view"] == "page")
        self.assertIn('"rowspan": 2', page["text"])
        self.assertIn("  code\n    indentation", page["text"])
        section = next(u for u in original if u["section_id"] == "b3")
        self.assertIn("# Running", section["text"])
        self.assertIn("b1", section["block_ids"])
        records = read_rows(self.source / "records.parquet")
        for r in records:
            r["citation_category"] = "bottom" if r["citation_category"] == "top" else "top"
        write_rows(self.source / "records.parquet", records)
        prepare(self.source, self.root / "other", self.config)
        self.assertEqual(original, read_rows(self.root / "other" / "units.parquet"))

    def test_schema_and_join_rejection(self):
        rows = read_rows(self.source / "selection.parquet")
        write_rows(self.source / "selection.parquet", rows[:-1])
        with self.assertRaisesRegex(ValueError, "every snapshot"):
            self.prepared()

    def test_missing_prompt_requires_verified_hydration(self):
        rows = read_rows(self.source / "records.parquet")
        for row in rows:
            row.pop("prompt")
        write_rows(self.source / "records.parquet", rows)
        with self.assertRaisesRegex(ValueError, "lack prompts"):
            self.prepared()

    def test_verified_raw_hydration(self):
        source = self.root / "hydrate"
        fixture(source, count=1)
        raw = self.root / "raw"
        payload = '<h1>Original</h1>'
        href = 'https://host0.example/journal/running-shoes-0'
        write_rows(raw / "part.parquet", [{"html_content": payload, "href": href, "hostname": "host0.example", "prompt": "Original prompt", "citation_category": "top"}])
        payload_hash = hashlib.sha256(payload.encode()).hexdigest()
        for name in ['records', 'snapshots']:
            rows = read_rows(source / (name + '.parquet'))
            rows[0]['payload_hash'] = payload_hash
            if name == 'records':
                rows[0].pop('prompt')
                rows[0].update(source_file='data/raw/part.parquet',source_file_hash=file_hash(raw/'part.parquet'),source_row=0)
            write_rows(source / (name + '.parquet'),rows)
        prepare(source,self.run,self.config,raw_root=raw)
        self.assertEqual(read_rows(self.run/'associations.parquet')[0]['prompt'],'Original prompt')
        write_rows(raw/'part.parquet',[{'modified':True}])
        with self.assertRaisesRegex(ValueError,'hash differs'):
            prepare(source,self.root/'tampered',self.config,raw_root=raw)

    def test_indices_and_invalid_vectors(self):
        self.assertEqual(validated_vectors([{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}], 2, 2)[0].tolist(), [1, 0])
        for data in ([{"index": 0, "embedding": [0, 0]}], [{"index": 0, "embedding": [np.nan, 1]}], [{"index": 0, "embedding": [1]}], [{"index": 1, "embedding": [1, 2]}]):
            with self.assertRaises(ProviderError):
                validated_vectors(data, 1, 2)

    def test_partial_resume_and_no_repeated_calls(self):
        self.prepared()
        provider = FakeProvider()
        partial = embed(self.run, "test", provider=provider, max_requests=1)
        self.assertEqual(partial["status"], "partial")
        full = embed(self.run, "test", provider=provider, resume=True)
        self.assertEqual(full["status"], "complete")
        count = provider.calls
        repeated = embed(self.run, "test", provider=provider, resume=True)
        self.assertEqual(provider.calls, count)
        self.assertEqual(full, repeated)

    def test_long_page_pooling_and_request_identity(self):
        blocks = read_rows(self.source / 'blocks.parquet')
        for row in blocks:
            if row['snapshot_id']=='s0' and json.loads(row['block_json'])['block_id']=='b2':
                block=json.loads(row['block_json']);block['text']='Large original content 你好\n'*1000
                row['block_json']=json.dumps(block)
        write_rows(self.source/'blocks.parquet',blocks)
        self.embedded()
        units=read_rows(self.run/'units.parquet')
        pool=next(u for u in units if u['snapshot_id']=='s0' and u['view']=='page' and u['status']=='derived')
        members=json.loads(pool['diagnostics_json'])['members']
        lookup={u['unit_id']:u for u in units}
        self.assertGreater(len(members),1)
        self.assertIn('你好',''.join(lookup[uid]['text'] for uid in members))
        u=lookup[members[0]];cfg=self.config['models']['test']
        self.assertNotEqual(request_identity(u,cfg),request_identity({**u,'role':'query'},cfg))
        self.assertNotEqual(request_identity(u,cfg),request_identity(u,{**cfg,'revision':'changed'}))

    def test_http_adapter_roles_and_dimensions(self):
        class Response:
            status_code=200
            def json(self):return {'data':[{'index':0,'embedding':[1.0]*8}],'usage':{}}
        config=self.config['models']['test']
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fixture-only'}),patch('representations.providers.httpx.post',return_value=Response()) as post:
            HTTPProvider(config).embed(['A source paragraph'],'document')
            body=post.call_args.kwargs['json']
            self.assertEqual(body['dimensions'],8)
            self.assertNotIn('input_type',body)
        config={**config,'provider':'voyage'}
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fixture-only'}),patch('representations.providers.httpx.post',return_value=Response()) as post:
            HTTPProvider(config).embed(['A query'],'query')
            body=post.call_args.kwargs['json']
            self.assertEqual(body['input_type'],'query')
            self.assertFalse(body['truncation'])
        with patch.dict('os.environ',{'OPENAI_API_KEY':'fixture-only'}):
            with self.assertRaisesRegex(ProviderError,'pinned'):
                HTTPProvider({**config,'provider':'openrouter','provider_order':[]})

    def test_retry_and_failure_ledger(self):
        self.prepared()
        provider = FakeProvider()
        original = provider.embed
        attempts = []
        def flaky(texts, role):
            attempts.append(1)
            if len(attempts) == 1:
                raise ProviderError("rate_limit", retryable=True)
            return original(texts, role)
        provider.embed = flaky
        sleeps = []
        status = embed(self.run, "test", provider=provider, sleep=sleeps.append)
        self.assertEqual(status["status"], "complete")
        self.assertEqual(sleeps, [1])
        other = self.root / "failed"
        prepare(self.source, other, self.config)
        provider.embed = lambda *args: (_ for _ in ()).throw(ProviderError("invalid_input"))
        status = embed(other, "test", provider=provider)
        self.assertEqual(status["status"], "complete_with_failures")
        status = embed(other, "test", provider=FakeProvider(), resume=True, retry_failed=True)
        self.assertEqual(status["status"], "complete")

    def test_alignment_missing_is_not_zero(self):
        rows = read_rows(self.source / "records.parquet")
        rows[0]["prompt"] = "  "
        write_rows(self.source / "records.parquet", rows)
        self.embedded()
        result = align(self.run, "test")
        self.assertEqual(result["available"], 7)
        manifest = read_json(self.run / "manifest.json")
        missing = next(r for r in read_rows(self.run / manifest["alignment"]["test"]["path"]) if r["record_id"] == "r0")
        self.assertIsNone(missing["path_similarity"])
        self.assertEqual(missing["best_section_unit_ids"], [])

    def test_training_pca_fit_and_apply(self):
        self.embedded()
        pages = sorted([u["unit_id"] for u in read_rows(self.run / "units.parquet") if u["view"] == "page"])
        fit_path = self.root / "fit.json"
        write_json(fit_path, {"scope": "training", "unit_ids": pages[:5], "heldout_unit_ids": pages[5:]})
        result = project(self.run, "test", components=2, fit_manifest=fit_path)
        folder = self.run / "projections" / result["projection_id"]
        output = self.root / "applied.parquet"
        apply_pca(self.run, "test", folder, output)
        expected = {r["unit_id"]: r["coordinates"] for r in read_rows(folder / "pca.parquet")}
        for row in read_rows(output):
            np.testing.assert_allclose(row["coordinates"], expected[row["unit_id"]], atol=1e-6)
        write_json(fit_path, {"scope": "training", "unit_ids": pages[:5], "heldout_unit_ids": pages[:2]})
        with self.assertRaisesRegex(ValueError, "overlapping"):
            project(self.run, "test", components=2, fit_manifest=fit_path)

    def test_review_manifest_requires_complete_judgments(self):
        self.embedded()
        review = self.root / "review.json"
        review_manifest(self.run, review, cases=8)
        with self.assertRaisesRegex(ValueError, "grades"):
            evaluate(self.run, "test", review, self.root / "metrics.json")
        data = read_json(review)
        self.assertNotIn('citation_category', json.dumps(data))
        for case in data["cases"]:
            for annotation in case["annotations"]:
                annotation["grade"] = 2
        write_json(review, data)
        result = evaluate(self.run, "test", review, self.root / "metrics.json")
        self.assertGreater(result["ndcg_at_5"]["denominator"], 0)
        self.assertAlmostEqual(result["ndcg_at_5"]["mean"], 1)

    def test_umap_and_escaped_explorer(self):
        self.embedded()
        align(self.run, "test")
        project(self.run, "test", components=2, exploratory=True, umap=True)
        output = self.root / "explorer.html"
        result = build_report(self.run, output)
        self.assertEqual(result["maps"], 1)
        html = output.read_text()
        self.assertNotIn('</script><img', html)
        self.assertIn('\\u003c/script>', html)
        self.assertNotIn('__EXPLORER_DATA__', html)

    def test_grouped_predictive_ablations(self):
        self.embedded()
        align(self.run,'test')
        output=self.root/'predictive.json'
        analyze(self.run,'test',output)
        results=read_json(output)
        self.assertEqual(results['urls'],8)
        self.assertEqual(len(results['results']),5)
        for value in results['results'].values():
            for fold in value['folds']:
                self.assertFalse(set(fold['training_urls']) & set(fold['heldout_urls']))


if __name__ == "__main__":
    unittest.main()
