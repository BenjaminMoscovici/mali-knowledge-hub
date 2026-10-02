"""Conversation-first HTTP surface for the V4 frontend.

The analytical engine and Supabase service credential remain on this server.
Private research uses only the caller's verified Supabase JWT and the existing
owner-scoped RLS tables.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import time
import traceback
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from supabase import create_client

from language import answer_language
from user_research import (REFERENCE_FIELDS, ResearchStore, ResearchStoreError,
                           evidence_references, hydrate_saved_evidence)
from source_wave import publish_snapshot_logged


WEB = Path(__file__).with_name("web")
MODES = {"quick", "balanced", "deep"}
ACCESS_COOKIE = "mkh_access"
REFRESH_COOKIE = "mkh_refresh"
MAX_QUESTION = 5000
MAX_GUEST_CONTEXT = 10
_analysis_limit = asyncio.Semaphore(8)


def error(message, status=400):
    return JSONResponse({"error": message}, status_code=status)


def setting(name):
    return os.environ.get(name, "").strip()


def auth_client():
    if not setting("SUPABASE_URL") or not setting("SUPABASE_PUBLISHABLE_KEY"):
        raise RuntimeError("Account sign-in is not configured.")
    return create_client(setting("SUPABASE_URL"), setting("SUPABASE_PUBLISHABLE_KEY"))


def set_auth_cookies(response, access, refresh):
    for name, value, age in ((ACCESS_COOKIE, access, 3600),
                             (REFRESH_COOKIE, refresh, 30 * 86400)):
        response.set_cookie(name, value, max_age=age, secure=True,
                            httponly=True, samesite="lax", path="/")
    return response


def clear_auth_cookies(response):
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
    return response


def same_origin(request):
    origin = request.headers.get("origin", "")
    expected = setting("MKH_PUBLIC_ORIGIN") or "https://mali-knowledge-hub.onrender.com"
    if origin == expected.rstrip("/"):
        return True
    # The local preview is intentionally limited to loopback.
    parsed = urlsplit(origin)
    return parsed.hostname in {"localhost", "127.0.0.1"} and request.url.hostname in {
        "localhost", "127.0.0.1"
    }


async def body(request):
    if request.method != "GET" and not same_origin(request):
        return None
    if "application/json" not in request.headers.get("content-type", ""):
        return None
    try:
        length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        return None
    if length < 0 or length > 400_000:
        return None
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


async def actor(request):
    """Return a verified user, usable JWT, and refreshed session if needed."""
    access = request.cookies.get(ACCESS_COOKIE)
    refresh = request.cookies.get(REFRESH_COOKIE)
    if not access and not refresh:
        return None, None, None
    client = auth_client()
    if access:
        try:
            user = (await asyncio.to_thread(client.auth.get_user, access)).user
            if user and user.id:
                return user, access, None
        except Exception:
            pass
    if refresh:
        try:
            session = (await asyncio.to_thread(client.auth.refresh_session, refresh)).session
            if session and session.user and session.user.id:
                return session.user, session.access_token, session
        except Exception:
            pass
    return None, None, None


def store_for(user, token):
    return ResearchStore(setting("SUPABASE_URL"),
                         setting("SUPABASE_PUBLISHABLE_KEY"), token, user.id)


def with_session(response, session):
    if session:
        return set_auth_cookies(response, session.access_token, session.refresh_token)
    return response


def thread_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def public_evidence(result):
    refs = evidence_references(result)
    for ref, source in zip(refs, result.get("evidence") or []):
        if source.get("content"):
            ref["content"] = str(source["content"])[:6000]
    return refs


def safe_guest_context(value):
    if not isinstance(value, list):
        return []
    messages = []
    for item in value[-MAX_GUEST_CONTEXT:]:
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = item.get("content")
        if not isinstance(content, str):
            continue
        messages.append({"role": item["role"], "content": content[:6000],
                         "standalone_question": str(item.get("standalone_question") or "")[:5000]})
    return messages


async def health(request):
    return JSONResponse({"status": "ok", "version": "v4-frontend-test"})


async def me(request):
    user, _, refreshed = await actor(request)
    response = JSONResponse({"user": {"id": user.id, "email": user.email} if user else None})
    return with_session(response, refreshed) if user else clear_auth_cookies(response)


async def email_link(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    email = str(payload.get("email") or "").strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return error("Enter a valid email address.")
    try:
        client = auth_client()
        redirect = setting("MKH_PUBLIC_ORIGIN") or "https://mali-knowledge-hub.onrender.com"
        await asyncio.to_thread(client.auth.sign_in_with_otp, {
            "email": email, "options": {"should_create_user": True,
                                         "email_redirect_to": redirect.rstrip("/") + "/"},
        })
    except Exception:
        return error("A sign-in link could not be sent right now.", 503)
    return JSONResponse({"message": "If this address can sign in, a link is on its way."})


async def accept_link(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    access, refresh = payload.get("access_token"), payload.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh, str) or len(access) > 8000 or len(refresh) > 8000:
        return error("This sign-in link is incomplete.")
    try:
        client = auth_client()
        user = (await asyncio.to_thread(client.auth.get_user, access)).user
        if not user or not user.id:
            raise ValueError("Invalid account")
    except Exception:
        return error("This sign-in link has expired. Request a new one.", 401)
    return set_auth_cookies(JSONResponse({"user": {"id": user.id, "email": user.email}}),
                            access, refresh)


async def logout(request):
    if await body(request) is None:
        return error("Invalid request.", 403)
    # The browser loses both credentials even when the provider is unreachable.
    return clear_auth_cookies(JSONResponse({"ok": True}))


async def conversations(request):
    user, token, refreshed = await actor(request)
    if not user:
        return error("Sign in to save conversations.", 401)
    store = store_for(user, token)
    try:
        if request.method == "GET":
            response = JSONResponse({"conversations": await asyncio.to_thread(store.list_conversations)})
        else:
            payload = await body(request)
            if payload is None:
                return error("Invalid request.", 403)
            mode = payload.get("analysis_mode", "balanced")
            if mode not in MODES:
                return error("Choose a valid analysis depth.")
            title = str(payload.get("title") or "New conversation").strip()[:120]
            cid = str(uuid.uuid4())
            row = await asyncio.to_thread(store.create_conversation, cid, title, mode)
            response = JSONResponse({"conversation": row}, status_code=201)
    except ResearchStoreError:
        return error("Saved conversations are temporarily unavailable.", 503)
    return with_session(response, refreshed)


async def conversation_detail(request):
    user, token, refreshed = await actor(request)
    if not user:
        return error("Sign in to access conversations.", 401)
    cid = thread_id(request.path_params.get("conversation_id"))
    if not cid:
        return error("Conversation not found.", 404)
    store = store_for(user, token)
    try:
        owned = next((row for row in await asyncio.to_thread(store.list_conversations)
                      if row["id"] == cid), None)
        if owned is None:
            return error("Conversation not found.", 404)
        if request.method == "GET":
            rows = await asyncio.to_thread(store.list_messages, cid)
            response = JSONResponse({"conversation": owned, "messages": rows})
        elif request.method == "PATCH":
            payload = await body(request)
            if payload is None:
                return error("Invalid request.", 403)
            changes = {}
            if "title" in payload:
                title = str(payload["title"]).strip()
                if not 1 <= len(title) <= 120:
                    return error("Title must be 1–120 characters.")
                changes["title"] = title
            if "analysis_mode" in payload:
                if payload["analysis_mode"] not in MODES:
                    return error("Choose a valid analysis depth.")
                changes["analysis_mode"] = payload["analysis_mode"]
            if "archived" in payload:
                changes["archived_at"] = (datetime.now(timezone.utc).isoformat()
                                          if payload["archived"] else None)
            if not changes:
                return error("Nothing to update.")
            await asyncio.to_thread(store.update_conversation, cid, **changes)
            response = JSONResponse({"ok": True})
        else:
            if await body(request) is None:
                return error("Invalid request.", 403)
            await asyncio.to_thread(store.delete_conversation, cid)
            response = JSONResponse({"ok": True})
    except ResearchStoreError:
        return error("The conversation could not be accessed right now.", 503)
    return with_session(response, refreshed)


async def saved_evidence(request):
    user, token, refreshed = await actor(request)
    if not user:
        return error("Sign in to inspect saved evidence.", 401)
    cid = thread_id(request.path_params.get("conversation_id"))
    try:
        position = int(request.query_params.get("position", "0"))
    except ValueError:
        position = 0
    if not cid or position < 1:
        return error("Evidence not found.", 404)
    store = store_for(user, token)
    try:
        rows = await asyncio.to_thread(store.list_messages, cid)
        row = next((r for r in rows if r["position"] == position and r["role"] == "assistant"), None)
        if not row:
            return error("Evidence not found.", 404)
        result = {"evidence": row.get("evidence_refs") or []}
        def fetch(ids):
            from analysis_core import supabase
            return (supabase.table("chunks").select("id,content").in_("id", ids).execute().data or [])
        await asyncio.to_thread(hydrate_saved_evidence, result, fetch)
        response = JSONResponse({"evidence": result["evidence"]})
    except Exception:
        return error("Saved evidence is temporarily unavailable.", 503)
    return with_session(response, refreshed)


async def chat(request):
    request_started = time.perf_counter()
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    question = payload.get("question")
    mode = payload.get("analysis_mode", "balanced")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= MAX_QUESTION:
        return error("Enter a question of at most 5,000 characters.")
    if mode not in MODES:
        return error("Choose a valid analysis depth.")
    question = question.strip()
    user, token, refreshed = await actor(request)
    store = store_for(user, token) if user else None
    cid = thread_id(payload.get("conversation_id")) if payload.get("conversation_id") else None
    if payload.get("conversation_id") and not cid:
        return error("Conversation not found.", 404)
    if cid and not user:
        return error("Sign in again to continue this saved conversation.", 401)
    prior = safe_guest_context(payload.get("prior_messages")) if not user else []
    rows = []
    if store and cid:
        try:
            if not any(r["id"] == cid for r in await asyncio.to_thread(store.list_conversations)):
                return error("Conversation not found.", 404)
            rows = await asyncio.to_thread(store.list_messages, cid)
            prior = [{"role": r["role"], "content": r["content"],
                      "standalone_question": r.get("standalone_question")}
                     for r in rows[-10:]]
        except ResearchStoreError:
            return error("This saved conversation could not be loaded.", 503)
    phase = "engine_load"
    context_usage = {}
    try:
        from analysis_core import (generate_grounded_answer, is_source_inventory_question,
                                   likely_context_dependent_followup, resolve_conversational_question,
                                   source_inventory_answer, openai_client)
        async with _analysis_limit:
            standalone = question
            if likely_context_dependent_followup(question, prior):
                phase = "context_rewrite"
                context_token, context_id = openai_client.begin()
                try:
                    standalone = await asyncio.to_thread(resolve_conversational_question, question, prior)
                finally:
                    context_usage = openai_client.finish(context_token, context_id)
            phase = "research"
            if is_source_inventory_question(standalone):
                result = {"answer": source_inventory_answer(), "evidence": [], "family_counts": {}}
            else:
                result = await asyncio.to_thread(generate_grounded_answer, standalone, depth=mode,
                                                 response_language=answer_language(question))
    except Exception as exc:
        # Never log provider messages, questions, tokens or source passages.
        print("MKH_API_FAILURE " + json.dumps({
            "phase": phase, "error_type": type(exc).__name__,
            "frames": [frame.name for frame in traceback.extract_tb(exc.__traceback__)[-6:]],
            "context_api_usage": context_usage,
        }, separators=(",", ":")), flush=True)
        return error("This analysis could not be completed. Please try again.", 503)
    answer = result.get("answer") or "No answer was produced."
    refs = evidence_references(result)
    save_error = False
    position = None
    if store:
        try:
            if not cid:
                cid = str(uuid.uuid4())
                await asyncio.to_thread(store.create_conversation, cid, question[:80], mode)
            position = len(rows) + 2
            await asyncio.to_thread(store.save_exchange, cid, position - 1,
                                    question, standalone, answer, mode, refs)
        except ResearchStoreError:
            save_error = True
    research_usage = result.get("api_usage") or {}
    print("MKH_REQUEST_USAGE " + json.dumps({
        "request_id": result.get("request_id"), "depth": mode,
        "server_seconds": round(time.perf_counter() - request_started, 2),
        "context_api_usage": context_usage, "research_api_usage": research_usage,
        "estimated_usd": round((context_usage.get("estimated_usd") or 0)
                               + (research_usage.get("estimated_usd") or 0), 8),
        "unpriced_calls": (context_usage.get("unpriced_calls") or 0)
                          + (research_usage.get("unpriced_calls") or 0),
    }, separators=(",", ":")), flush=True)
    response = JSONResponse({"answer": answer, "evidence": public_evidence(result),
                             "standalone_question": standalone, "conversation_id": cid,
                             "position": position, "saved": bool(store and not save_error),
                             "save_error": save_error,
                             "geography": (result.get("geography") or {}).get("assumption")})
    return with_session(response, refreshed)


async def import_guest(request):
    user, token, refreshed = await actor(request)
    if not user:
        return error("Sign in to save this guest conversation.", 401)
    payload = await body(request)
    if payload is None or not isinstance(payload.get("messages"), list):
        return error("Invalid guest conversation.", 400)
    messages = payload["messages"]
    if not messages or len(messages) > 100 or len(messages) % 2:
        return error("A complete guest conversation is required.")
    mode = payload.get("analysis_mode", "balanced")
    if mode not in MODES:
        return error("Choose a valid analysis depth.")
    title = str(payload.get("title") or "Guest research").strip()[:120] or "Guest research"
    validated = []
    for i, item in enumerate(messages):
        if not isinstance(item, dict) or item.get("role") != ("user" if i % 2 == 0 else "assistant"):
            return error("Guest messages are incomplete.")
        content = item.get("content")
        if not isinstance(content, str) or not 1 <= len(content) <= 50_000:
            return error("A guest message is too long.")
        refs = item.get("evidence") or []
        if not isinstance(refs, list) or len(refs) > 100:
            return error("Too many evidence references.")
        validated.append((item, content, [{k: (str(v)[:1500] if k == "source_excerpt" else v)
                                           for k, v in ref.items()
                                           if k in REFERENCE_FIELDS or k == "source_excerpt"}
                                          for ref in refs if isinstance(ref, dict)]))
    store = store_for(user, token)
    cid = str(uuid.uuid4())
    try:
        await asyncio.to_thread(store.create_conversation, cid, title, mode)
        for i in range(0, len(validated), 2):
            q, a = validated[i], validated[i + 1]
            await asyncio.to_thread(store.save_exchange, cid, i + 1,
                                    q[1], str(q[0].get("standalone_question") or q[1])[:5000],
                                    a[1], a[0].get("analysis_mode") if a[0].get("analysis_mode") in MODES else mode,
                                    a[2])
    except ResearchStoreError:
        return error("This guest conversation could not be saved.", 503)
    return with_session(JSONResponse({"conversation_id": cid}, status_code=201), refreshed)


async def index(request):
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


async def admin(request):
    target = setting("MKH_ADMIN_URL")
    return RedirectResponse(target, status_code=302) if target else error("Administration is on a separate service.", 404)


routes = [
    Route("/api/health", health),
    Route("/api/me", me),
    Route("/api/auth/email", email_link, methods=["POST"]),
    Route("/api/auth/session", accept_link, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/conversations", conversations, methods=["GET", "POST"]),
    Route("/api/conversations/import", import_guest, methods=["POST"]),
    Route("/api/conversations/{conversation_id}/evidence", saved_evidence),
    Route("/api/conversations/{conversation_id}", conversation_detail,
          methods=["GET", "PATCH", "DELETE"]),
    Route("/admin", admin),
    Route("/Administration", admin),
    Mount("/assets", app=StaticFiles(directory=WEB), name="assets"),
    Route("/", index),
]
@asynccontextmanager
async def lifespan(app):
    # Publication is idempotent and runs after the server has bound its port,
    # so a large first load cannot make the health check fail.
    asyncio.create_task(asyncio.to_thread(publish_snapshot_logged))
    yield


app = Starlette(routes=routes, lifespan=lifespan)


async def security_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


app.add_middleware(BaseHTTPMiddleware, dispatch=security_headers)
