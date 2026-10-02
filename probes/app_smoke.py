"""Run the unchanged v0.3 Streamlit app once in Streamlit AppTest, no query."""

import getpass
import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest


def main():
    config = json.loads(getpass.getpass("Four MKH credentials as JSON (hidden): "))
    names = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY",
             "HDX_HAPI_APP_IDENTIFIER")
    for name in names:
        os.environ[name] = config[name]
    path = Path(__file__).resolve().parents[1] / "baseline" / "v0.3" / "app.py"
    test = AppTest.from_file(str(path), default_timeout=90).run()
    print(json.dumps({"exceptions": [e.message for e in test.exception],
                      "titles": [t.value for t in test.title],
                      "chat_inputs": len(test.chat_input),
                      "buttons": [b.label for b in test.button]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
