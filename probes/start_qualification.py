"""Launch a pinned, local, guest-only MKH benchmark endpoint after access checks."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "v3"
REQUIRED = ("MKH_QUALIFICATION_CORPUS_DSN", "MKH_QUALIFICATION_MODEL_KEY",
            "HDX_HAPI_APP_IDENTIFIER")
FORBIDDEN = ("SUPABASE_SECRET_KEY", "OPENAI_API_KEY")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=17821)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    missing = [key for key in REQUIRED if not os.environ.get(key)]
    forbidden = [key for key in FORBIDDEN if os.environ.get(key)]
    if missing or forbidden:
        sys.exit("Qualification preflight blocked. Missing: " + ", ".join(missing)
                 + ". Clear ordinary runtime credentials: " + ", ".join(forbidden) + ".")

    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT).strip():
        sys.exit("The serving checkout has tracked changes. Commit or use a clean worktree.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    sys.path.insert(0, str(APP))
    from qualification_corpus import from_environment
    from openai import OpenAI

    try:
        from_environment().verify_role()
        with OpenAI(api_key=os.environ["MKH_QUALIFICATION_MODEL_KEY"], timeout=10, max_retries=0) as client:
            for model in ("gpt-5.6-luna", "gpt-5-mini", "text-embedding-3-small"):
                client.models.retrieve(model)
    except Exception as error:
        sys.exit(f"Qualification preflight failed ({type(error).__name__}). "
                 "Check the dedicated login, visible corpus rows, network and approved model access.")

    print(f"Qualification preflight passed for {commit}", flush=True)
    if not args.preflight_only:
        env = os.environ.copy()
        env.update(MKH_READ_ONLY_QUALIFICATION="1",
                   MKH_PUBLIC_ORIGIN=f"http://127.0.0.1:{args.port}", RENDER_GIT_COMMIT=commit)
        subprocess.run([sys.executable, "-m", "uvicorn", "web_api:app", "--host", "127.0.0.1",
                        "--port", str(args.port)], cwd=APP, env=env, check=True)


if __name__ == "__main__":
    main()
