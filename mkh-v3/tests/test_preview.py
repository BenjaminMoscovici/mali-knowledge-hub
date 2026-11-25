"""Checks for the V3 publication, tool and continuation boundaries."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from starlette.testclient import TestClient

from app import create_app
from knowledge import CANON, Evidence, Knowledge, KnowledgeError
from state import History

CH = "mli-ch-late2025"
WDI = "world-bank-wdi-mli"
MOPTI_SQL = """
SELECT period_type, COUNT(*) AS area_count, ROUND(SUM(people_phase_3_plus), 1) AS estimate
FROM ch_mali WHERE source_region = 'Mopti' GROUP BY period_type ORDER BY period_type
"""


class PublishedKnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.knowledge = Knowledge()
        self.ledger = Evidence(self.knowledge, False)

    def test_mopti_calculation_and_ambiguity(self):
        calculation = self.knowledge.query([CH], MOPTI_SQL, self.ledger)
        self.assertEqual(calculation["data"]["rows"], [
            {"period_type": "current", "area_count": 8, "estimate": 201343.4},
            {"period_type": "projected", "area_count": 8, "estimate": 346629.8},
        ])
        self.assertEqual(calculation["data"]["input_releases"][0]["source_id"], CH)
        matches = self.knowledge.geography("Mopti", None, self.ledger)
        self.assertEqual({x["data"]["level"] for x in matches}, {"region", "cercle", "commune"})
        quantities = self.knowledge.query([CH], """
            SELECT id, source_area, area_mapping_status FROM ch_mali
            WHERE source_region = 'Mopti' AND source_area = 'Bandiagara'
            ORDER BY period_start
        """, self.ledger)
        self.assertTrue(all(r["area_mapping_status"] == "unresolved" for r in quantities["data"]["rows"]))
        self.assertTrue(all(" / row " in item["locator"] for item in quantities["data"]["input_records"]))

    def test_read_only_boundary_and_publication(self):
        for sql in ("PRAGMA table_list", "SELECT name FROM sqlite_master", "SELECT 1; SELECT 2",
                    "UPDATE ch_mali SET area_phase = 4"):
            with self.subTest(sql=sql), self.assertRaises(KnowledgeError):
                self.knowledge.query([CH], sql, self.ledger)
        with self.assertRaises(KnowledgeError):
            self.knowledge.query([CH, "mli-instat-localities-2023"], "SELECT 1", self.ledger)
        with self.assertRaises(KnowledgeError):
            self.ledger.add_web("https://example.org/", "Unapproved web source")

    def test_unseen_source_is_discoverable_and_queryable_by_metadata(self):
        with tempfile.TemporaryDirectory() as path:
            directory = Path(path)
            shutil.copytree(CANON, directory, dirs_exist_ok=True)
            metadata = {
                "id": "market-observations", "review": "published", "title": "Market observations",
                "type": "dataset", "publisher": "QA fixture", "release": "test vintage", "period": "August",
                "geography": "Ségou", "url": "https://example.org/fixture", "limitations": [],
                "topics": ["prix du marché", "market prices", "millet"], "description": "Fictional fixture",
                "table": "market_observations",
                "columns": {"id": "TEXT", "locator": "TEXT", "price": "REAL"},
                "records": [{"id": "a", "locator": "row 1", "price": 10.0},
                            {"id": "b", "locator": "row 2", "price": None},
                            {"id": "c", "locator": "row 3", "price": 16.0}],
            }
            (directory / "new.json").write_text(json.dumps(metadata))
            (directory / "draft.json").write_text(json.dumps({**metadata, "id": "market-draft", "review": "draft"}))
            k = Knowledge(directory)
            self.assertEqual(k.discover("prix du marché millet")[0]["id"], metadata["id"])
            evidence = Evidence(k, False)
            result = k.query([metadata["id"]], "SELECT AVG(price) AS average FROM market_observations", evidence)
            self.assertEqual(result["data"]["rows"], [{"average": 13.0}])
            with self.assertRaises(KnowledgeError):
                k.source("market-draft")

    def test_signed_history_and_web_off(self):
        history = History("fixture-signing-value", self.knowledge, False)
        web = Evidence(self.knowledge, True).add_web("https://example.org/test", "Outside canon")
        turn = history.sign("chat", "person", {
            "prompt": "Earlier question", "answer": "External observation", "evidence": [web], "web_used": True,
        })
        self.assertEqual(list(history.accessible("chat", "person", [turn])),
                         [{"prompt": "Earlier question", "withdrawn": True}])
        self.assertEqual(list(history.accessible("chat", "person", [{**turn, "web_used": False}])),
                         [{"prompt": "Earlier question"}])
        self.assertEqual(list(history.accessible("other-chat", "person", [turn])),
                         [{"prompt": "Earlier question"}])


class CompanionEntryPointTest(unittest.TestCase):
    def test_chat_uses_discovery_sql_documents_and_live_data_then_retains_scope(self):
        stored = {}
        operation_inputs = {}
        provider_calls = []
        researched_tools = [
            ("discover_sources", {"query": "situation alimentaire Mopti", "kind": None}),
            ("inspect_source", {"source_id": CH}),
            ("query_data", {"source_ids": [CH], "sql": MOPTI_SQL}),
            ("search_documents", {"query": "reprise de la projection", "source_id": "mli-ch-june2026-bulletin"}),
            ("fetch_live", {"source_id": WDI, "series_code": "AG.YLD.CREL.KG", "start_year": 2023, "end_year": 2024}),
        ]

        def mocked(request):
            path = request.url.path
            payload = json.loads(request.content) if request.content else None
            if path == "/auth/v1/user":
                self.assertEqual(request.headers.get("authorization"), "Bearer test-only-session")
                return httpx.Response(200, json={
                    "id": "test-user", "aud": "authenticated", "email_confirmed_at": "2026-10-01",
                })
            if path == "/rest/v1/mkh_v3_conversations":
                if request.method == "GET":
                    return httpx.Response(200, json=list(stored.values()))
                if request.method == "POST":
                    stored[payload["id"]] = payload
                    return httpx.Response(201, json=[payload])
                self.assertEqual(request.url.params["revision"], "eq.1")
                entry = next(iter(stored.values()))
                entry.update(payload)
                return httpx.Response(200, json=[entry])
            if path == "/rest/v1/mkh_v3_attempts":
                return httpx.Response(200, json=[]) if request.method == "GET" else httpx.Response(201)
            if request.url.host == "api.worldbank.org":
                base = {"indicator": {"id": "AG.YLD.CREL.KG"}, "countryiso3code": "MLI"}
                return httpx.Response(200, json=[{"lastupdated": "2026-10-01"}, [
                    {**base, "date": "2024", "value": 1482.0},
                    {**base, "date": "2023", "value": None},
                ]])
            self.assertEqual(path, "/v1/responses")
            self.assertFalse(payload["store"])
            self.assertTrue(all(tool["type"] == "function" for tool in payload.get("tools", [])))
            call_number = len(provider_calls)
            provider_calls.append(payload)
            for item in payload["input"]:
                if item.get("type") == "function_call_output":
                    operation_inputs[item["call_id"]] = json.loads(item["output"])
            if call_number < len(researched_tools):
                name, args = researched_tools[call_number]
                output = [{"type": "function_call", "name": name, "call_id": f"call_{call_number}",
                           "arguments": json.dumps(args)}]
            else:
                calculation = operation_inputs["call_2"]
                references = [calculation["id"], operation_inputs["call_3"][0]["id"],
                              operation_inputs["call_4"]["id"]]
                answer = "## Note sur Mopti\nAnalyse de la période source. " + " ".join(f"[[{x}]]" for x in references)
                if call_number > len(researched_tools):
                    self.assertEqual(payload["input"][0]["content"], "Note en français pour la zone historique de Mopti.")
                    self.assertIn("Modifie seulement la période.", payload["input"][-1]["content"])
                    answer = "Période modifiée. [[" + calculation["id"] + "]]"
                output = [{"type": "message", "content": [{"type": "output_text", "text": answer}]}]
            return httpx.Response(200, json={"status": "completed", "output": output,
                                              "usage": {"input_tokens": 34, "output_tokens": 20}})

        cfg = {"SUPABASE_URL": "https://test.invalid", "SUPABASE_PUBLISHABLE_KEY": "test-publishable",
               "OPENAI_API_KEY": "test-only-key", "MKH_WEB_RESEARCH": "false"}
        with patch.dict(os.environ, cfg), TestClient(create_app(httpx.MockTransport(mocked))) as client:
            headers = {"Origin": "http://testserver"}
            blocked = client.post("/api/chat", json={"prompt": "Bonjour"}, headers=headers)
            self.assertEqual(blocked.status_code, 401)
            client.cookies.set("mkh_v3_session", "test-only-session")
            result = client.post("/api/chat", json={"prompt": "Note en français pour la zone historique de Mopti."},
                                 headers=headers)
            events = [json.loads(line) for line in result.text.splitlines()]
            answer = events[-1]
            self.assertEqual(answer["type"], "answer")
            self.assertEqual({item["kind"] for item in answer["evidence"]},
                             {"calculation", "factual_extract", "live_observations"})
            self.assertIsNone(operation_inputs["call_4"]["data"]["rows"][1]["value"])
            conversation_id = answer["conversation_id"]
            followup = client.post("/api/chat", json={"conversation_id": conversation_id,
                                   "prompt": "Modifie seulement la période."}, headers=headers)
            self.assertEqual(json.loads(followup.text.splitlines()[-1])["conversation_id"], conversation_id)
            saved = client.get("/api/conversations/" + conversation_id).json()
            self.assertEqual(len(saved["turns"]), 2)
            self.assertNotIn("signature", saved["turns"][0])


if __name__ == "__main__":
    unittest.main()
