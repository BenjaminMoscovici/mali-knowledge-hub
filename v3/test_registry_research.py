"""Paired source qualification and unfamiliar release onboarding through guest chat."""
import gzip
import json

from starlette.testclient import TestClient

import registry_research
from web_api import app

ORIGIN = "https://mali-knowledge-hub.onrender.com"


def request(question):
    response = TestClient(app, base_url=ORIGIN).post(
        "/api/chat", json={"question": question}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["metrics"]["route"] == "registry_evidence"
    assert result["metrics"]["model_calls"] == result["metrics"]["external_research_calls"] == 0
    return result


def test_discovers_two_real_source_types_without_naming_providers():
    result = request(
        "Show evidence for Mali's humanitarian planning figures and humanitarian funding requirements in 2026"
    )
    assert "5100000" in result["answer"] and "135628821" in result["answer"]
    assert "No combined total is calculated" in result["answer"]
    assert {item["source_family"] for item in result["evidence"]} == {
        "OCHA HPC / HDX", "OCHA Financial Tracking System (FTS)"
    }
    assert all(item["reference_period_start"] == "2026-01-01" for item in result["evidence"])
    assert any(item["locator"].endswith("row 5") for item in result["evidence"])
    assert any(item["locator"].startswith("CSV line 54") for item in result["evidence"])


def test_exact_identifier_and_geographic_limits():
    plan = request("Show evidence from OCHA FTS for HMLI26 in 2026")
    assert len(plan["evidence"]) == 1
    assert "135628821" in plan["answer"] and "HMLI26" in plan["answer"]
    assert "Reported financing gap: USD 442,237,591" in plan["answer"]
    assert "calculated within this row" in plan["evidence"][0]["content"]
    missing = request("Show evidence from OCHA FTS for HMLI99 in 2026")
    assert missing["evidence"] == [] and "No matching evidence" in missing["answer"]
    local = request("Show evidence from global HPC HNO for Mopti cercle in 2026")
    assert local["evidence"] == [] and "national observations only" in local["answer"]


def test_pdf_locator_and_requested_period():
    result = request("Show evidence from the 2022 census report on population methodology")
    assert 11 in {item["page"] for item in result["evidence"]}
    assert all(item["locator"] == f'PDF page {item["page"]}' for item in result["evidence"])
    assert all(item["reference_period_start"] == "2022-01-01" for item in result["evidence"])
    missing = request("Show evidence from the RGPH5 preliminary report in 2025")
    assert not missing["evidence"]


def test_unfamiliar_packaged_source_is_discovered_from_metadata(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    spec = dict(adapter="packaged_records", package="fixture.json.gz", dataset_id="asset-facts",
                release_id="test-release", scope="Dara district", aliases=["water asset register"],
                topics=["water tanker logs"], fields={"quantity": "Volume in litres"})
    source = dict(source_name="District service log", provider="Audit fixture",
                  access_route="https://example.org/asset-facts", integration_status="integrated",
                  research=spec)
    registry.write_text(json.dumps([source]))
    with gzip.open(tmp_path / spec["package"], "wt") as archive:
        row = dict(id="record-3", release_id="test-release", dataset_id="asset-facts",
                   version="v1", locator="Sheet Dispatch row 3", payload={"quantity": 314159, "private_note": "excluded"},
                   reference_start="2025-01-01", reference_end="2025-12-31")
        json.dump({"records": [row, dict(row, id="other-release", release_id="stale")]}, archive)
    monkeypatch.setattr(registry_research, "REGISTRY", registry)
    result = request("Show evidence on water tanker logs in 2025")
    assert "314159" in result["answer"] and "excluded" not in result["answer"]
    assert [item["record_id"] for item in result["evidence"]] == ["record-3"]
    assert result["evidence"][0]["locator"] == "Sheet Dispatch row 3"


def test_real_research_ledger_integrates_the_new_document_and_keeps_legacy_evidence(monkeypatch):
    from test_issue1_research import research_function

    worker = research_function(monkeypatch, lambda geography: {"raw_count": 0, "evidence": []})
    outcome = worker("Compare the 2022 census report with humanitarian needs data in 2026")
    ledger = outcome["ledger"]
    assert any(item["source_type"] == "registry_document" and item["page"] for item in ledger)
    assert any(item["source_type"] == "food_security_classification" for item in ledger)
    assert outcome["execution_trace"]["sources"]["registry"]["status"] == "SUCCESS_WITH_RESULTS"


def test_evidence_followup_preserves_exact_plan_and_rechecks_year():
    previous = "Show evidence from OCHA FTS for HMLI26 in 2026"
    client = TestClient(app, base_url=ORIGIN)
    result = client.post("/api/chat", headers={"Origin": ORIGIN}, json={
        "question": "And in 2025?",
        "prior_messages": [
            {"role": "user", "content": previous},
            {"role": "assistant", "content": "Invented 2025 funding: 999999 [E99]"},
        ],
    }).json()
    assert result["standalone_question"] == previous.replace("in 2026", "in 2025")
    assert result["metrics"]["context_resolution_method"] == "registry_evidence_reference_year"
    assert result["metrics"]["model_calls"] == 0
    assert result["evidence"] == [] and "No matching evidence" in result["answer"]


def test_valid_id_alone_does_not_verify_generated_registry_quantities():
    from citations import unsupported_registry_quantities, verify

    evidence = [
        {"evidence_id": "E01", "source_type": "registry_record",
         "content": "Reported people in need: 5100000 people", "reference_period_start": "2026-01-01"},
        {"evidence_id": "E02", "source_type": "registry_record",
         "content": "Reported funding: USD 135628821.0"},
    ]
    claim = "The 2026 plan records 5.1 million people in need [E01] and USD 135,628,821 [E02]."
    assert verify(claim, evidence)[1]["valid"]
    assert not unsupported_registry_quantities(claim, evidence)
    assert unsupported_registry_quantities("The funding was USD −135,628,821 [E02].", evidence)
    swapped = claim.replace("[E01]", "[E02]")
    assert verify(swapped, evidence)[1]["valid"]
    assert unsupported_registry_quantities(swapped, evidence) == [
        {"cited_ids": ["E02"], "unsupported_quantity_count": 2}
    ]
