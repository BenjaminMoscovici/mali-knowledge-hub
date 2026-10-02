"""Summarize the frozen V1 benchmark from recorded final candidate runs."""

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
MAP = {"government_documents": "government_docs", "humanitarian_document": "hnrp_docs",
       "hdx_hapi": "hapi", "fongim": "fongim"}


def entries(name):
    path = RESULTS / name
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    cases = json.loads((ROOT / "benchmark_v1_frozen.json").read_text())["cases"]
    baseline = {x["case_id"]: x for x in entries("baseline_batch.jsonl")}
    baseline["D01"] = json.loads((RESULTS / "baseline_D01.json").read_text())
    candidate = {}
    for name in ("v1_batch.jsonl", "v1_balanced_batch.jsonl",
                 "v1_balanced_heldout.jsonl"):
        candidate.update({x["case_id"]: x for x in entries(name)
                          if x.get("total_seconds") is not None})
    report = {"case_count": len(cases), "development_count": 0, "heldout_count": 0,
              "cases": {}, "baseline_paired": {}}
    for case in cases:
        case_id = case["id"]
        item = candidate[case_id]
        expected = {MAP[name] for name in case["sources"]}
        selected = {name for name, flag in (item["source_plan"] or {}).items() if flag}
        check = {
            "split": case["split"], "seconds": item["total_seconds"],
            "required_source_families_selected": expected <= selected,
            "citation_ids_valid": item["citation_audit"]["valid"],
            "evidence_count": len(item["evidence"] or []),
            "estimated_openai_usd": item["api_usage"]["estimated_usd"],
            "openai_calls": item["api_usage"]["call_count"],
            "errors": item.get("exceptions") or item.get("error_debug"),
        }
        report["cases"][case_id] = check
        report[case["split"] + "_count"] += 1
        if case_id in baseline:
            report["baseline_paired"][case_id] = {
                "baseline_seconds": baseline[case_id]["total_seconds"],
                "v1_seconds": item["total_seconds"],
            }
    paired = report["baseline_paired"]
    report["baseline_paired_median_seconds"] = statistics.median(v["baseline_seconds"] for v in paired.values())
    report["v1_paired_median_seconds"] = statistics.median(v["v1_seconds"] for v in paired.values())
    report["candidate_required_sources_passed"] = sum(x["required_source_families_selected"] for x in report["cases"].values())
    report["candidate_citation_ids_passed"] = sum(x["citation_ids_valid"] for x in report["cases"].values())
    report["estimated_openai_usd_total"] = round(sum(x["estimated_openai_usd"] for x in report["cases"].values()), 6)
    (RESULTS / "v1_milestone_summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "baseline_paired")}, indent=2))


if __name__ == "__main__":
    main()
