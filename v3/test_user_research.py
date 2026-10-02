import unittest
import ast
from pathlib import Path
from types import SimpleNamespace

from user_research import (ResearchStore, ResearchStoreError,
                           evidence_references, hydrate_saved_evidence)


class Response:
    content = b"[]"

    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self.rows


class Session:
    def __init__(self):
        self.calls = []
        self.rows = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return Response(self.rows)


class PagedSession(Session):
    def __init__(self, rows):
        super().__init__()
        self.all_rows = rows

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        params = kwargs["params"]
        start = int(params["offset"])
        limit = int(params["limit"])
        return Response(self.all_rows[start:start + limit])


class UserResearchTests(unittest.TestCase):
    def setUp(self):
        self.http = Session()
        self.store = ResearchStore("https://project.supabase.co", "publishable",
                                   "signed-jwt", "owner-uuid", session=self.http)

    def test_private_reads_use_signed_user_and_owner_filter(self):
        self.store.list_conversations()
        self.store.list_messages("thread-uuid")
        for method, url, kwargs in self.http.calls:
            self.assertEqual(method, "GET")
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer signed-jwt")
            self.assertEqual(kwargs["headers"]["apikey"], "publishable")
            self.assertEqual(kwargs["params"]["user_id"], "eq.owner-uuid")
            self.assertNotIn("secret", str(kwargs).lower())

    def test_evidence_history_contains_references_without_passages(self):
        refs = evidence_references({"evidence": [
            {"evidence_id": "D1", "document_id": "doc-1", "chunk_id": 34,
             "document_title": "Appeal", "page": 2,
             "valid_from": "2025-01-01", "valid_until": "2025-12-31",
             "content": "A full extracted paragraph", "passage": "A full report"},
            {"evidence_id": "H1", "source_type": "hdx_hapi",
             "source_endpoint": "/api/v1/metadata", "resource_hdx_id": "abc",
             "content": "Structured figures"},
        ]})
        self.assertEqual(refs[0]["chunk_id"], 34)
        self.assertEqual(refs[0]["valid_until"], "2025-12-31")
        self.assertEqual(refs[1]["resource_hdx_id"], "abc")
        self.assertNotIn("source_excerpt", refs[0])
        self.assertEqual(refs[1]["source_excerpt"], "Structured figures")
        self.assertNotIn("A full extracted paragraph", str(refs))

    def test_saved_passages_load_in_batches_without_a_history_limit(self):
        refs = [{"chunk_id": i, "evidence_id": f"E{i}"} for i in range(350)]
        refs.append({"evidence_id": "H1", "source_excerpt": "Historical API value"})
        result = {"saved": True, "evidence": refs}
        calls = []

        def fetch(ids):
            calls.append(ids)
            return [{"id": i, "content": f"Passage {i}"}
                    for i in ids if i != 12]

        self.assertEqual(hydrate_saved_evidence(result, fetch), 349)
        self.assertEqual([len(batch) for batch in calls], [100, 100, 100, 50])
        self.assertEqual(refs[349]["content"], "Passage 349")
        self.assertIsNone(refs[12]["content"])
        self.assertNotIn("content", refs[-1])
        self.assertTrue(result["passages_loaded"])

    def test_batch_exchange_uses_caller_identity(self):
        self.http.rows = [{"id": "first"}, {"id": "second"}]
        self.store.update_conversation = lambda *args, **kwargs: None
        self.store.save_exchange("thread-uuid", 1, "question", "standalone",
                                 "answer [D1]", "balanced", [{"evidence_id": "D1"}])
        body = self.http.calls[0][2]["json"]
        self.assertEqual([row["user_id"] for row in body], ["owner-uuid"] * 2)
        self.assertEqual([row["position"] for row in body], [1, 2])
        self.assertEqual(body[1]["evidence_refs"], [{"evidence_id": "D1"}])

    def test_long_thread_paginates_without_reusing_positions(self):
        rows = [{"position": i} for i in range(1, 503)]
        paged = PagedSession(rows)
        store = ResearchStore("https://project.supabase.co", "publishable",
                              "signed-jwt", "owner-uuid", session=paged)
        self.assertEqual(len(store.list_messages("thread-uuid")), 502)
        self.assertEqual([call[2]["params"]["offset"] for call in paged.calls],
                         ["0", "500"])

    def test_committed_exchange_can_be_recognized_after_http_failure(self):
        self.store.update_conversation = lambda *args, **kwargs: None
        def failed_post(*args, **kwargs):
            raise ResearchStoreError("timeout")
        self.store._request = failed_post
        self.store.list_messages = lambda _: [
            {"position": 1, "role": "user", "content": "Q"},
            {"position": 2, "role": "assistant", "content": "A"},
        ]
        self.store.save_exchange("thread", 1, "Q", "Q", "A", "quick", [])

    def test_delayed_save_keeps_the_mode_used_for_that_exchange(self):
        source = ast.parse((Path(__file__).parent / "app.py").read_text())
        function = next(node for node in source.body
                        if isinstance(node, ast.FunctionDef) and node.name == "sync_private_thread")
        calls = []
        store = SimpleNamespace(save_exchange=lambda *args: calls.append(args))
        thread = {"persisted": True, "saved_messages": 0, "depth": "deep",
                  "messages": [
                      {"role": "user", "content": "Q", "analysis_mode": "quick"},
                      {"role": "assistant", "content": "A", "result": None},
                  ]}
        namespace = {"st": SimpleNamespace(session_state={"kh_threads": {"id": thread}}),
                     "research_store": store, "evidence_references": evidence_references,
                     "ResearchStoreError": ResearchStoreError}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        namespace[function.name]("id")
        self.assertEqual(calls[0][5], "quick")
        self.assertEqual(thread["saved_messages"], 2)


if __name__ == "__main__":
    unittest.main()
