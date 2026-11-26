import json
import os
import unittest
from unittest.mock import patch

import httpx
from starlette.testclient import TestClient

from app import create_app
from companion import answer_prefix
from state import BURST_ATTEMPTS, PreviewSessions, StateError


class StreamingDelivery(unittest.TestCase):
    def test_only_decoded_answer_is_visible_at_every_chunk_boundary(self):
        answer = 'A "quote", slash \\, line\nMali – Ségou 🌾'
        raw = json.dumps({"answer": answer, "requirement_changes": [{"quote": "hidden metadata"}]})
        previous = ""
        for end in range(len(raw) + 1):
            prefix = answer_prefix(raw[:end])
            self.assertTrue(answer.startswith(prefix) and prefix.startswith(previous), end)
            previous = prefix
        self.assertEqual(previous, answer)
        self.assertEqual(answer_prefix('{"arguments":{"answer":"tool contents"}}'), "")

    def test_provider_events_deliver_draft_then_final_without_private_payloads(self):
        answer = "Published draft"
        raw = json.dumps({"answer": answer, "requirement_changes": []})
        def model(request):
            self.assertTrue(json.loads(request.content)["stream"])
            events = [
                {"type": "response.reasoning_text.delta", "delta": "private-test-sentinel"},
                {"type": "response.output_item.added", "item": {"type": "message"}},
                {"type": "response.output_text.delta", "delta": raw[:17]},
                {"type": "response.output_text.delta", "delta": raw[17:]},
                {"type": "response.completed", "response": {"status": "completed", "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": raw}]}]}},
            ]
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                text="".join("data: " + json.dumps(e) + "\n\n" for e in events))
        headers = {"Origin": "http://testserver"}
        with patch.dict(os.environ, {"OPENAI_API_KEY":"fixture", "MKH_SEMANTIC_SEARCH":"off"}), TestClient(
            create_app(httpx.MockTransport(model))
        ) as client:
            first = client.post("/api/chat", json={"prompt": "Draft a note"}, headers=headers)
            events = [json.loads(line) for line in first.text.splitlines()]
            self.assertNotIn("private-test-sentinel", first.text)
            drafts = [e["text"] for e in events if e["type"] == "draft"]
            self.assertGreater(len(drafts), 1)
            self.assertTrue(answer.startswith(drafts[0]))
            self.assertEqual(events[-1]["text"], answer)
            chat = events[-1]["conversation_id"]
            # A reload and nine turns use the same private guest session.
            saved = "/api/conversations/" + chat
            for i in range(8):
                started = client.post("/api/chat", json={"prompt": f"Follow-up {i}", "conversation_id": chat,
                                                         "delivery": "job"}, headers=headers)
                stream = client.get("/api/jobs/" + started.json()["job_id"] + "?watch=1")
                self.assertEqual(json.loads(stream.text.splitlines()[-1])["event"]["type"], "answer")
            self.assertEqual(len(client.get(saved).json()["turns"]), 9)
            client.cookies.clear()
            self.assertEqual(client.get(saved).status_code, 410)

    def test_burst_reopens_after_five_minutes_and_shared_ceiling_still_applies(self):
        preview = PreviewSessions()
        with patch("state.time.monotonic", return_value=0):
            _, guest, _ = preview.guest(None)
            for _ in range(BURST_ATTEMPTS):
                preview.reserve(guest)
            with self.assertRaisesRegex(StateError, "five minutes"):
                preview.reserve(guest)
        with patch("state.time.monotonic", return_value=301):
            preview.reserve(guest)
            for _ in range(preview.DAILY_PREVIEW_ASSIGNMENTS - len(preview.attempts)):
                preview.reserve()
            with self.assertRaisesRegex(StateError, "shared preview"):
                preview.reserve()
