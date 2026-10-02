"""Deterministic benchmark summary; complements manual evidence validation."""

import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = {"government_documents": "government_docs", "humanitarian_document": "hnrp_docs",
       "hdx_hapi": "hapi", "fongim": "fongim"}


def read_jsonl(path):
    return {entry["case_id"]: entry for entry in
            map(json.loads, path.read_text().splitlines())
            if entry.get("total_seconds") is not None}


def score(entry, case):
    expected = {MAP[source] for source in case["sources"]}
    selected = {key for key, value in (entry.get("source_plan") or {}).items() if value}
    answer = entry.get("answer") or ""
    citations = entry.get("citation_audit")
    if citations is None:
        citation_ok = bool(re.search(r"\[E\d+", answer)) if expected else True
    else:
        citation_ok = citations["valid"]
    checks = {"required_sources": expected <= selected,
              "citations": citation_ok,
              "no_exception": not entry.get("exceptions") and entry.get("total_seconds") is not None}
    if case["id"] == "A01":
        checks["clarification"] = bool(re.search(r"which place|quel lieu|quelle région", answer, re.I))
        checks["no_unrequested_retrieval"] = not selected
    if case["id"] == "I01":
        checks["impact_caution"] = bool(re.search(r"does not establish|ne permet pas|cannot establish", answer, re.I))
    return checks


def main():
    cases = {case["id"]: case for case in json.loads((ROOT / "benchmark_v1_frozen.json").read_text())["cases"]}
    baseline = read_jsonl(ROOT / "results" / "baseline_batch.jsonl")
    baseline["D01"] = json.loads((ROOT / "results" / "baseline_D01.json").read_text())
    candidate = read_jsonl(ROOT / "results" / "v1_batch.jsonl")
    paired = sorted(set(baseline) & set(candidate))
    report = {"cases": {}, "paired_count": len(paired)}
    for case_id in paired:
        base, new = baseline[case_id], candidate[case_id]
        report["cases"][case_id] = {
            "baseline_seconds": base["total_seconds"],
            "v1_seconds": new["total_seconds"],
            "baseline_checks": score(base, cases[case_id]),
            "v1_checks": score(new, cases[case_id]),
            "v1_estimated_openai_usd": (new.get("api_usage") or {}).get("estimated_usd"),
        }
    report["baseline_median_seconds"] = statistics.median(baseline[c]["total_seconds"] for c in paired)
    report["v1_median_seconds"] = statistics.median(candidate[c]["total_seconds"] for c in paired)
    report["v1_citation_checks_passed"] = sum(report["cases"][c]["v1_checks"]["citations"] for c in paired)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
