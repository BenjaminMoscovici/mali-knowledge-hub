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
