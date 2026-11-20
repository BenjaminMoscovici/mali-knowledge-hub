"""Exercise guest chat, actual ledger and synthesis with controlled providers."""
import importlib
import json
import sys
from types import SimpleNamespace

from starlette.testclient import TestClient

import web_api
from test_issue1_research import research_function

ORIGIN = "https://mali-knowledge-hub.onrender.com"


def test_compound_chat_synthesizes_registry_and_keeps_scope_on_followup(monkeypatch):
    for name, value in {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "fixture-key",
        "OPENAI_API_KEY": "fixture-key",
        "HDX_HAPI_APP_IDENTIFIER": "fixture-id",
    }.items():
        monkeypatch.setenv(name, value)
    original = sys.modules.get("analysis_core")
    try:
        engine = importlib.import_module("analysis_core")
        worker = research_function(monkeypatch, lambda geography: {"raw_count": 0, "evidence": []})
        monkeypatch.setattr(engine, "run_four_source_research", worker)
        prompts = []
        formats = []
        answers = []

        class ControlledProvider:
            def begin(self):
                return None, "fixture"

            def finish(self, *args):
                return {"calls": [{"endpoint": "responses"}]}

            @property
            def responses(self):
                return self

            def create(self, **kwargs):
                prompts.append(kwargs["input"])
                formats.append(kwargs.get("text"))
                if "Audit the factual support" in kwargs.get("instructions", ""):
                    lines = json.loads(kwargs["input"])["lines_to_review"]
                    return SimpleNamespace(output_text=json.dumps({"findings": [
                        {"line": int(i), "verdict": "supported", "replacement": ""} for i in lines
                    ]}))
                return SimpleNamespace(output_text=answers.pop(0))

        monkeypatch.setattr(engine, "openai_client", ControlledProvider())
        census_id = "registry:mli-instat-rgph5-global-2022"
        answers.append(json.dumps({
            "intents": [{"topic": "enumeration methods", "source_families": [census_id]}],
            "geo_entities": [], "is_meta_question": False,
        }))
        planned = engine.plan_sources_semantically("How did enumerators collect household data in 2022?")
        assert census_id in planned["planner_output"]["intents"][0]["source_families"]
        assert census_id in json.dumps(formats[-1])
        client = TestClient(web_api.app, base_url=ORIGIN)
        query = (
            "What does the 2022 census report say about enumeration methods, "
            "and how much funding does OCHA FTS report for HMLI26 in 2026?"
        )
        evidence = worker(query)["ledger"]
        census = next(row for row in evidence if row["source_type"] == "registry_document")
        funding = next(row for row in evidence if row.get("record_id") == "1300c8a4-c1c1-542a-b494-051acc8839d8")
        answers.append(f'The report documents enumeration methods [{census["evidence_id"]}]. '
                       f'The plan records USD 135,628,821 in reported funding [{funding["evidence_id"]}].')
        result = client.post("/api/chat", json={"question": query}, headers={"Origin": ORIGIN}).json()
        assert result["metrics"]["route"] == "complex_research"
        assert "135,628,821" in result["answer"]
        assert "PDF page" in prompts[-1]
        assert census["evidence_id"] in {row["evidence_id"] for row in result["evidence"]}

        answers.append(f'Enumeration method [{census["evidence_id"]}]. '
                       f'Reported funding: USD 135,628,821 [{funding["evidence_id"]}].')
        brief = client.post("/api/chat", headers={"Origin": ORIGIN}, json={
            "question": "Turn it into a short brief.",
            "prior_messages": [
                {"role": "user", "content": query},
                {"role": "assistant", "content": "Prior draft only [E99].", "standalone_question": query},
                {"role": "user", "content": "Thanks."},
                {"role": "assistant", "content": "You’re welcome."},
            ],
        }).json()
        assert brief["metrics"]["context_resolution_method"] == "cited_brief_replay"
        assert brief["standalone_question"] == query
        assert "short professional brief" in prompts[-2] and query in prompts[-2]
        assert "Prior draft only" not in prompts[-2]
        assert funding["evidence_id"] in brief["answer"]
        assert any(row.get("record_id") == funding["record_id"] for row in brief["evidence"])

        original_question = "What did OCHA FTS say about reported funding for HMLI26 in 2026?"
        revised = original_question.replace("2026", "2025")
        status = next(row for row in worker(revised)["ledger"]
                      if row["source_type"] == "source_availability" and "no_matching_evidence" in row["content"])
        answers.append(f'The requested year has no matching financing record [{status["evidence_id"]}].')
        follow = client.post("/api/chat", headers={"Origin": ORIGIN}, json={
            "question": "And in 2025?",
            "prior_messages": [
                {"role": "user", "content": original_question},
                {"role": "assistant", "content": "Reported funding was made-up [E99]."},
            ],
        }).json()
        assert follow["metrics"]["context_resolution_method"] == "registry_research_reference_year"
        assert follow["standalone_question"] == original_question.replace("2026", "2025")
        assert "made-up" not in prompts[-1] and "HMLI26 in 2025" in prompts[-1]
        assert "no_matching_evidence" in prompts[-1]
        assert "no matching financing record" in follow["answer"]
        assert not any(row.get("record_id") == funding["record_id"] for row in follow["evidence"])
    finally:
        if original is None:
            sys.modules.pop("analysis_core", None)


def test_read_only_qualification_skips_startup_publishers(monkeypatch):
    monkeypatch.setenv("MKH_READ_ONLY_QUALIFICATION", "1")
    calls = []
    for name in (
        "publish_snapshot_logged", "publish_operational_logged",
        "publish_analytical_logged", "publish_project_learning_logged", "publish_eu_logged",
    ):
        monkeypatch.setattr(web_api, name, lambda: calls.append("publish"))
    with TestClient(web_api.app, base_url=ORIGIN) as client:
        assert client.get("/api/health").status_code == 200
    assert calls == []
