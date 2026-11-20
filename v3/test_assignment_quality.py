"""Exercise assignment edits and analytical source binding at normal entry points."""
import importlib
import json
from types import SimpleNamespace

from starlette.testclient import TestClient

import web_api


ORIGIN = "https://mali-knowledge-hub.onrender.com"


def test_scope_edits_reenter_normal_chat_and_compare_only_matched_rows(monkeypatch):
    for key, value in {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "fixture",
        "OPENAI_API_KEY": "fixture",
        "HDX_HAPI_APP_IDENTIFIER": "fixture",
    }.items():
        monkeypatch.setenv(key, value)
    engine = importlib.import_module("analysis_core")
    rewrites = iter([
        "What is the 2023 population of Mopti commune?",
        "Compare the 2023 populations of Mopti and Ségou communes and show percentage relative to the smaller.",
        "Compare the 2023 populations of Mopti and Ségou cercles and show percentage relative to the smaller.",
    ])
    prompts = []

    def resolve(**params):
        prompts.append(params["input"])
        return SimpleNamespace(output_text=next(rewrites))

    monkeypatch.setattr(engine, "openai_client", SimpleNamespace(
        begin=lambda: (None, "fixture"), finish=lambda *_: {"calls": [{"endpoint": "responses"}]},
        responses=SimpleNamespace(create=resolve),
    ))
    client = TestClient(web_api.app, base_url=ORIGIN)
    prior = []
    outputs = []
    for question in [
        "What is the 2023 population of Ségou commune?",
        "Replace only the location with Mopti.",
        "Using the two figures just discussed, compare them as a percentage relative to the smaller.",
        "Repeat the same comparison for cercles instead.",
    ]:
        response = client.post("/api/chat", headers={"Origin": ORIGIN},
                               json={"question": question, "prior_messages": prior})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["metrics"]["route"] == "country_fact"
        assert result["evidence"]
        if prior:
            assert result["metrics"]["context_resolution_method"] == "assignment_resolution"
        prior.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": result["answer"],
             "standalone_question": result["standalone_question"]},
        ])
        outputs.append(result)
    assert all("What is the 2023 population of Ségou commune?" in p for p in prompts)
    for level, result in zip(("commune", "cercle"), outputs[-2:]):
        evidence = json.loads(result["evidence"][0]["content"])["result"]
        assert {row["unit_type"] for row in evidence["rows"]} == {level}
        comparison = evidence["relative_difference"]
        assert comparison["percent"] == (comparison["larger_population"] -
                                          comparison["smaller_population"]) * 100 / comparison["smaller_population"]
        assert "× 100" in result["answer"]


def test_different_national_water_definitions_stay_separate():
    from country_indicators import indicator_answer

    result = indicator_answer("What percentage of people in Mali use basic drinking water? "
                              "Distinguish this from safely managed drinking water.")
    assert result["evidence"][0]["record_id"] == "SH.H2O.BASW.ZS"
    assert result["evidence"][1]["source_family"] == "WHO/UNICEF Joint Monitoring Programme"
    assert result["answer"].count("**86.363**") == 1


def test_reported_active_sector_retrieval_filters_before_limit():
    from project_learning_sources import retrieve_project_learning

    for question in (
        "Find active World Bank education projects recorded for Mali.",
        "Liste des projets d’éducation de la Banque mondiale déclarés actifs au Mali.",
    ):
        projects = [row["project_record"] for row in retrieve_project_learning(question)
                    if row.get("project_record")]
        assert projects
        assert all(row["status"] == "Active" and "Education" in row["title"] for row in projects)


def test_single_sector_synthesis_carries_typed_relationships_without_neighbor_rows():
    from synthesis_context import prepare, serialize

    source = {
        "evidence_id": "E01", "source_type": "fongim_structured",
        "section": "Sector-organization relationships",
        "content": "Nutrition: Nutrition actor; Education: Education actor",
        "relationship_rows": [
            {"sector": "Nutrition", "organization": "Nutrition actor",
             "relationship": "associated with the same project", "unique_projects": 1},
            {"sector": "Education", "organization": "Education actor",
             "relationship": "associated with the same project", "unique_projects": 2},
        ],
    }
    view, _ = prepare([source], "Which nutrition actors are recorded?", "balanced")
    prompt = serialize(view)
    assert "Nutrition actor" in prompt
    assert "Education actor" not in prompt
    assert "associated with the same project" in prompt
    assert len(source["relationship_rows"]) == 2
