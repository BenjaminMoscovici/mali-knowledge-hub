import json
import unittest

import httpx

from knowledge import Evidence, Knowledge, KnowledgeError
from retrieval import SemanticSearch
from state import History


class ResearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.k = Knowledge()

    def test_identity_join_preserves_native_rows_and_complete_aggregate(self):
        k = self.k
        ledger = Evidence(k, False)
        left, right = "mli-world-bank-v3", "mli-iati-worldbank"
        result = k.link_records(left, right, "World Bank project ID",
                                "SELECT count(*) AS pairs, count(DISTINCT l_project_id) AS projects FROM linked", ledger)
        expected = sum(l["project_id"] == r["project_id"] for l in k.source(left)["records"]
                       for r in k.source(right)["records"] if r["project_id"])
        self.assertGreater(expected, 5)
        self.assertEqual(result["data"]["rows"], [{"pairs": expected, "projects": expected}])
        self.assertEqual(len(result["data"]["input_releases"]), 2)
        with self.assertRaises(KnowledgeError):
            k.link_records(left, right, "place", "SELECT count(*) FROM linked", ledger)

    def test_map_and_chart_use_actual_rows(self):
        ledger = Evidence(self.k, False)
        item = self.k.query(["mli-cod-ab"], "SELECT pcode, area_km2 FROM cod_regions ORDER BY area_km2 DESC LIMIT 4", ledger)
        for kind in ("map", "chart", "table"):
            result = ledger.present(item["id"], kind, "Area by region", "pcode", "area_km2")
            self.assertEqual(result["evidence_id"], item["id"])
        with self.assertRaises(KnowledgeError):
            ledger.present(item["id"], "map", "Area by region", "area_km2", "area_km2")
        self.assertNotIn("geometries", self.k.inspect("mli-cod-ab"))

    def test_snapshot_computation_and_dependency_withdrawal(self):
        ledger = Evidence(self.k, False)
        src = self.k.source("world-bank-wdi-mli")
        parent = ledger.add(src, "live_observations", "test years", {
            "rows": [{"year": 2020, "value": 30}, {"year": 2021, "value": None}, {"year": 2022, "value": 36}]})
        result = self.k.query_result(parent["id"], "SELECT avg(value) AS mean, count(value) AS observed FROM prior_result", ledger)
        self.assertEqual(result["data"]["rows"], [{"mean": 33, "observed": 2}])
        self.assertEqual(result["data"]["parent_evidence"]["data"], parent["data"])
        history = History("test-only", self.k, False)
        turn = history.sign("c", "u", {"prompt":"revise", "evidence":[], "answer":"earlier answer",
                                       "basis":{"withdrawn-other-source":"old release"}})
        self.assertTrue(list(history.accessible("c", "u", [turn]))[0]["withdrawn"])

    def test_long_passage_navigation_and_context(self):
        k = self.k
        entry = max((e for e in k.index.entries if e["kind"] == "passage"), key=lambda e: e["payload"][1])
        p, offset, text = entry["payload"]
        self.assertGreater(offset, 0)
        ledger = Evidence(k, False)
        item = k.read_passage(entry["source"]["id"], p["locator"], offset, ledger)
        self.assertTrue(item["data"]["text"].startswith(text))
        self.assertIn("#page=", item["url"])
        history = History("test", k, False)
        turns = [{"prompt": f"change {i}", "answer": "note"} for i in range(11)]
        inputs, _ = history.context(turns)
        self.assertIn("change 1", inputs[0]["content"])


class RetrievalTest(unittest.IsolatedAsyncioTestCase):
    async def test_exact_semantic_fusion_and_service_failure(self):
        k = Knowledge()
        target = "mli-fts-requirements-funding"
        def embeddings(request):
            payload = json.loads(request.content)
            # Simulate a model that maps a paraphrase in a new language to the relevant record.
            result = []
            for i, text in enumerate(payload["input"]):
                relevant = target in text or text == "unseen paraphrase"
                result.append({"index": i, "embedding": [int(relevant), int(not relevant)] + [0] * 254})
            return httpx.Response(200, json={"data": result, "usage": {"total_tokens": len(result)}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(embeddings)) as client:
            engine = SemanticSearch(k.index, client, "test")
            usage = {"embedding_tokens": 0}
            cache = {}
            scores = await engine.search("unseen paraphrase", cache, usage)
            self.assertEqual(k.discover("unseen paraphrase", affinities=scores)[0]["id"], target)
            before = usage.copy()
            await engine.search("unseen paraphrase", cache, usage)
            self.assertEqual(usage, before)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
            usage = {"embedding_tokens": 0}
            scores = await SemanticSearch(k.index, client, "test").search("financement", {}, usage)
            self.assertIsNone(scores)
            self.assertTrue(usage["retrieval_fallback"])
            self.assertEqual(k.discover("financement", affinities=scores)[0]["id"], target)
