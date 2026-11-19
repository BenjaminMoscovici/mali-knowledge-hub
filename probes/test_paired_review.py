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


def test_blinded_ratings_keep_unassessable_and_critical_counts_separate(tmp_path):
    import csv
    from paired_review import DIMENSIONS, summarize_ratings

    (tmp_path / "review.json").write_text(json.dumps({"pairs": [
        {"case_id": "K1", "A": {"answer_evidence_sha256": "a"}, "B": {"answer_evidence_sha256": "b"}},
    ]}))
    (tmp_path / "review-key.json").write_text(json.dumps({
        "order": {"K1": {"A": "candidate", "B": "baseline"}},
        "measurements": {"baseline": {}, "candidate": {}},
    }))
    ratings = tmp_path / "ratings.csv"
    with ratings.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("case_id", "label", "answer_evidence_sha256", *DIMENSIONS, "critical_error"))
        writer.writerow(("K1", "A", "a", "5", "4", "NA", "5", "4", "no"))
        writer.writerow(("K1", "B", "b", "3", "4", "4", "2", "5", "yes"))
    summary = summarize_ratings(tmp_path, ratings)
    assert summary["quality"]["factual_correctness"]["mean_change"] == 2
    assert summary["quality"]["completeness"]["assessable_pairs"] == 0
    assert summary["critical_errors"]["baseline"]["critical_errors"] == 1
    ratings.write_text(ratings.read_text().replace("K1,A,a", "K1,A,other"))
    with pytest.raises(ValueError, match="different answer"):
        summarize_ratings(tmp_path, ratings)
