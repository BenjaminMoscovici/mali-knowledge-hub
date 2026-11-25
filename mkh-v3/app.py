"""The isolated MKH V3 web application."""

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from companion import Companion, CompanionError, MODES
from knowledge import Evidence, Knowledge, KnowledgeError, json_text
from live_preview_check import requested as preview_check_requested, run as run_preview_check
from state import COOKIE, History, StateError, SupabaseState

WEB = Path(__file__).resolve().parent / "web"
EMAIL = re.compile(r"[^@\s]{1,128}@[^@\s]{1,123}\.[^@\s]{1,30}\Z")
ERROR_HEADERS = {"Cache-Control": "no-store"}
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


async def request_json(request):
    if not same_origin(request):
        raise StateError("Open the preview directly to perform this action.")
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise StateError("Expected a JSON request.")
    buffer = bytearray()
    try:
        async for chunk in request.stream():
            if len(buffer) + len(chunk) > MAX_BYTES:
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
        "chat_configured": bool(state.store and state.companion), "public_web_research": state.web_enabled,
        "sources": len(state.knowledge.sources),
    })


async def sources(request):
    query = request.query_params.get("q", "")[:350]
    return data_response({"sources": settings(request).knowledge.discover(query)})


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


async def identify(request):
    state = settings(request)
    try:
        _, owner = await account(request)
        return data_response({
            "authenticated": bool(owner), "auth_enabled": bool(state.store),
            "chat_enabled": bool(owner and state.companion), "model_configured": bool(state.companion),
        })
    except StateError as failure:
        return error(str(failure), 503)


async def auth(request):
    state = settings(request)
    if not state.store:
        return error("V3 sign-in is being configured.", 503)
    try:
        body = await request_json(request)
        email = body.get("email", "")
        if not isinstance(email, str) or len(email) > 254 or not EMAIL.fullmatch(email.strip()):
            return error("Enter your V3 team email address.")
        email = email.strip().lower()
        if request.path_params["operation"] == "request-code":
            await state.store.send_code(email)
            return data_response({"sent": True})
        if request.path_params["operation"] != "verify-code":
            return error("Unknown sign-in operation.", 404)
        code = body.get("code", "")
        if not isinstance(code, str) or not re.fullmatch(r"\d{6,10}", code):
            return error("Enter the numeric code from your email.")
        token, age = await state.store.verify_code(email, code)
        response = data_response({"authenticated": True})
        response.set_cookie(COOKIE, token, max_age=age, httponly=True, secure=secured(request), samesite="lax")
        return response
    except StateError as failure:
        return error(str(failure), 400)


async def signout(request):
    if not same_origin(request):
        return error("Open the preview directly to sign out.", 403)
    response = data_response({"authenticated": False})
    response.delete_cookie(COOKIE, httponly=True, secure=secured(request), samesite="lax")
    return response


async def conversations(request):
    try:
        token, owner = await account(request)
        if not owner:
            return error("Sign in to open your saved conversations.", 401)
        state = settings(request)
        value = request.path_params.get("conversation_id")
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
        history = state.history.accessible(conversation_id, owner, row["turns"])
        return data_response({
            "id": conversation_id, "title": row["title"],
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
        token, owner = await account(request)
        if not owner:
            return error("Sign in to run a V3 assignment.", 401)
        if not state.companion:
            return error("The V3 model credential has yet to be configured.", 503)
        conversation_id = selected_id(body["conversation_id"]) if body.get("conversation_id") else str(uuid4())
        prompt = prompt.strip()
    except StateError as failure:
        return error(str(failure), 400)

    def event(value):
        return json_text(value) + "\n"

    async def stream():
        if state.slot.locked():
            yield event({"type": "error", "text": "The preview is processing another assignment. Try again shortly."})
            return
        async with state.slot:
            try:
                row = await state.store.load(token, conversation_id)
                if body.get("conversation_id") and row is None:
                    yield event({"type": "error", "text": "The saved V3 conversation is unavailable."})
                    return
                turns = row["turns"] if row else []
                earlier = list(state.history.accessible(conversation_id, owner, turns))
                context, prior_evidence = state.history.context(earlier)
                await state.store.reserve(token)
                async for piece in state.companion.research(prompt, mode, context, prior_evidence):
                    if piece["type"] == "answer":
                        title = row["title"] if row else " ".join(prompt.split())[:110]
                        turns.append(state.history.sign(conversation_id, owner, {
                            "prompt": prompt, "answer": piece["text"], "evidence": piece["evidence"],
                            "web_used": piece["web_used"], "partial": piece["partial"],
                            "tool_failures": piece["tool_failures"], "usage": piece["usage"], "mode": mode,
                        }))
                        await state.store.save(token, conversation_id, title, turns, row["revision"] if row else 0)
                        piece["conversation_id"] = conversation_id
                    yield event(piece)
            except (KnowledgeError, CompanionError, StateError) as failure:
                yield event({"type": "error", "text": str(failure)})

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={**ERROR_HEADERS, "X-Content-Type-Options": "nosniff"})


def create_app(transport=None, directory=None):
    @asynccontextmanager
    async def lifespan(application):
        client = httpx.AsyncClient(transport=transport, timeout=12.0, follow_redirects=False,
                                   limits=httpx.Limits(max_connections=8))
        preview_check = None
        try:
            state = application.state
            state.client = client
            state.knowledge = Knowledge(directory) if directory else Knowledge()
            state.web_enabled = os.getenv("MKH_WEB_RESEARCH", "").lower() in {"1", "true"}
            state.origin = (os.getenv("MKH_PUBLIC_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")
            url, public_key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_PUBLISHABLE_KEY")
            state.store = SupabaseState(client, url, public_key) if url and public_key else None
            model_key = os.getenv("OPENAI_API_KEY")
            state.companion = Companion(state.knowledge, client, model_key, state.web_enabled) if model_key else None
            state.history = History(
                os.getenv("MKH_HISTORY_SIGNING_KEY") or model_key, state.knowledge, state.web_enabled,
            )
            state.slot = asyncio.Lock()
            if state.companion and preview_check_requested():
                preview_check = asyncio.create_task(run_preview_check(state.companion))
            yield
        finally:
            if preview_check is not None:
                preview_check.cancel()
                with suppress(asyncio.CancelledError):
                    await preview_check
            await client.aclose()

    return Starlette(lifespan=lifespan, routes=[
        Route("/", home),
        Route("/api/health", health),
        Route("/api/sources", sources),
        Route("/api/sources/{source_id}", source),
        Route("/api/session", identify),
        Route("/api/auth/signout", signout, methods=["POST"]),
        Route("/api/auth/{operation}", auth, methods=["POST"]),
        Route("/api/conversations", conversations),
        Route("/api/conversations/{conversation_id}", conversations, methods=["GET", "DELETE"]),
        Route("/api/chat", chat, methods=["POST"]),
        Mount("/assets", app=StaticFiles(directory=WEB)),
    ])


app = create_app()
