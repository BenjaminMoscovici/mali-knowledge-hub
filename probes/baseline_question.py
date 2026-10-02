"""Run one frozen benchmark question through the unchanged v0.3 Streamlit app."""

import getpass
import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Quels sont les grands axes de la SNEDD 2024–2033 ?"


def main():
    config = json.loads(getpass.getpass("Four MKH credentials as JSON (hidden): "))
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY",
                 "HDX_HAPI_APP_IDENTIFIER"):
        os.environ[name] = config[name]
    app_path = ROOT / "baseline" / "v0.3" / "app.py"
    test = AppTest.from_file(str(app_path), default_timeout=300).run()
    if test.exception:
        print(json.dumps({"startup_exceptions": [e.message for e in test.exception]}))
        return
    test.text_area[0].input(QUESTION).run()
    test.button(key="kh_landing_submit").click().run()
    messages = test.session_state["kh_messages"]
    last = messages[-1] if messages else {}
    result = last.get("result") or {}
    output = {
        "case_id": "D01", "question": QUESTION,
        "startup_exceptions": [e.message for e in test.exception],
        "answer": last.get("content"),
        "total_seconds": result.get("total_seconds"),
        "research_seconds": result.get("research_seconds"),
        "synthesis_seconds": result.get("synthesis_seconds"),
        "family_counts": result.get("family_counts"),
        "source_plan": result.get("source_plan"),
        "evidence_count": len(result.get("evidence") or []),
        "evidence_ids": [e.get("evidence_id") for e in result.get("evidence") or []],
    }
    dest = ROOT / "results" / "baseline_D01.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "answer"},
                     ensure_ascii=False))
    print("answer_chars", len(output["answer"] or ""))


if __name__ == "__main__":
    main()
