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
        self.assertEqual(len(ledger.artifacts), 3)
        aliased = self.k.query(["mli-cod-ab"], "SELECT pcode as region_id, place, area_km2 FROM cod_regions", ledger)
        mapped = ledger.present(aliased["id"], "map", "Area by region", "place", "area_km2")
        self.assertEqual(mapped["map_field"], "region_id")
        invalid = self.k.query(["mli-cod-ab"], "SELECT place, area_km2 FROM cod_regions", ledger)
        with self.assertRaises(KnowledgeError):
            ledger.present(invalid["id"], "map", "Area by region", "place", "area_km2")
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

    def test_approved_identifier_coverage_and_map_survive_source_transfer(self):
        ledger = Evidence(self.k, False)
        activities, boundary = "mli-ocha-3w-2026-q1", "mli-cod-ab"
        key = next(iter(self.k.source(activities)["entity_keys"]))
        result = self.k.link_records(activities, boundary, key,
            "SELECT r_pcode, COUNT(DISTINCT l_organization) AS actors FROM linked GROUP BY r_pcode", ledger)
        rows = self.k.source(activities)["records"]
        self.assertTrue(result["data"]["relationship"]["left_unmatched_rows"] > 0)
        self.assertEqual(result["data"]["relationship"]["matched_pairs"], sum(bool(r["cod_region_id"]) for r in rows))
        self.assertEqual(result["data"]["relationship"]["left_unmatched_rows"],
                         sum(r["cod_region_id"] is None for r in rows))
        self.assertEqual(ledger.present(result["id"], "map", "Reported organizations", "r_pcode", "actors")["map_source"], boundary)
        with self.assertRaisesRegex(KnowledgeError, "multiply observations"):
            self.k.link_records(activities, "mli-dtm-round83", key, "SELECT COUNT(*) FROM linked", ledger)
        inspected = self.k.inspect(activities)
        self.assertIn("food_security", inspected["dimension_values"]["sector"]["examples"])
        self.assertIn(boundary, {r["source"] for r in inspected["relationships"]})

    def test_model_allowance_caps_the_next_call_and_accounts_for_cached_input(self):
        from companion import CompanionError, budget_response, model_cost
        usage = {"input_tokens":5000, "cached_tokens":1000, "output_tokens":300, "embedding_tokens":1200}
        model = "gpt-6.2-sol"
        self.assertAlmostEqual(model_cost(model, usage), 0.011124)
        body = {"model":model, "input":[{"role":"user","content":"draft"}], "max_output_tokens":3000}
        budget_response(body, usage, 0.020)
        self.assertLess(body["max_output_tokens"], 1000)
        with self.assertRaisesRegex(CompanionError, "allowance was reached"):
            budget_response(body, usage, 0.0112)

    def test_requirement_changes_are_grounded_in_user_words_and_recall_is_scoped(self):
        from companion import apply_requirements
        prev = {"audience": "pour le comité", "format": "un graphique", "geography": "Ségou"}
        changes = [{"dimension": "format", "action": "set", "quote": "une note"},
                   {"dimension": "audience", "action": "remove", "quote": "drop everybody"}]
        self.assertEqual(apply_requirements(prev, changes, "Fais-en une note."),
                         {**prev, "format": "une note"})
        self.assertEqual(prev["format"], "un graphique")
        ledger = Evidence(self.k, False)
        history = History("fixture", self.k, False)
        bad = history.sign("chat", "owner", {"prompt": "old task", "answer": "withdrawn fact",
                           "basis": {"unpublished": "version"}})
        good = history.sign("chat", "owner", {"prompt": "auditor", "answer": "verified previous wording"})
        accessible = list(history.accessible("chat","owner",[bad,good]))
        self.assertEqual(history.recall(accessible, "withdrawn", ledger), [])
        self.assertEqual(history.recall(accessible, "auditor", ledger)[0]["previous_answer"], good["answer"])


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
            scores = await SemanticSearch(k.index, client, "test").search("financement humanitaire OCHA FTS", {}, usage)
            self.assertIsNone(scores)
            self.assertTrue(usage["retrieval_fallback"])
            self.assertEqual(k.discover("financement humanitaire OCHA FTS", affinities=scores)[0]["id"], target)


class ResearchDeliveryTest(unittest.TestCase):
    def test_job_is_private_and_cancellation_prevents_an_answer(self):
        import asyncio
        import os
        from unittest.mock import patch
        from starlette.testclient import TestClient
        from app import create_app

        async def slow_model(request):
            await asyncio.sleep(4)
            return httpx.Response(200, json={"output": []})
        hdr = {"Origin": "http://testserver"}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "MKH_SEMANTIC_SEARCH": "off"}), TestClient(
            create_app(httpx.MockTransport(slow_model))
        ) as client:
            res = client.post("/api/chat", json={"prompt": "Write a decision note.", "delivery": "job"}, headers=hdr)
            self.assertEqual(res.status_code, 202)
            job = "/api/jobs/" + res.json()["job_id"]
            owner = client.cookies["mkh_v31_guest"]
            self.assertEqual(client.get(job).json()["event"]["type"], "activity")
            client.cookies.clear()
            self.assertEqual(client.get(job).status_code, 410)
            client.cookies.set("mkh_v31_guest", owner)
            self.assertEqual(client.delete(job).status_code, 403)
            self.assertEqual(client.delete(job, headers=hdr).json()["event"]["text"], "Assignment stopped.")
            self.assertEqual(client.get(job).json()["event"]["type"], "error")
