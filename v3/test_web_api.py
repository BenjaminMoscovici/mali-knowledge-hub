"""API boundary tests without network or live provider credentials."""

import asyncio
import sys
import types
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

import web_api


class User:
    def __init__(self, uid):
        self.id = uid
        self.email = uid + "@example.org"


class MemoryStore:
    accounts = {}

    def __init__(self, uid):
        self.uid = uid
        self.data = self.accounts.setdefault(uid, {})

    def list_conversations(self):
        return [v["conversation"] for v in self.data.values()]

    def create_conversation(self, cid, title, mode):
        row = {"id": cid, "title": title, "analysis_mode": mode}
        self.data[cid] = {"conversation": row, "messages": []}
        return row

    def list_messages(self, cid):
        return list(self.data[cid]["messages"]) if cid in self.data else []

    def save_exchange(self, cid, position, question, standalone, answer, mode, refs):
        self.data[cid]["messages"].extend([
            {"position": position, "role": "user", "content": question,
             "standalone_question": standalone},
            {"position": position+1, "role": "assistant", "content": answer,
             "evidence_refs": refs, "analysis_mode": mode},
        ])


def engine():
    fake = types.ModuleType("analysis_core")
    fake.openai_client = types.SimpleNamespace(begin=lambda: (None, "context-test"),
        finish=lambda token, query_id: {"estimated_usd": 0.001, "unpriced_calls": 0})
    fake.likely_context_dependent_followup = lambda q, prior: bool(prior)
    fake.resolve_conversational_question = lambda q, prior: q + " [context: " + prior[0]["content"] + "]"
    fake.is_source_inventory_question = lambda q: False
    fake.source_inventory_answer = lambda: ""
    fake.generate_grounded_answer = lambda q, depth, response_language: {
        "answer": response_language + ": Freshly grounded [E01] for " + q,
        "evidence": [{"evidence_id": "E01", "source_type": "knowledge_base_document",
                      "chunk_id": 9, "document_title": "Test source", "content": "Source text"}],
    }
    return fake


class WebAPITests(unittest.TestCase):
    def setUp(self):
        MemoryStore.accounts = {}
        self.client = TestClient(web_api.app, base_url="https://mali-knowledge-hub.onrender.com")
        self.engine_patch = patch.dict(sys.modules, {"analysis_core": engine()})
        self.engine_patch.start()
        self.actor_patch = patch.object(web_api, "actor", side_effect=self.actor)
        self.actor_patch.start()
        self.store_patch = patch.object(web_api, "store_for", side_effect=lambda u,t: MemoryStore(u.id))
        self.store_patch.start()

    def tearDown(self):
        self.actor_patch.stop(); self.store_patch.stop(); self.engine_patch.stop()
        self.client.close()

    async def actor(self, request):
        uid = request.headers.get("x-test-actor")
        return (User(uid), "fake-jwt", None) if uid else (None, None, None)

    def post(self, path, data, uid=None):
        headers={"Origin": "https://mali-knowledge-hub.onrender.com"}
        if uid: headers["x-test-actor"] = uid
        return self.client.post(path, json=data, headers=headers)

    def test_guest_answer_and_citations_without_login(self):
        response = self.post("/api/chat", {"question":"Needs in Mopti?", "analysis_mode":"balanced"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["saved"])
        self.assertEqual(payload["evidence"][0]["content"], "Source text")
        self.assertIn("[E01]", payload["answer"])

    def test_account_history_is_private_and_followup_retrieves_again(self):
        initial = self.post("/api/chat", {"question":"Needs in Gao?", "analysis_mode":"quick"}, "alice")
        self.assertEqual(initial.status_code, 200)
        cid = initial.json()["conversation_id"]
        self.assertEqual(self.client.get(f"/api/conversations/{cid}", headers={"x-test-actor":"bob"}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/conversations/{cid}", headers={"x-test-actor":"alice"}).json()["messages"][1]["role"], "assistant")
        followup = self.post("/api/chat", {"question":"And the priorities?", "conversation_id":cid}, "alice")
        self.assertEqual(followup.status_code, 200)
        self.assertIn("context: Needs in Gao?", followup.json()["standalone_question"])
        self.assertIn("Freshly grounded", followup.json()["answer"])

    def test_rewritten_followup_keeps_original_answer_language(self):
        with patch.object(sys.modules["analysis_core"], "resolve_conversational_question", return_value="Bandiagara: regional needs evidence?"):
            response = self.post("/api/chat", {
                "question": "Et à Bandiagara précisément : peut-on déduire les besoins du cercle à partir du total régional ?",
                "prior_messages": [{"role": "user", "content": "Besoins à Mopti ?"}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["standalone_question"], "Bandiagara: regional needs evidence?")
        self.assertTrue(response.json()["answer"].startswith("French:"))

    def test_french_source_inventory_uses_original_question_language(self):
        fake=sys.modules["analysis_core"]
        with patch.object(fake, "is_source_inventory_question", return_value=True), \
             patch.object(fake, "source_inventory_answer", side_effect=lambda language: language+": catalogue") as catalogue:
            response=self.post("/api/chat", {"question":"Quelles sont vos sources ?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "French: catalogue")
        catalogue.assert_called_once_with("French")

    def test_followup_usage_includes_context_rewrite_without_prompt_logging(self):
        with patch("builtins.print") as logged:
            response = self.post("/api/chat", {
                "question": "Et les priorités ?",
                "prior_messages": [{"role": "user", "content": "Besoins à Mopti ?"}],
            })
        self.assertEqual(response.status_code, 200)
        records = [call.args[0] for call in logged.call_args_list]
        record = next(value for value in records if value.startswith("MKH_REQUEST_USAGE "))
        import json
        usage = json.loads(record.split(" ", 1)[1])
        self.assertEqual(usage["estimated_usd"], 0.001)
        self.assertNotIn("priorités", record)
        self.assertNotIn("Besoins", record)

    def test_mutation_requires_same_origin(self):
        response = self.client.post("/api/chat", json={"question":"A question"},
                                    headers={"Origin":"https://attacker.example"})
        self.assertEqual(response.status_code, 403)

    def test_expired_account_cannot_silently_continue_saved_thread_as_guest(self):
        initial = self.post("/api/chat", {"question":"Needs in Gao?"}, "alice")
        cid = initial.json()["conversation_id"]
        response = self.post("/api/chat", {"question":"And the priorities?", "conversation_id":cid})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(MemoryStore.accounts["alice"][cid]["messages"]), 2)

    def test_private_responses_are_not_cached(self):
        response = self.post("/api/chat", {"question":"Needs in Gao?"}, "alice")
        cid = response.json()["conversation_id"]
        detail = self.client.get(f"/api/conversations/{cid}", headers={"x-test-actor":"alice"})
        self.assertEqual(detail.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
