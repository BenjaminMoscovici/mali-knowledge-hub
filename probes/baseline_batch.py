"""Measure selected development cases against unchanged v0.3."""

import getpass
import json
import os
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
CASES = {item["id"]: item for item in json.loads(
    (ROOT / "benchmark_v1_frozen.json").read_text()) ["cases"]
    if item["split"] == "development"}


def main():
    ids = sys.argv[1:] or ["D04", "H01", "F01", "X01", "I01", "A01"]
    assert all(case_id in CASES for case_id in ids)
    config = json.loads(getpass.getpass("Four MKH credentials as JSON (hidden): "))
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY",
                 "HDX_HAPI_APP_IDENTIFIER"):
        os.environ[name] = config[name]
    dest = ROOT / "results" / "baseline_batch.jsonl"
    dest.parent.mkdir(exist_ok=True)
    for case_id in ids:
        case = CASES[case_id]
        print("START", case_id, flush=True)
        test = AppTest.from_file(
            str(ROOT / "baseline" / "v0.3" / "app.py"), default_timeout=360
        ).run()
        if not test.exception:
            test.text_area[0].input(case["question"]).run()
            test.button(key="kh_landing_submit").click().run()
        messages = test.session_state.get("kh_messages", [])
        last = messages[-1] if messages else {}
        result = last.get("result") or {}
        record = {
            "case_id": case_id, "question": case["question"],
            "exceptions": [e.message for e in test.exception],
            "answer": last.get("content"),
            "total_seconds": result.get("total_seconds"),
            "research_seconds": result.get("research_seconds"),
            "synthesis_seconds": result.get("synthesis_seconds"),
            "family_counts": result.get("family_counts"),
            "source_plan": result.get("source_plan"),
            "execution_trace": result.get("execution_trace"),
            "evidence": result.get("evidence"),
        }
        with dest.open("a") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        print("DONE", case_id, "seconds", record["total_seconds"],
              "families", record["family_counts"], "exceptions", len(record["exceptions"]),
              flush=True)


if __name__ == "__main__":
    main()
