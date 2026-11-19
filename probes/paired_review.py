"""Prepare a private, blinded review of two pinned MKH guest-chat captures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


DIMENSIONS = (
    "factual_correctness", "citation_support", "completeness",
    "professional_usefulness", "natural_communication",
)


def load_attempt(root, case_id, question, mode, commit):
    native = root / "raw" / f"{case_id}--0.json"
    path = native if native.exists() else root / f"{case_id}.json"
    capture = json.loads(path.read_text())
    payload = capture.get("request_payload")
    if payload and (payload.get("question") != question or payload.get("analysis_mode") != mode):
        raise ValueError(f"{case_id}: the recorded request differs from the paired protocol")
    status = capture.get("http_status", capture.get("status"))
    response = capture.get("response") or {}
    metrics = response.get("metrics") or {}
    ok = capture.get("ok", status == 200)
    if ok and metrics.get("hub_commit") != commit:
        raise ValueError(f"{case_id}: successful response does not identify the pinned build")
    if ok and metrics.get("depth") != mode:
        raise ValueError(f"{case_id}: successful response used a different analysis mode")
    evidence = response.get("evidence") or []
    answer = response.get("answer") or ""
    digest = hashlib.sha256(json.dumps([answer, evidence], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {
        "ok": ok,
        "answer": answer,
        "evidence": evidence,
        "answer_evidence_sha256": digest,
        "wall_seconds": capture.get("wall_s", capture.get("client_seconds")),
        "reported_model_usd": metrics.get("estimated_usd"),
        "unpriced_model_calls": metrics.get("unpriced_calls"),
        "request_payload_verified": bool(payload),
    }


def summarize(attempts):
    success = [item for item in attempts if item["ok"]]
    times = [item["wall_seconds"] for item in attempts if item["wall_seconds"] is not None]
    # A missing receipt or a call with unknown pricing cannot count as zero.
    costs = [item["reported_model_usd"] for item in success
             if item["reported_model_usd"] is not None and item["unpriced_model_calls"] == 0]
    return {
        "attempted": len(attempts), "answered": len(success),
        "median_wall_seconds_including_failures": median(times) if times else None,
        "timed_attempts": len(times), "fully_priced_successes": len(costs),
        "median_reported_model_usd": median(costs) if costs else None,
        "request_payloads_verified": sum(item["request_payload_verified"] for item in attempts),
    }


def prepare(benchmark, ids, baseline, candidate, baseline_commit, candidate_commit, output):
    cases = {case["id"]: case for case in json.loads(benchmark.read_text())["cases"]}
    if not ids or len(set(ids)) != len(ids) or baseline_commit == candidate_commit:
        raise ValueError("Use unique case IDs and two different pinned builds")
    if output.exists():
        raise FileExistsError("Use a fresh private output directory")
    pairs, key, measurements = [], {}, {"baseline": [], "candidate": []}
    for case_id in ids:
        case = cases[case_id]
        # The existing 32-case reference used Balanced for every turn.
        mode = "balanced"
        if case.get("prior_messages"):
            raise ValueError("Use the conversation evaluator for dependent multi-turn cases")
        attempts = {
            "baseline": load_attempt(baseline, case_id, case["question"], mode, baseline_commit),
            "candidate": load_attempt(candidate, case_id, case["question"], mode, candidate_commit),
        }
        swap = hashlib.sha256(f"{candidate_commit}:{case_id}".encode()).digest()[0] % 2
        order = ("candidate", "baseline") if swap else ("baseline", "candidate")
        key[case_id] = dict(zip(("A", "B"), order))
        pair = {"case_id": case_id, "question": case["question"],
                "expected_behavior": case.get("expected_behavior", [])}
        for label, build in key[case_id].items():
            attempt = attempts[build]
            measurements[build].append(attempt)
            pair[label] = {field: attempt[field] for field in ("ok", "answer", "evidence", "answer_evidence_sha256")}
        pairs.append(pair)
    output.mkdir(mode=0o700, parents=True)
    (output / "review.json").write_text(json.dumps({
        "guidance": ("Score each dimension 1–5, or NA if unassessable. Read the actual cited "
                     "evidence; record any critical factual or scope error. Reserve 5 for an "
                     "answer usable as written for the task. Missing evidence is not a verified fact."),
        "pairs": pairs,
    }, indent=2, ensure_ascii=False))
    (output / "review-key.json").write_text(json.dumps({
        "builds": {"baseline": baseline_commit, "candidate": candidate_commit},
        "order": key, "measurements": {build: summarize(rows) for build, rows in measurements.items()},
    }, indent=2))
    with (output / "ratings.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("case_id", "label", "answer_evidence_sha256", *DIMENSIONS, "critical_error", "notes"))
        for pair in pairs:
            for label in ("A", "B"):
                writer.writerow((pair["case_id"], label, pair[label]["answer_evidence_sha256"],
                                 *("" for _ in range(len(DIMENSIONS) + 2))))




def summarize_ratings(review_directory, ratings):
    """Join completed ratings to the exact answer evidence and show paired deltas."""
    review = json.loads((review_directory / "review.json").read_text())
    key = json.loads((review_directory / "review-key.json").read_text())
    expected = {(pair["case_id"], label): pair[label]
                for pair in review["pairs"] for label in ("A", "B")}
    by_case = {}
    seen = set()
    with ratings.open(newline="") as stream:
        for row in csv.DictReader(stream):
            identity = (row["case_id"], row["label"])
            if identity in seen or identity not in expected:
                raise ValueError("Unknown or duplicate paired rating")
            seen.add(identity)
            if row["answer_evidence_sha256"] != expected[identity]["answer_evidence_sha256"]:
                raise ValueError("Rating is bound to a different answer or evidence ledger")
            if any(row[dimension] not in {"1", "2", "3", "4", "5", "NA"} for dimension in DIMENSIONS):
                raise ValueError("Use scores 1–5 or NA for every rating dimension")
            if row["critical_error"] not in {"yes", "no", "NA"}:
                raise ValueError("Mark each critical error as yes, no or NA")
            build = key["order"][row["case_id"]][row["label"]]
            by_case.setdefault(row["case_id"], {})[build] = row
    if set(expected) != seen:
        raise ValueError("Both ratings are required for every case")

    quality = {}
    for dimension in DIMENSIONS:
        paired = [(int(row["baseline"][dimension]), int(row["candidate"][dimension]))
                  for row in by_case.values()
                  if all(row[build][dimension] != "NA" for build in ("baseline", "candidate"))]
        quality[dimension] = {
            "assessable_pairs": len(paired),
            "baseline_mean": mean(a for a, _ in paired) if paired else None,
            "candidate_mean": mean(b for _, b in paired) if paired else None,
            "mean_change": mean(b - a for a, b in paired) if paired else None,
            "candidate_better": sum(b > a for a, b in paired),
            "candidate_worse": sum(b < a for a, b in paired),
        }
    errors = {build: {
        "critical_errors": sum(row[build]["critical_error"] == "yes" for row in by_case.values()),
        "unassessed": sum(row[build]["critical_error"] == "NA" for row in by_case.values()),
    } for build in ("baseline", "candidate")}
    return {"reviewed_pairs": len(by_case), "quality": quality, "critical_errors": errors,
            "measurements": key["measurements"]}

def capture_balanced(benchmark, ids, base, commit, output):
    cases = {case["id"]: case for case in json.loads(benchmark.read_text())["cases"]}
    if not ids or len(set(ids)) != len(ids) or any(cases[cid].get("prior_messages") for cid in ids):
        raise ValueError("Capture requires unique standalone case IDs")
    output.mkdir(mode=0o700, parents=True)
    base = base.rstrip("/")

    def capture(case_id):
        payload = {"question": cases[case_id]["question"], "analysis_mode": "balanced", "prior_messages": []}
        request = Request(base + "/api/chat", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "Origin": base})
        started = time.monotonic()
        try:
            with urlopen(request, timeout=65) as result:
                response = json.load(result)
                row = {"status": result.status, "response": response}
        except (URLError, TimeoutError, ValueError) as exc:
            row = {"status": getattr(exc, "code", None), "error": type(exc).__name__}
        row.update(case=case_id, request_payload=payload, wall_s=time.monotonic() - started)
        (output / f"{case_id}.json").write_text(json.dumps(row, ensure_ascii=False))
        if row.get("status") == 200 and (row["response"].get("metrics") or {}).get("hub_commit") != commit:
            raise ValueError(f"{case_id}: endpoint did not return the pinned build")

    # Match the captured V4 reference. Every attempted failure remains recorded.
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(capture, ids))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ids")
    parser.add_argument("--candidate-commit")
    parser.add_argument("--capture-base", help="Capture a new candidate run at this isolated service URL")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--baseline-commit")
    parser.add_argument("--ratings", type=Path, help="Summarize a completed blinded review")
    args = parser.parse_args()
    if args.ratings:
        print(json.dumps(summarize_ratings(args.output, args.ratings), indent=2))
        raise SystemExit(0)
    if not args.benchmark or not args.ids or not args.candidate_commit:
        parser.error("Capture and preparation require --benchmark, --ids and --candidate-commit")
    ids = args.ids.split(",")
    if args.capture_base:
        capture_balanced(args.benchmark, ids, args.capture_base, args.candidate_commit, args.output)
    elif args.baseline and args.candidate and args.baseline_commit:
        prepare(args.benchmark, ids, args.baseline, args.candidate,
                args.baseline_commit, args.candidate_commit, args.output)
    else:
        parser.error("Specify --capture-base, or --baseline, --candidate and --baseline-commit")
