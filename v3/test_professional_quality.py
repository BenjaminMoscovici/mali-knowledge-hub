"""Quality checks anchored in audited source scope, without external services."""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from starlette.testclient import TestClient

import web_api
from document_targets import explicit_title_targets, named_targets

ORIGIN = "https://mali-knowledge-hub.onrender.com"


def test_toponym_alternatives_list_exact_distinct_geographic_entities():
    client = TestClient(web_api.app, base_url=ORIGIN)
    response = client.post("/api/chat", headers={"Origin": ORIGIN}, json={
        "question": "Could Kayes be a region, a cercle or a commune?",
        "analysis_mode": "balanced",
    })
    assert response.status_code == 200
    result = response.json()
    assert result["metrics"]["route"] == "simple_geography"
    records = result["evidence"][0]["content"]
    import json
    observations = json.loads(records)["records"]
    assert {item["level"] for item in observations if item["name"].lower() == "kayes"} == {
        "region", "cercle", "commune"
    }
    assert "distinct identities" in result["answer"]
    assert result["metrics"]["estimated_usd"] == 0


def test_primary_document_wins_over_related_title_suffix():
    tree = ast.parse(Path(__file__).with_name("analysis_core.py").read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "build_document_evidence")
    docs = [
        {"id": "strategy", "title": "Stratégie Nationale pour l’Émergence et le Développement Durable"},
        {"id": "portfolio", "title": "Projets Structurants Prioritaires pour la mise en œuvre de la SNEDD 2024-2033"},
    ]
    seen = []

    def search(question, match_count, filter_document_ids):
        seen.append(filter_document_ids)
        return []

    scope = {
        "time": time, "ThreadPoolExecutor": ThreadPoolExecutor,
        "submit": lambda executor, fn, *args: executor.submit(fn, *args),
        "get_document_groups": lambda: {"government": ["strategy", "portfolio"], "hnrp": [], "documents": docs},
        "named_targets": named_targets, "explicit_title_targets": explicit_title_targets,
        "search_knowledge_base": search,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<qualification>", "exec"), scope)
    retrieve = scope[function.name]
    retrieve("Quels objectifs la SNEDD 2024–2033 fixe-t-elle pour la formation professionnelle ?", use_hnrp=False)
    assert seen == [["strategy"]]
    seen.clear()
    retrieve("Quel est le rôle des Projets Structurants Prioritaires pour la mise en œuvre de la SNEDD 2024–2033 ?", use_hnrp=False)
    assert seen == [["strategy"], ["portfolio"]] or seen == [["portfolio"], ["strategy"]]


def test_qualification_rejects_mutations_and_ignores_auth_cookies(monkeypatch):
    monkeypatch.setenv("MKH_READ_ONLY_QUALIFICATION", "1")
    def unavailable():
        raise AssertionError("Guest qualification must not refresh an authenticated session")
    monkeypatch.setattr(web_api, "auth_client", unavailable)
    with TestClient(web_api.app, base_url=ORIGIN) as client:
        client.cookies.set(web_api.ACCESS_COOKIE, "fixture")
        assert client.get("/api/me").json()["user"] is None
        assert client.post("/api/auth/signup", headers={"Origin": ORIGIN}, json={}).status_code == 403
        result = client.post("/api/chat", headers={"Origin": ORIGIN}, json={"question": "Hello"})
        assert result.status_code == 200 and not result.json()["saved"]


def test_commune_only_answer_does_not_receive_admin2_numbers_from_hapi():
    from synthesis_context import prepare

    needs = {"evidence_id": "E01", "source_type": "hdx_hapi",
             "content": "Admin2/locality observation: 156,243 people in need."}
    presence = {"evidence_id": "E02", "source_type": "operational_presence",
                "content": "Commune source label unverified; recorded presence only."}
    selected, audit = prepare([needs, presence], "Uniquement pour la commune de Mopti : quels besoins ?")
    assert [item["evidence_id"] for item in selected] == ["E02"]
    assert audit["scope_withheld_ids"] == ["E01"]
    direct, _ = prepare([needs, presence], "What needs are documented in Mopti commune?")
    assert [item["evidence_id"] for item in direct] == ["E02"]
    broader, _ = prepare([needs, presence], "Compare the commune with the region.")
    assert needs in broader
