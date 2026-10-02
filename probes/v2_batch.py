"""Run frozen V2 cases against the isolated V2 Streamlit candidate."""

import getpass
import json
import os
from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
CASES = {case["id"]: case for case in json.loads(
    (ROOT / "benchmark_v2_frozen.json").read_text())["cases"]}
CASES.update({case["id"]: case for case in json.loads(
    (ROOT / "benchmark_v1_frozen.json").read_text())["cases"]})


def main():
    ids = sys.argv[1:] or [c for c in CASES if c.startswith("J") and
                           CASES[c]["split"] == "development"]
    assert all(cid in CASES for cid in ids)
    config = json.loads(getpass.getpass("Four MKH credentials as JSON (hidden): "))
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY",
                 "HDX_HAPI_APP_IDENTIFIER"):
        os.environ[name] = config[name]
    if not os.environ["SUPABASE_URL"].startswith("https://hofoubbmepacdljeablj.supabase.co"):
        raise ValueError("Expected the verified GIZ Supabase project URL")
    filename = ("v2_v1_regression.jsonl" if all(not c.startswith("J") for c in ids)
                else "v2_heldout.jsonl" if all(CASES[c]["split"] == "heldout" for c in ids)
                else "v2_development.jsonl")
    dest = ROOT / "results" / filename
    for cid in ids:
        print("START", cid, flush=True)
        case = CASES[cid]
        test = AppTest.from_file(str(ROOT / "v2" / "app.py"), default_timeout=360).run()
        if not test.exception:
            test.text_area[0].input(case["question"]).run()
            test.button(key="kh_landing_submit").click().run()
        messages = test.session_state.get("kh_messages", [])
        last = messages[-1] if messages else {}
        result = last.get("result") or {}
        record = {
            "case_id": cid, "question": case["question"],
            "exceptions": [e.message for e in test.exception],
            "answer": last.get("content"), "error_debug": test.session_state.get("kh_last_error_debug"),
            "total_seconds": result.get("total_seconds"),
            "source_plan": result.get("source_plan"),
            "family_counts": result.get("family_counts"),
            "execution_trace": result.get("execution_trace"),
            "joined": result.get("joined"),
            "evidence": result.get("evidence"),
            "api_usage": result.get("api_usage"),
            "citation_audit": result.get("citation_audit"),
        }
        with dest.open("a") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        print("DONE", cid, "seconds", record["total_seconds"],
              "joins", len((record["joined"] or {}).get("relationships", [])),
              "exceptions", len(record["exceptions"]), flush=True)


if __name__ == "__main__":
    main()
