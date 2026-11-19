import json

import pytest

from paired_review import load_attempt, prepare


def test_pairing_blinds_builds_retains_failures_and_checks_question_mode_and_commit(tmp_path):
    benchmark = tmp_path / "cases.json"
    benchmark.write_text(json.dumps({"cases": [{"id": "TASK1", "question": "A work task?"}]}))
    baseline, candidate, output = [tmp_path / dirname for dirname in ("before", "after", "review")]
    baseline.mkdir()
    candidate.mkdir()
    (baseline / "TASK1.json").write_text(json.dumps({
        "status": 200, "wall_s": 2, "response": {
            "answer": "A cited answer [E01].", "evidence": [{"evidence_id": "E01"}],
            "metrics": {"hub_commit": "before", "depth": "balanced", "estimated_usd": 0.001,
                        "unpriced_calls": 0},
        },
    }))
    path = candidate / "TASK1.json"
    path.write_text(json.dumps({
        "status": None, "wall_s": 65, "request_payload": {
            "question": "A work task?", "analysis_mode": "balanced",
        },
    }))
    prepare(benchmark, ["TASK1"], baseline, candidate, "before", "after", output)
    pair = json.loads((output / "review.json").read_text())["pairs"][0]
    assert {pair[label]["ok"] for label in ("A", "B")} == {True, False}
    assert not any("build" in item for item in (pair["A"], pair["B"]))
    assert "A cited answer" in {pair[label]["answer"][:14] for label in ("A", "B")}
    summary = json.loads((output / "review-key.json").read_text())["measurements"]
    assert summary["candidate"]["median_wall_seconds_including_failures"] == 65
    assert summary["candidate"]["median_reported_model_usd"] is None
    with pytest.raises(ValueError, match="pinned build"):
        load_attempt(baseline, "TASK1", "A work task?", "balanced", "other")
    with pytest.raises(ValueError, match="paired protocol"):
        load_attempt(candidate, "TASK1", "A work task?", "quick", "after")
