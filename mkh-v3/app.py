"""The isolated MKH V3 web application."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from companion import Companion, CompanionError, MODES
from jobs import ResearchJobs
from publication import Publications, extract, preview as source_preview, suggest
from knowledge import Evidence, Knowledge, KnowledgeError, SOURCE_ID, json_text
from live_preview_check import requested as preview_check_requested, run as run_preview_check
from state import (
    COOKIE, EMAIL_FLOW_COOKIE, GUEST_COOKIE, PASSWORD_COOKIE, TOP_TURNS,
    History, PreviewSessions, StateError, SupabaseState,
)

WEB = Path(__file__).resolve().parent / "web"
EMAIL = re.compile(r"[^@\s]{1,128}@[^@\s]{1,123}\.[^@\s]{1,30}\Z")
ERROR_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
MAX_BYTES = 22000


def settings(request):
    return request.app.state


def data_response(content, status=200):
    return JSONResponse(content, status_code=status, headers=ERROR_HEADERS)


def error(content, status=400):
    return data_response({"error": content}, status)


def public_origin(request):
    return settings(request).origin or str(request.base_url).rstrip("/")


def secured(request):
    return public_origin(request).startswith("https://")


def same_origin(request):
    return request.headers.get("origin") == public_origin(request)


async def request_json(request, limit=MAX_BYTES):
    if not same_origin(request):
        raise StateError("Open the preview directly to perform this action.")
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise StateError("Expected a JSON request.")
    buffer = bytearray()
    try:
        async for chunk in request.stream():
            if len(buffer) + len(chunk) > limit:
                raise StateError("The request exceeds the preview size limit.")
            buffer.extend(chunk)
        value = json.loads(buffer)
    except (UnicodeError, ValueError, ClientDisconnect) as failure:
        if isinstance(failure, StateError):
            raise
        raise StateError("The preview could not read this request.") from None
    if not isinstance(value, dict):
        raise StateError("Expected a JSON object.")
    return value


def selected_id(value):
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise StateError("Select a valid V3 conversation.") from None


async def account(request):
    state = settings(request)
    token = request.cookies.get(COOKIE)
    if not state.store or not token or len(token) > 6000:
        return None, None
    identifier = await state.store.user(token)
    return (token, identifier) if identifier else (None, None)


async def home(request):
    return FileResponse(WEB / "index.html", headers={
        "Cache-Control": "no-cache",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                   "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                                   "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    })


async def health(request):
    state = settings(request)
    return data_response({
        "status": "ok", "environment": "v3-preview", "commit": os.getenv("RENDER_GIT_COMMIT", "local"),
        "chat_configured": bool(state.companion), "public_web_research": state.web_enabled,
        "sources": len(state.knowledge.sources), "managed_sources": state.registry is not None,
    })


async def sources(request):
    query = request.query_params.get("q", "")[:350]
    k = settings(request).knowledge
    try:
        offset = int(request.query_params.get("offset", 0))
        paged = "offset" in request.query_params
        page = k.source_page(query, offset=offset, page_size=24 if paged else max(1, len(k.sources)))
        if not paged:
            page["sources"] = [{**k.describes(k.sources[item["id"]]), **item} for item in page["sources"]]
        return data_response(page)
    except ValueError:
        return error("Use a nonnegative source offset.")


async def source(request):
    k = settings(request).knowledge
    try:
        source_id = request.path_params["source_id"]
        item = k.inspect(source_id)
        if item["type"] == "document":
            item["evidence"] = k.search_documents("", source_id, Evidence(k, False))
        if item["type"] == "live":
            code = request.query_params.get("series")
            if code:
                start = int(request.query_params.get("start_year", "2020"))
                end = int(request.query_params.get("end_year", "2024"))
                item["evidence"] = [await k.live(source_id, code, start, end, Evidence(k, False),
                                                  settings(request).client)]
        return data_response(item)
    except KnowledgeError as failure:
        return error(str(failure), 400)
    except ValueError:
        return error("Use a valid year range.", 400)


async def geometry(request):
    try:
        src = settings(request).knowledge.source(request.path_params["source_id"])
        if not src.get("map_key"):
            return error("The selected release has no published display boundaries.", 404)
        return data_response({"key": src["map_key"], "release": src["release"], "geometries": src["geometries"],
                              "fingerprint": settings(request).knowledge.stamps[src["id"]],
                              "compatible_fingerprints": src.get("compatible_fingerprints", [])})
    except KnowledgeError as failure:
        return error(str(failure), 404)


async def memory(request):
    try:
        token, owner = await account(request)
        if not owner:
            return error("Sign in to manage personal memory.", 401)
        store = settings(request).store
        if request.method == "GET":
            return data_response(await store.memory(token))
        body = await request_json(request)
        notes, enabled = body.get("notes"), body.get("enabled")
        if not isinstance(notes, str) or len(notes) > 2000 or type(enabled) is not bool:
            return error("Use up to 2,000 characters for memory and select its enabled state.")
        await store.save_memory(token, enabled, notes.strip())
        return data_response({"enabled": enabled and bool(notes.strip()), "notes": notes.strip()})
    except StateError as failure:
        return error(str(failure), 400)


async def sync_catalogue(state):
    if state.registry is None:
        return
    current = await state.registry.refresh()
    if current is state.knowledge:
        return
    state.knowledge = current
    state.history = History(state.signing_key, current, state.web_enabled)
    if state.companion:
        state.companion = Companion(current, state.client, state.companion.api_key, state.web_enabled)


def answer_available(state, piece):
    return (all(state.knowledge.current_release(k, v) for k, v in piece.get("basis", {}).items())
            and all(Evidence(state.knowledge, state.web_enabled).allowed(e) for e in piece.get("evidence", []))
            and (not piece.get("web_used") or state.web_enabled))


class CatalogueBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(("/api/sources", "/api/conversations", "/api/chat", "/api/admin", "/api/health")):
            try:
                await sync_catalogue(scope["app"].state)
            except StateError:
                return await error("The published source catalogue could not be verified. Try again shortly.", 503)(scope, receive, send)
        return await self.app(scope, receive, send)


async def admin(request):
    state = settings(request)
    try:
        token, owner = await account(request)
        registry = state.registry
        if not owner or not registry or not await registry.editor(token):
            return error("A V3 source editor account is required.", 403)
        if request.method == "GET":
            detail = request.query_params.get("version")
            if detail:
                from publication import VERSIONS
                rows = await registry.rows(VERSIONS, "manifest", token, id="eq." + selected_id(detail), limit=1)
                if not rows:
                    return error("This source version is unavailable.", 404)
                return data_response(source_preview(rows[0]["manifest"]))
            inventory = await registry.inventory(token)
            return data_response(inventory)
        body = await request_json(request, 2150000)
        op = body.get("operation")
        if op == "change":
            key = body.get("source_id")
            if not isinstance(key, str) or not SOURCE_ID.fullmatch(key):
                return error("Choose a saved source.")
            version = selected_id(body["version_id"]) if body.get("version_id") else None
            expected = selected_id(body["expected"]) if body.get("expected") else None
            if body.get("status") == "published" and not version:
                return error("Select the version to publish.")
            await registry.change(token, key, body.get("status"), version, expected)
            await sync_catalogue(state)
            return data_response({"saved": True})
        if op not in {"inspect","suggest","draft"}:
            return error("Unknown source review action.")
        manifest = await extract(body)
        detail = source_preview(manifest)
        if op == "suggest":
            if not state.companion:
                return error("The model is unavailable.", 503)
            state.preview.reserve()
            await state.store.reserve(token)
            detail["suggestions"] = await suggest(state.companion, detail)
        if op == "draft":
            Knowledge(releases=[manifest])
            await registry.draft(token, manifest)
        return data_response(detail)
    except (KnowledgeError, StateError, TimeoutError) as failure:
        return error(str(failure) or "The source operation exceeded its time limit.", 400)


async def identify(request):
    state = settings(request)
    try:
        token, owner = await account(request)
        return data_response({
            "source_editor": bool(owner and state.registry and await state.registry.editor(token)),
            "authenticated": bool(owner), "auth_enabled": bool(state.store),
            "chat_enabled": bool(state.companion), "model_configured": bool(state.companion),
            "password_setup_pending": bool(request.cookies.get(PASSWORD_COOKIE)),
        })
    except StateError as failure:
        return error(str(failure), 503)


def set_cookie(response, request, name, value, age):
    response.set_cookie(name, value, max_age=age, httponly=True, secure=secured(request), samesite="lax")


def clear_cookie(response, request, name):
    response.delete_cookie(name, httponly=True, secure=secured(request), samesite="lax")


def password(body, minimum):
    value = body.get("password")
    if not isinstance(value, str) or not minimum <= len(value) <= 256:
        if minimum > 1:
            raise StateError("Choose a password containing 12 to 256 characters.")
        raise StateError("Enter your V3 password.")
    return value


def email_flow(request):
    operation, _, verifier = request.cookies.get(EMAIL_FLOW_COOKIE, "").partition(".")
    if operation not in {"signup", "recover"} or not re.fullmatch(r"[A-Za-z0-9_-]{43}", verifier):
        raise StateError("Request a fresh email link in this browser.")
    return operation, verifier


def start_account_session(response, request, token, age):
    set_cookie(response, request, COOKIE, token, age)
    for name in (GUEST_COOKIE, PASSWORD_COOKIE, EMAIL_FLOW_COOKIE):
        clear_cookie(response, request, name)
    return response


async def finish_email_flow(request, operation, verifier, code):
    token, age = await settings(request).store.exchange_code(code, verifier)
    if operation == "recover":
        response = RedirectResponse("/?auth=set-password", headers=ERROR_HEADERS)
        set_cookie(response, request, PASSWORD_COOKIE, token, min(age, 900))
        clear_cookie(response, request, EMAIL_FLOW_COOKIE)
        return response
    response = RedirectResponse("/?auth=ready", headers=ERROR_HEADERS)
    return start_account_session(response, request, token, age)


async def auth_callback(request):
    if not settings(request).store:
        return RedirectResponse("/?auth=expired", headers=ERROR_HEADERS)
    try:
        operation, verifier = email_flow(request)
        code = request.query_params.get("code", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{15,240}", code):
            raise StateError("Request a fresh email link in this browser.")
        return await finish_email_flow(request, operation, verifier, code)
    except StateError:
        return RedirectResponse("/?auth=expired", headers=ERROR_HEADERS)


async def auth(request):
    state = settings(request)
    if not state.store:
        return error("V3 sign-in is being configured.", 503)
    try:
        body = await request_json(request)
        operation = request.path_params["operation"]
        redirect = public_origin(request) + "/auth/callback"
        if operation == "set-password":
            token = request.cookies.get(PASSWORD_COOKIE, "")
            if not 1 <= len(token) <= 6000:
                return error("Open the password setup link from your V3 email.", 401)
            await state.store.set_password(token, password(body, 12))
            return start_account_session(data_response({"authenticated": True}), request, token, 3600)
        if operation not in {"sign-in", "signup", "recover"}:
            return error("Unknown sign-in operation.", 404)
        email = body.get("email", "")
        if not isinstance(email, str) or len(email) > 254 or not EMAIL.fullmatch(email.strip()):
            return error("Enter your V3 team email address.")
        email = email.strip().lower()
        if operation == "sign-in":
            token, age = await state.store.sign_in(email, password(body, 1))
            return start_account_session(data_response({"authenticated": True}), request, token, age)
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        initial_password = password(body, 12) if operation == "signup" else None
        await state.store.send_password_link(operation, email, initial_password, challenge, redirect)
        response = data_response({"sent": True})
        set_cookie(response, request, EMAIL_FLOW_COOKIE, operation + "." + verifier, 3600)
        clear_cookie(response, request, PASSWORD_COOKIE)
        return response
    except StateError as failure:
        return error(str(failure), 400)


async def signout(request):
    if not same_origin(request):
        return error("Open the preview directly to sign out.", 403)
    response = data_response({"authenticated": False})
    for name in (COOKIE, GUEST_COOKIE, PASSWORD_COOKIE, EMAIL_FLOW_COOKIE):
        clear_cookie(response, request, name)
    return response


async def conversations(request):
    try:
        token, owner = await account(request)
        state = settings(request)
        value = request.path_params.get("conversation_id")
        if not owner:
            if request.method == "GET" and value:
                guest_owner = request.cookies.get(GUEST_COOKIE)
                guest = state.preview.guests.get(guest_owner)
                chat_id = selected_id(value)
                if guest and time.monotonic() - guest.touched < state.preview.GUEST_IDLE_SECONDS and chat_id in guest.conversations:
                    guest.touched = time.monotonic()
                    turns = state.history.accessible(chat_id, guest_owner, guest.conversations[chat_id])
                    return data_response({"id": chat_id, "earlier_before": None, "turns": [
                        {k: v for k, v in turn.items() if k != "signature"} for turn in turns]})
                return error("This temporary conversation has expired.", 410)
            return error("Sign in to open your saved conversations.", 401)
        if value is None:
            return data_response({"conversations": await state.store.recent(token)})
        conversation_id = selected_id(value)
        if request.method == "DELETE":
            if not same_origin(request):
                return error("Open the preview directly to delete a conversation.", 403)
            await state.store.delete(token, conversation_id)
            return data_response({"deleted": True})
        row = await state.store.load(token, conversation_id)
        if not row:
            return error("This V3 conversation is unavailable.", 404)
        before = request.query_params.get("before")
        if before is not None:
            if not before.isdecimal() or len(before) > 9:
                return error("Invalid historical turn number.")
            page = await state.store.earlier_page(token, conversation_id, int(before))
            turns = [r["turn"] for r in page]
            first = page[0]["ordinal"] if page else 1
        else:
            turns = row["turns"]
            first = row["revision"] - len(turns) + 1
        history = state.history.accessible(conversation_id, owner, turns)
        return data_response({
            "id": conversation_id, "title": row["title"], "earlier_before": first if first > 1 else None,
            "turns": [{k: v for k, v in turn.items() if k != "signature"} for turn in history],
        })
    except StateError as failure:
        return error(str(failure), 503)


async def chat(request):
    state = settings(request)
    try:
        body = await request_json(request)
        prompt = body.get("prompt")
        mode = body.get("mode", "fast")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 5000:
            return error("Enter a prompt containing 1 to 5,000 characters.")
        if not isinstance(mode, str) or mode not in MODES:
            return error("Choose Fast or Deep mode.")
        if not state.companion:
            return error("The V3 model credential has yet to be configured.", 503)
        token, owner = await account(request)
        if body.get("signed_in") is True and not owner:
            return error("Your sign-in expired. Sign in to reopen saved chats, or start a guest chat.", 401)
        guest = None
        new_guest = False
        if not owner:
            owner, guest, new_guest = state.preview.guest(request.cookies.get(GUEST_COOKIE))
        conversation_id = selected_id(body["conversation_id"]) if body.get("conversation_id") else str(uuid4())
        if guest and body.get("conversation_id") and conversation_id not in guest.conversations:
            return error("This guest conversation expired. Start a new chat to continue.", 410)
        instructions = body.get("instructions")
        if instructions is not None and (not isinstance(instructions, str) or len(instructions) > 2000):
            return error("Keep the working instructions within 2,000 characters.")
        prompt = prompt.strip()
    except StateError as failure:
        return error(str(failure), 400)

    run_id = str(uuid4())

    async def stream():
        if owner in state.active_owners:
            yield {"type": "error", "text": "Another assignment is running in this session. Stop it or wait for its answer."}
            return
        if len(state.active_owners) >= 8:
            yield {"type": "error", "text": "The preview queue is full. Try again in a minute."}
            return
        state.active_owners.add(owner)
        try:
            if state.slot.locked():
                yield {"type": "activity", "text": "Waiting for a research slot"}
            async with asyncio.timeout(165), state.slot:
                async for piece in execute():
                    yield piece
        except TimeoutError:
            yield {"type": "error", "text": "The assignment timed out. You can send the question again."}
        finally:
            state.active_owners.discard(owner)

    async def execute():
        try:
            row = await state.store.load(token, conversation_id) if token else None
            if token and body.get("conversation_id") and row is None:
                yield {"type": "error", "text": "The saved V3 conversation is unavailable."}
                return
            if guest:
                turns = list(guest.conversations.get(conversation_id, []))
            else:
                turns = list(row["turns"]) if row else []
            earlier = list(state.history.accessible(conversation_id, owner, turns))
            context, prior_evidence = state.history.context(earlier)
            previous = earlier[-1] if earlier else {}
            objective = previous.get("objective") or (earlier[0]["prompt"] if earlier else prompt)
            brief = previous.get("instructions", "") if instructions is None else instructions.strip()
            if earlier and (objective != earlier[0]["prompt"] or len(earlier) > 5):
                context.append({"role": "user", "content": "Original assignment (later changes take precedence): " + objective})
            if brief:
                context.append({"role": "user", "content": "Current user-pinned working instructions: " + brief})
            if token:
                note = await state.store.memory(token)
                if note.get("enabled") and note.get("notes"):
                    context.append({"role": "user", "content": "User-selected personal preferences and context: " + note["notes"]})
            basis = {}
            for turn in earlier:
                basis.update(turn.get("basis", {}))
                basis.update({e["source_id"]: e.get("fingerprint", e["release"]) for e in turn.get("evidence", []) if e["origin"] == "canon"})
            if token:
                await state.store.reserve(token)
            state.preview.reserve(guest)
            async def recall(query, ledger):
                archived = []
                if row and row["revision"] > len(turns):
                    archived = await state.store.find_work(token, conversation_id, query)
                accessible = list(state.history.accessible(conversation_id, owner, archived))
                return state.history.recall(accessible + earlier, query, ledger)

            last_draft_check = 0
            async for piece in state.companion.research(prompt, mode, context, prior_evidence, basis,
                                                       any(turn.get("web_used") for turn in earlier), recall,
                                                       previous.get("requirements", {})):
                if piece["type"] == "draft" and piece.get("basis"):
                    if time.monotonic() - last_draft_check > 4:
                        await sync_catalogue(state)
                        last_draft_check = time.monotonic()
                    if not answer_available(state, piece):
                        raise StateError("A source changed. Run the assignment again with the current release.")
                if piece["type"] == "answer":
                    await sync_catalogue(state)
                    if not answer_available(state, piece):
                        raise StateError("A source changed during this assignment. Run it again with the current release.")
                    title = row["title"] if row else " ".join(prompt.split())[:110]
                    turns.append(state.history.sign(conversation_id, owner, {
                        "run_id": run_id,
                        "prompt": prompt, "answer": piece["text"], "evidence": piece["evidence"],
                        "objective": objective, "instructions": brief, "requirements": piece.get("requirements", {}),
                        "basis": piece.get("basis", {}),
                        "artifacts": piece.get("artifacts", []), "research_steps": piece.get("research_steps", []),
                        "web_used": piece["web_used"], "partial": piece["partial"],
                        "tool_failures": piece["tool_failures"], "usage": piece["usage"], "mode": mode,
                    }))
                    if guest:
                        if conversation_id not in guest.conversations and len(guest.conversations) >= 3:
                            del guest.conversations[next(iter(guest.conversations))]
                        guest.conversations[conversation_id] = turns[-TOP_TURNS:]
                    else:
                        await state.store.save(token, conversation_id, title, turns, row["revision"] if row else 0)
                    piece["conversation_id"] = conversation_id
                yield piece
        except (KnowledgeError, CompanionError, StateError) as failure:
            yield {"type": "error", "text": str(failure)}


    if body.get("delivery") == "job":
        job_id = state.jobs.start(run_id, owner, prompt, instructions or "", conversation_id, stream)
        response = data_response({"job_id": job_id, "conversation_id": conversation_id}, 202)
    else:
        async def encoded():
            async for item in stream():
                if item["type"] == "draft":
                    item = {"type": "draft", "text": item["text"]}
                yield json_text(item) + "\n"
        response = StreamingResponse(encoded(), media_type="application/x-ndjson",
                                     headers={**ERROR_HEADERS, "X-Content-Type-Options": "nosniff"})
    if new_guest:
        set_cookie(response, request, GUEST_COOKIE, owner, 86400)
    return response


async def job_status(request):
    state = settings(request)
    try:
        _, owner = await account(request)
    except StateError as failure:
        return error(str(failure), 503)
    if not owner:
        owner = request.cookies.get(GUEST_COOKIE)
        if owner not in state.preview.guests:
            return error("This temporary research run has expired.", 410)
    job = state.jobs.get(request.path_params["job_id"], owner)
    if not job:
        return error("This research run is unavailable. Reopen a saved chat or start another assignment.", 410)
    if request.method == "DELETE":
        if not same_origin(request):
            return error("Open the preview directly to stop research.", 403)
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            if job.result is None:
                job.result = {"type": "error", "text": "Assignment stopped."}
    async def snapshot(check_sources=False):
        event = job.result or {"type": "activity", "text": job.activity, "research_steps": list(job.steps), "draft": job.draft}
        basis = job.result if event["type"] == "answer" else {"basis": job.draft_basis}
        if state.registry and (event["type"] == "answer" or job.draft_basis):
            if check_sources or event["type"] == "answer":
                await sync_catalogue(state)
            if not answer_available(state, basis):
                event = {"type": "error", "text": "A source used in this answer changed. Run the assignment again."}
        return {"prompt": job.prompt, "instructions": job.instructions, "conversation_id": job.conversation, "event": event}

    if request.method == "GET" and request.query_params.get("watch") == "1":
        async def updates():
            first = True
            while True:
                changed = job.changed
                try:
                    data = await snapshot(check_sources=first)
                except StateError:
                    break  # Close the connection so the browser can reconnect and recheck.
                first = False
                yield json_text(data) + "\n"
                if data["event"]["type"] in {"answer", "error"}:
                    break
                try:
                    await asyncio.wait_for(changed.wait(), 8)
                except TimeoutError:
                    pass  # Repeat the current state as a heartbeat through idle proxies.
        return StreamingResponse(updates(), media_type="application/x-ndjson",
                                 headers={**ERROR_HEADERS, "X-Accel-Buffering": "no"})
    try:
        return data_response(await snapshot(check_sources=True))
    except StateError:
        return error("The current source catalogue is temporarily unavailable.", 503)


def create_app(transport=None, directory=None):
    @asynccontextmanager
    async def lifespan(application):
        client = httpx.AsyncClient(transport=transport, timeout=12.0, follow_redirects=False,
                                   limits=httpx.Limits(max_connections=8))
        preview_check = None
        try:
            # PKCE codes arrive in the callback query string.
            logging.getLogger("uvicorn.access").disabled = True
            state = application.state
            state.client = client
            state.knowledge = Knowledge(directory) if directory else Knowledge()
            state.web_enabled = os.getenv("MKH_WEB_RESEARCH", "").lower() in {"1", "true"}
            state.origin = (os.getenv("MKH_PUBLIC_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
            url, public_key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_PUBLISHABLE_KEY")
            state.store = SupabaseState(client, url, public_key) if url and public_key else None
            model_key = os.getenv("OPENAI_API_KEY")
            state.companion = Companion(state.knowledge, client, model_key, state.web_enabled) if model_key else None
            state.signing_key = os.getenv("MKH_HISTORY_SIGNING_KEY") or model_key
            state.history = History(state.signing_key, state.knowledge, state.web_enabled)
            registry_enabled = os.getenv("MKH_MANAGED_SOURCES", "on" if os.getenv("RENDER") == "true" else "off").lower() in {"1","on","true"}
            state.registry = Publications(state.knowledge, state.store) if registry_enabled and state.store else None
            state.slot = asyncio.Semaphore(2)
            state.active_owners = set()
            state.preview = PreviewSessions()
            state.jobs = ResearchJobs()
            if state.companion and preview_check_requested():
                preview_check = asyncio.create_task(run_preview_check(state.companion))
            yield
        finally:
            if hasattr(application.state, "jobs"):
                await application.state.jobs.close()
            if preview_check is not None:
                preview_check.cancel()
                with suppress(asyncio.CancelledError):
                    await preview_check
            await client.aclose()

    application = Starlette(lifespan=lifespan, routes=[
        Route("/", home),
        Route("/api/health", health),
        Route("/api/sources", sources),
        Route("/api/sources/{source_id}", source),
        Route("/api/session", identify),
        Route("/api/admin/sources", admin, methods=["GET","POST"]),
        Route("/api/memory", memory, methods=["GET", "POST"]),
        Route("/api/sources/{source_id}/geometry", geometry),
        Route("/auth/callback", auth_callback),
        Route("/api/auth/signout", signout, methods=["POST"]),
        Route("/api/auth/{operation}", auth, methods=["POST"]),
        Route("/api/conversations", conversations),
        Route("/api/conversations/{conversation_id}", conversations, methods=["GET", "DELETE"]),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/jobs/{job_id}", job_status, methods=["GET", "DELETE"]),
        Mount("/assets", app=StaticFiles(directory=WEB)),
    ])
    application.add_middleware(CatalogueBoundary)
    return application


app = create_app()
