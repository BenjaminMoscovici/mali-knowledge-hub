from starlette.testclient import TestClient

import web_api


def test_unconfigured_preview_has_commit_and_blocks_access_and_publication(monkeypatch):
    monkeypatch.setenv("MKH_HOSTED_PREVIEW", "1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "fixture-commit")
    monkeypatch.delenv("MKH_QUALIFICATION_MODEL_KEY", raising=False)
    def forbidden():
        raise AssertionError("A preview cannot publish")
    monkeypatch.setattr(web_api, "publish_snapshot_logged", forbidden)
    with TestClient(web_api.app) as client:
        assert client.get("/api/health").json() == {"status": "setup_pending", "hub_commit": "fixture-commit"}
        assert client.get("/").status_code == 503
        assert client.post("/api/chat", json={"question": "Hello"}).status_code == 503


def test_ready_preview_opens_ordinary_guest_chat_without_credentials(monkeypatch):
    origin = "https://preview.example.org"
    for key, value in {
        "MKH_HOSTED_PREVIEW": "1", "MKH_READ_ONLY_QUALIFICATION": "1",
        "MKH_QUALIFICATION_CORPUS_DSN": "fixture", "MKH_QUALIFICATION_MODEL_KEY": "fixture",
        "HDX_HAPI_APP_IDENTIFIER": "fixture",
        "RENDER_EXTERNAL_URL": origin,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.setattr(web_api, "preview_preflight", lambda: None)
    with TestClient(web_api.app, base_url=origin) as client:
        assert client.get("/api/health").json()["status"] == "ready"
        landing = client.get("/")
        assert landing.status_code == 200
        assert 'id="prompt"' in landing.text
        assert "set-cookie" not in landing.headers
        headers = {"Origin": origin}
        assert client.post("/api/auth/signup", json={}, headers=headers).status_code == 403
        assert client.post("/api/chat", json={"question": "Hello"}, headers=headers).json()["saved"] is False
