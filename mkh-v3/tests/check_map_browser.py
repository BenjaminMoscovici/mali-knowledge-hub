"""Optional Chromium regression for a cross-release exhibit, CSV and printable brief.

Run with the V3 URL as the argument. The completed chat response is a replay of an
actual calculation. Geometry, frontend assets and file downloads use the running app.
Requires Playwright and a Chromium executable.
"""
import csv
import io
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge import Evidence, Knowledge


def check(origin):
    k = Knowledge()
    ledger = Evidence(k, False)
    activities, geo = "mli-ocha-3w-2026-q1", "mli-cod-ab"
    result = k.link_records(activities, geo, next(iter(k.source(activities)["entity_keys"])),
        "SELECT r_pcode AS code, COUNT(DISTINCT l_organization) AS organizations FROM linked "
        "WHERE l_sector='nutrition' GROUP BY r_pcode ORDER BY r_pcode", ledger)
    figure = ledger.present(result["id"], "map", "Nutrition presence by region", "code", "organizations")
    expected = {r["code"]:r["organizations"] for r in result["data"]["rows"]}
    with sync_playwright() as p:
        options = {"executable_path":shutil.which("chromium"), "args":["--no-sandbox"]}
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if proxy and urlsplit(origin).hostname not in {"localhost","127.0.0.1"}:
            target = urlsplit(proxy)
            config = {"server":f"{target.scheme}://{target.hostname}:{target.port}"}
            if target.username:
                config.update(username=target.username,password=target.password or "")
            options["proxy"] = config
        with p.chromium.launch(**options) as browser:
            page = browser.new_page(accept_downloads=True, ignore_https_errors=True)
            run = {"job_id":"test-render","conversation_id":"test-chat"}
            if urlsplit(origin).hostname in {"localhost","127.0.0.1"}:
                page.route("**/api/session", lambda route:route.fulfill(json={
                    "authenticated":False, "auth_enabled":False, "model_configured":True,"chat_enabled":True}))
            page.route("**/api/chat", lambda route:route.fulfill(status=202,json=run))
            page.route("**/api/jobs/test-render", lambda route:route.fulfill(json={"event":{
                "type":"answer","text":"Verified result [["+result["id"]+"]]", "evidence":[result],
                "conversation_id":"test-chat","artifacts":[figure]}}))
            page.goto(origin,wait_until="domcontentloaded",timeout=60000)
            page.get_by_text("Guest chat · Temporary conversation", exact=True).wait_for(timeout=20000)
            page.get_by_label("Ask a question about Mali").fill("Show the map")
            page.get_by_role("button", name="Send question").click()
            page.locator('.exhibit canvas[height="466"]').wait_for(timeout=20000)
            with page.expect_download() as downloaded:
                page.locator(".exhibit").get_by_role("button",name="Download CSV").click()
            rows = csv.DictReader(io.StringIO(Path(downloaded.value.path()).read_text(encoding="utf-8-sig")))
            assert {r["code"]:int(r["organizations"]) for r in rows} == expected
            with page.expect_download() as downloaded:
                page.get_by_role("button",name="Download brief").click()
            assert "data:image/png;base64," in Path(downloaded.value.path()).read_text()
            print(f"Rendered joined map, downloaded CSV for {len(expected)} regions and exported map in printable brief.")


if __name__ == "__main__":
    check(sys.argv[1])
