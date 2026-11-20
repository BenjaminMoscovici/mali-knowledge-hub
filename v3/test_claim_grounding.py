"""Regressions for normal-answer claim review and partial recovery."""

import json
from types import SimpleNamespace

from claim_grounding import ground_answer
from synthesis_context import serialize


def test_quantity_with_wrong_denominator_is_repaired_and_unrelated_claim_is_removed():
    evidence = [
        {"evidence_id": "E01", "source_type": "registry_record", "document_title": "Survey",
         "content": "In 2024, 42 percent of surveyed households in River District reported access."},
        {"evidence_id": "E02", "source_type": "registry_record", "document_title": "Activity report",
         "content": "Two inspections were recorded for River District."},
    ]
    draft = ("42 percent of the population had access in 2024 [E01].\n"
             "Two inspections were recorded [E02].\n"
             "The inspections caused households to gain access [E01, E02].")
    corrected = "In 2024, 42 percent of surveyed households in River District reported access [E01]."
    responses = iter([
        {"findings": [
            {"line": 0, "verdict": "unsupported", "replacement": corrected},
            {"line": 1, "verdict": "supported", "replacement": ""},
            {"line": 2, "verdict": "unsupported", "replacement": ""},
        ]},
        {"findings": [{"line": 0, "verdict": "supported", "replacement": ""}]},
    ])
    calls = []

    def provider(**request):
        calls.append(json.loads(request["input"]))
        return SimpleNamespace(output_text=json.dumps(next(responses)))

    answer, audit = ground_answer(provider, "fixture", "What did the survey and inspections show?",
                                  draft, evidence, serialize(evidence), [], "English")
    assert len(calls) == 2
    assert calls[-1]["lines_to_review"] == {"0": corrected}
    assert "[E01] SOURCE" in calls[-1]["citable_evidence"]
    assert "[E02] SOURCE" not in calls[-1]["citable_evidence"]
    assert corrected in answer and draft.splitlines()[1] in answer
    assert "caused" not in answer and "of the population" not in answer
    assert audit["revised_lines"] == audit["removed_lines"] == 1


def test_failed_recheck_does_not_replace_a_valid_finding_or_keep_the_bad_line():
    evidence = [{"evidence_id": "E01", "source_type": "registry_record",
                 "content": "A grant was committed to Regional Office, with no delivery reported."}]
    outputs = iter([
        '{"findings":[{"line":0,"verdict":"supported","replacement":""},'
        '{"line":1,"verdict":"unsupported","replacement":"A service was delivered [E01]."}]}',
        '{"findings":[{"line":1,"verdict":"unsupported","replacement":""}]}',
    ])
    answer, audit = ground_answer(
        lambda **kwargs: SimpleNamespace(output_text=next(outputs)), "fixture", "What happened?",
        "A grant was committed [E01].\nDelivery was confirmed [E01].", evidence,
        serialize(evidence), [], "English",
    )
    assert "grant was committed" in answer and "confirmed" not in answer and "delivered" not in answer
    assert audit["revised_lines"] == 0 and audit["removed_lines"] == 1


def test_incomplete_audit_is_explicit_and_leaves_the_prior_guards_in_charge():
    answer, audit = ground_answer(
        lambda **kwargs: SimpleNamespace(output_text='{"findings":[]}'),
        "fixture", "What was recorded?", "An inspection was recorded [E01].",
        [{"evidence_id": "E01"}], "inspection", [], "English",
    )
    assert answer == "An inspection was recorded [E01]."
    assert audit == {"status": "unavailable"}


def test_wrapped_claim_is_reviewed_with_its_citation_and_keeps_original_layout():
    evidence = [{"evidence_id": "E01", "source_type": "registry_record",
                 "content": "The survey counted 42 households."}]
    calls = []

    def provider(**kwargs):
        payload = json.loads(kwargs["input"])
        calls.append(payload)
        return SimpleNamespace(output_text=json.dumps({"findings": [
            {"line": int(i), "verdict": "supported", "replacement": ""}
            for i in payload["lines_to_review"]
        ]}))

    draft = "The survey counted\n42 households.\n[E01]"
    result, audit = ground_answer(provider, "fixture", "What was counted?", draft, evidence,
                                  serialize(evidence), [], "English")
    assert calls[0]["lines_to_review"] == {"0": "The survey counted 42 households. [E01]"}
    assert result == draft and audit["removed_lines"] == 0
    result, audit = ground_answer(provider, "fixture", "What was counted?", draft.replace("42", "99"),
                                  evidence, serialize(evidence), [], "English")
    assert "99" not in result and "[E01]" not in result and audit["removed_lines"] == 1


def test_table_drops_unsupported_rows_without_lending_adjacent_citations():
    evidence = [{"evidence_id": "E01", "source_type": "registry_record",
                 "content": "River District reported 42 households."}]
    draft = ("| District | Households |\n|---|---:|\n"
             "| River | 42 [E01] |\n| Lake | 70 |")

    def provider(**kwargs):
        lines = json.loads(kwargs["input"])["lines_to_review"]
        assert set(lines) == {"0", "2", "3"}
        assert "[E01]" in lines["2"] and "[E01]" not in lines["3"]
        return SimpleNamespace(output_text=json.dumps({"findings": [
            {"line": 0, "verdict": "nonmaterial", "replacement": ""},
            {"line": 2, "verdict": "supported", "replacement": ""},
            {"line": 3, "verdict": "unsupported", "replacement": ""},
        ]}))

    result, audit = ground_answer(provider, "fixture", "What was reported?", draft, evidence,
                                  serialize(evidence), [], "English")
    assert "|---|---:|\n| River | 42 [E01] |" in result
    assert "Lake" not in result and audit["removed_lines"] == 1
