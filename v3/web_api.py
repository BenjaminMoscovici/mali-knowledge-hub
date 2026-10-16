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
import requests
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, unquote

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from supabase import create_client, ClientOptions

from language import answer_language, synthesis_language
from user_research import (REFERENCE_FIELDS, ResearchStore, ResearchStoreError,
                           evidence_references, hydrate_saved_evidence)
from source_wave import publish_snapshot_logged
from operational_sources import publish_operational_logged
from analytical_sources import publish_analytical_logged
from project_learning_sources import publish_project_learning_logged
from eu_sources import publish_eu_logged
from query_router import classify
from geographic_model import geographic_model
from country_foundation import country_foundation, resolve_country_followup
from geography_context import resolve_count_followup, resolve_hierarchy_followup
from followup_context import resolve_slots


WEB = Path(__file__).with_name("web")
MODES = {"quick", "balanced", "deep"}
ACCESS_COOKIE = "mkh_access"
REFRESH_COOKIE = "mkh_refresh"
MAX_QUESTION = 5000
MAX_GUEST_CONTEXT = 10
_analysis_limit = asyncio.Semaphore(8)
_transform_limit = asyncio.Semaphore(8)
_attachment_limit = asyncio.Semaphore(2)
_auth_limit = asyncio.Semaphore(4)
_admin_limit = asyncio.Semaphore(2)


async def extract_attachment(request):
    """Transient local parsing. No corpus writes, provider calls, or file logs."""
    if not same_origin(request):
        return error("Only same-origin attachments are accepted.", 403)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
        return error("Send the document as a binary attachment.", 415)
    filename = unquote(request.headers.get("x-mkh-filename", ""))
    query = unquote(request.headers.get("x-mkh-question", ""))
    if not filename or len(filename) > 250 or len(query) > MAX_QUESTION:
        return error("Invalid attachment name or question.")
    maximum = 5 * 1024 * 1024
    try:
        if int(request.headers.get("content-length", "0")) > maximum:
            return error("Chat attachments must be smaller than 5 MB. Administration accepts 20 MB.", 413)
    except ValueError:
        return error("Invalid attachment length.")
    async with _attachment_limit:
        raw = bytearray()
        async for part in request.stream():
            if len(raw) + len(part) > maximum:
                return error("Chat attachments must be smaller than 5 MB.", 413)
            raw.extend(part)
        from document_formats import chat_excerpt
        try:
            data = await asyncio.to_thread(chat_excerpt, filename, bytes(raw), query)
            return JSONResponse(data)
        except ValueError as exc:
            return error(str(exc), 422)
        finally:
            raw.clear()


def error(message, status=400):
    return JSONResponse({"error": message}, status_code=status)


def setting(name):
    return os.environ.get(name, "").strip()


def auth_client():
    if not setting("SUPABASE_URL") or not setting("SUPABASE_PUBLISHABLE_KEY"):
        raise RuntimeError("Account sign-in is not configured.")
    return create_client(setting("SUPABASE_URL"), setting("SUPABASE_PUBLISHABLE_KEY"),
                         options=ClientOptions(auto_refresh_token=False, persist_session=False))


def verified_email_user(user):
    return bool(user and getattr(user, "id", None) and getattr(user, "email", None)
                and getattr(user, "email_confirmed_at", None))


def account_view(user):
    # Editable profile metadata is display-only, never a source of permissions.
    metadata = getattr(user, "user_metadata", None) or {}
    username = metadata.get("username", "") if isinstance(metadata, dict) else ""
    return {"id": user.id, "email": user.email,
            "username": username[:60] if isinstance(username, str) else ""}


def auth_redirect():
    return (setting("MKH_PUBLIC_ORIGIN") or
            "https://mali-knowledge-hub.onrender.com").rstrip("/") + "/"


def signup_settings():
    """Fail closed before creating an account if email verification is disabled."""
    url, key = setting("SUPABASE_URL"), setting("SUPABASE_PUBLISHABLE_KEY")
    if not url or not key:
        raise RuntimeError("Account sign-in is not configured")
    response = requests.get(url.rstrip("/") + "/auth/v1/settings",
                            headers={"apikey": key}, timeout=10)
    response.raise_for_status()
    config = response.json()
    return (config.get("mailer_autoconfirm") is False
            and config.get("disable_signup") is False
            and config.get("external", {}).get("email") is True)


def account_email(payload):
    value = payload.get("email")
    email = value.strip().casefold() if isinstance(value, str) else ""
    return email if len(email) <= 254 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else None


def valid_new_password(value):
    return isinstance(value, str) and 12 <= len(value) <= 256 and len(value.encode("utf-8")) <= 1024


def valid_username(value):
    return (isinstance(value, str) and 2 <= len(value.strip()) <= 60
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def provider_failure(exc, message):
    if getattr(exc, "code", "") == "email_address_not_authorized":
        return error("Confirmation emails are not enabled for this address yet. Please contact the Hub administrator.", 503)
    if getattr(exc, "code", "") == "email_send_failed":
        return error("The email service could not send your message. Please try again later or contact the Hub administrator.", 503)
    if getattr(exc, "status", None) == 429 or str(getattr(exc, "code", "")).startswith("over_"):
        return error("Too many attempts. Please wait before trying again.", 429)
    if getattr(exc, "code", "") in {"weak_password", "same_password"}:
        return error("Choose a stronger new password that differs from your current password.")
    return error(message, 503)


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
    try:
        client = auth_client()
    except Exception:
        return None, None, None
    if access:
        try:
            user = (await asyncio.to_thread(client.auth.get_user, access)).user
            if verified_email_user(user):
                return user, access, None
        except Exception:
            pass
    if refresh:
        try:
            session = (await asyncio.to_thread(client.auth.refresh_session, refresh)).session
            if session and verified_email_user(session.user):
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
    response = JSONResponse({"user": account_view(user) if user else None})
    return with_session(response, refreshed) if user else clear_auth_cookies(response)


async def auth_status(request):
    try:
        enabled = await asyncio.to_thread(signup_settings)
    except Exception:
        return error("Account signup is temporarily unavailable.", 503)
    return JSONResponse({"signup_enabled": enabled, "email_confirmation_required": True})


async def signup(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    email, password, username = account_email(payload), payload.get("password"), payload.get("username")
    if not email:
        return error("Enter a valid email address.")
    if not valid_username(username):
        return error("Choose a username of 2–60 characters.")
    if not valid_new_password(password):
        return error("Use a password of 12–256 characters.")
    async with _auth_limit:
        try:
            if not await asyncio.to_thread(signup_settings):
                return error("Verified-email signup is not available right now.", 503)
            result = await asyncio.to_thread(auth_client().auth.sign_up, {
                "email": email, "password": password,
                "options": {"data": {"username": username.strip()},
                            "email_redirect_to": auth_redirect()},
            })
            # Never establish a session from signup, including provider misconfiguration.
            if result.session:
                return error("Email verification is required. Contact the Hub administrator.", 503)
        except Exception as exc:
            if getattr(exc, "code", "") not in {"user_already_exists", "email_exists"}:
                return provider_failure(exc, "Your account could not be created right now. Try again later.")
    return JSONResponse({"message": "Signup request accepted. If this is a new account, check your personal email "
                         "and spam folder for a confirmation link. Already registered? Sign in or reset your password. "
                         "If a confirmation is missing, use Resend confirmation email below."})


async def resend_confirmation(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    email = account_email(payload)
    if not email:
        return error("Enter a valid email address.")
    async with _auth_limit:
        try:
            await asyncio.to_thread(auth_client().auth.resend, {
                "type": "signup", "email": email,
                "options": {"email_redirect_to": auth_redirect()},
            })
        except Exception as exc:
            return provider_failure(exc, "A confirmation email could not be requested right now. Try again later.")
    return JSONResponse({"message": "Confirmation requested. If this account still needs verification, "
                         "check your inbox and spam folder for a fresh link. Already verified? Sign in or reset your password."})


async def password_login(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    email, password = account_email(payload), payload.get("password")
    # Legacy passwords remain usable; stronger limits apply only to newly chosen passwords.
    if not email or not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return error("Enter your email address and password.")
    async with _auth_limit:
        try:
            result = await asyncio.to_thread(auth_client().auth.sign_in_with_password,
                                             {"email": email, "password": password})
            if (not result.session or not verified_email_user(result.user)
                    or not verified_email_user(result.session.user)
                    or result.session.user.id != result.user.id):
                return error("Sign-in failed. Check your email verification and credentials.", 401)
        except Exception as exc:
            if getattr(exc, "code", "") in {"invalid_credentials", "email_not_confirmed"}:
                return error("Sign-in failed. Check your email verification and credentials.", 401)
            return provider_failure(exc, "Sign-in is temporarily unavailable.")
    return with_session(JSONResponse({"user": account_view(result.user)}), result.session)


async def recover_password(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    email = account_email(payload)
    if not email:
        return error("Enter a valid email address.")
    async with _auth_limit:
        try:
            await asyncio.to_thread(auth_client().auth.reset_password_for_email,
                                    email, {"redirect_to": auth_redirect()})
        except Exception as exc:
            return provider_failure(exc, "A password reset email could not be sent right now.")
    return JSONResponse({"message": "If this address has an account, a password reset link is on its way. "
                         "Use it to set a password for your existing account and saved research."})


async def update_password(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    if not valid_new_password(payload.get("password")):
        return error("Use a password of 12–256 characters.")
    user, access, refreshed = await actor(request)
    if not user:
        return error("Open a fresh password reset email or sign in first.", 401)
    refresh = refreshed.refresh_token if refreshed else request.cookies.get(REFRESH_COOKIE)
    if not refresh:
        return error("Open a fresh password reset email or sign in again.", 401)
    async with _auth_limit:
        try:
            client = auth_client()
            session = (await asyncio.to_thread(client.auth.set_session, access, refresh)).session
            if not session or not verified_email_user(session.user) or session.user.id != user.id:
                raise ValueError("Session identity mismatch")
            result = await asyncio.to_thread(client.auth.update_user, {"password": payload["password"]})
            if not verified_email_user(result.user) or result.user.id != user.id:
                raise ValueError("Account identity mismatch")
        except Exception as exc:
            return provider_failure(exc, "Your password could not be changed. Open a fresh reset email and try again.")
    return with_session(JSONResponse({"user": account_view(result.user),
                                      "message": "Password saved. Use your email address and password to sign in."}), session)


async def email_link(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    email = account_email(payload)
    if not email:
        return error("Enter a valid email address.")
    try:
        client = auth_client()
        await asyncio.to_thread(client.auth.sign_in_with_otp, {
            "email": email, "options": {"should_create_user": False,
                                         "email_redirect_to": auth_redirect()},
        })
    except Exception:
        return error("A sign-in link could not be sent right now.", 503)
    return JSONResponse({"message": "If this address can sign in, a link is on its way."})


async def accept_link(request):
    payload = await body(request)
    if payload is None:
        return error("Invalid request.", 403)
    access, refresh = payload.get("access_token"), payload.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh, str) or not access or not refresh or len(access) > 8000 or len(refresh) > 8000:
        return error("This sign-in link is incomplete.")
    try:
        client = auth_client()
        user = (await asyncio.to_thread(client.auth.get_user, access)).user
        if not verified_email_user(user):
            raise ValueError("Invalid account")
        session = (await asyncio.to_thread(client.auth.refresh_session, refresh)).session
        if not session or not verified_email_user(session.user) or session.user.id != user.id:
            raise ValueError("Session identity mismatch")
    except Exception:
        return error("This sign-in link has expired. Request a new one.", 401)
    return with_session(JSONResponse({"user": account_view(user)}), session)


async def logout(request):
    if await body(request) is None:
        return error("Invalid request.", 403)
    # Revoke the current refresh session where possible, and always clear browser credentials.
    access, refresh = request.cookies.get(ACCESS_COOKIE), request.cookies.get(REFRESH_COOKIE)
    if access and refresh:
        try:
            client = auth_client()
            await asyncio.to_thread(client.auth.set_session, access, refresh)
            await asyncio.to_thread(client.auth.sign_out, {"scope": "local"})
        except Exception:
            pass
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
    route_started = time.perf_counter()
    route = classify(question, mode)
    routing_seconds = time.perf_counter() - route_started
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
    standalone = question
    context_method = "existing_resolver"
    slot_context = None
    try:
        if route["path"] not in {"conversational", "conversation_only"}:
            resolved = await asyncio.to_thread(resolve_country_followup, question, prior)
            geography_method = 'structured_country_fact'
            if not resolved:
                resolved = await asyncio.to_thread(resolve_count_followup, question, prior)
                geography_method = 'structured_geographic_count'
            if not resolved:
                resolved = await asyncio.to_thread(resolve_hierarchy_followup, question, prior)
                geography_method = 'structured_geographic_hierarchy'
            if resolved:
                standalone = resolved
                route = classify(standalone, mode)
                context_method = geography_method
            else:
                slot_context = await asyncio.to_thread(resolve_slots, question, prior)
                if slot_context:
                    standalone = slot_context['standalone_question']
                    route = classify(standalone, mode)
                    context_method = slot_context['method']
        if route["path"] == "conversational":
            result = {"answer": route["reply"], "evidence": []}
        elif route["path"] == "conversation_only":
            from conversation_transform import restate
            phase = "conversation_transform"
            async with _transform_limit:
                result = await asyncio.to_thread(restate, question, prior, answer_language(question))
        elif slot_context and slot_context.get('direct_answer'):
            phase = "structured_empty_project_subset"
            result = {"answer": slot_context['direct_answer'], "evidence": [],
                      "family_counts": {}}
        elif route["path"] == "country_fact":
            phase = "structured_country_fact"
            result = await asyncio.to_thread(lambda: country_foundation().answer(standalone, synthesis_language(question)))
        elif route["path"] == "simple_geography":
            phase = "structured_geography"
            result = await asyncio.to_thread(lambda: geographic_model().answer(standalone, answer_language(question)))
        else:
            from analysis_core import (generate_grounded_answer, is_source_inventory_question,
                                   likely_context_dependent_followup, resolve_conversational_question,
                                   source_inventory_answer, openai_client)
            async with _analysis_limit:
                if not slot_context and likely_context_dependent_followup(question, prior):
                    phase = "context_rewrite"
                    context_token, context_id = openai_client.begin()
                    try:
                        standalone = await asyncio.to_thread(resolve_conversational_question, question, prior)
                    finally:
                        context_usage = openai_client.finish(context_token, context_id)
                phase = "research"
                if classify(standalone, mode)["path"] == "country_fact":
                    route = {"path": "country_fact"}
                    phase = "structured_country_fact"
                    result = await asyncio.to_thread(lambda: country_foundation().answer(standalone, synthesis_language(question)))
                elif classify(standalone, mode)["path"] == "simple_geography":
                    route = {"path": "simple_geography"}
                    phase = "structured_geography"
                    result = await asyncio.to_thread(lambda: geographic_model().answer(standalone, answer_language(question)))
                elif is_source_inventory_question(standalone):
                    result = {"answer": await asyncio.to_thread(source_inventory_answer, answer_language(question)), "evidence": [], "family_counts": {}}
                else:
                    result = await asyncio.to_thread(generate_grounded_answer, standalone, depth=mode,
                                                 response_language=synthesis_language(question))
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
    metrics = {
        "hub_commit": os.environ.get("RENDER_GIT_COMMIT"),
        "context_resolution_method": context_method,
        "request_id": result.get("request_id"), "depth": mode,
        "route": route["path"], "routing_seconds": round(routing_seconds, 6),
        "server_seconds": round(time.perf_counter() - request_started, 4),
        "model_calls": len([c for c in context_usage.get("calls", []) + research_usage.get("calls", []) if c.get("endpoint") == "responses"]),
        "embedding_calls": len([c for c in context_usage.get("calls", []) + research_usage.get("calls", []) if c.get("endpoint") == "embeddings"]),
        "external_research_calls": research_usage.get("external_call_count", 0),
        "external_call_scope": "Tracked research HTTP calls; model/embedding calls counted separately; account and database I/O excluded",
        "account_io": bool(user),
        "context_api_usage": context_usage, "research_api_usage": research_usage,
        "estimated_usd": round((context_usage.get("estimated_usd") or 0)
                               + (research_usage.get("estimated_usd") or 0), 8),
        "synthesis_context": result.get("execution_trace", {}).get("synthesis_context", {}),
        "research_seconds": result.get("research_seconds", 0),
        "synthesis_seconds": result.get("synthesis_seconds", 0),
        "unpriced_calls": (context_usage.get("unpriced_calls") or 0)
                          + (research_usage.get("unpriced_calls") or 0),
    }
    print("MKH_REQUEST_USAGE " + json.dumps(metrics, separators=(",", ":")), flush=True)
    response = JSONResponse({"answer": answer, "evidence": public_evidence(result),
                             "standalone_question": standalone, "conversation_id": cid,
                             "position": position, "saved": bool(store and not save_error),
                             "save_error": save_error,
                             "metrics": metrics,
                             "geography": (result.get("geography") or {}).get("assumption")})
    return with_session(response, refreshed)


async def country(request):
    params=request.query_params
    question=params.get('q')
    if question:
        if len(question)>MAX_QUESTION:return error('Country question is too long.')
        result=await asyncio.to_thread(lambda:country_foundation().answer(question,synthesis_language(question)))
        if result is None:return error('Use a supported country population, geography, indicator or climate question.',422)
        return JSONResponse(result)
    metric=params.get('metric')
    foundation=await asyncio.to_thread(country_foundation)
    if not metric:
        report={k:v for k,v in foundation.validation.items() if k!='population_rollups'}
        from country_indicators import indicator_package
        from country_climate import climate_package
        from country_physical import physical_package
        indicators=indicator_package()
        climate=climate_package()
        physical=physical_package()
        return JSONResponse({'validation':report,'metrics':['population','ranking','area','neighbours','residence','indicator','geometry','climate','terrain','physical_rivers','river_geometry','terrain_raster'],
            'physical':{'sources':{k:{field:s[field] for field in ('dataset_id','provider','version','source_page','license','limitations')} for k,s in physical['sources'].items()},'quality':physical['quality']},
            'climate':{k:climate[k] for k in ('dataset_id','source_version','reference_period','geographic_framework','variables','quality_checks','limitations')},
            'indicators':[{'id':s['indicator_id'],'name':s['metadata']['name'],'unit':s['unit'],'domain':s['domain']} for s in indicators['series']]})
    if metric in ('terrain','physical_rivers','river_geometry','terrain_raster'):
        from country_physical import physical_query,physical_evidence,river_geometry,raster_path
        if any(params.get(k) for k in ('year','period','scope','scope_level')):
            return error('Physical sources have fixed versions and geography; no temporal substitution or administrative allocation.')
        name=params.get('name');level=params.get('level','country');river_id=params.get('river_id')
        if name and len(name)>200:return error('Place/river name is too long.')
        if level not in ('country','region'):return error('Physical summaries support country/region only.')
        if metric!='terrain' and level!='country':return error('River/raster selection supports national context only.')
        try:
            if metric=='river_geometry':return JSONResponse(river_geometry(name,river_id),media_type='application/geo+json')
            if metric=='terrain_raster':
                if name or river_id:return error('Raster is the fixed country-only terrain subset.')
                return FileResponse(raster_path(),media_type='image/tiff',filename='Mali_ETOPO2022_60s_COD_v03.tif')
            data=physical_query(metric,[name] if name else None,level,river_id)
        except ValueError:return error('Unsupported physical source selection.')
        return JSONResponse({'country':data,'evidence':physical_evidence(data) if data['rows'] else []})
    if metric=='climate':
        from country_climate import climate_query,climate_evidence
        if (any(params.get(k) for k in ('year','scope','scope_level'))
                or params.get('level','country')!='country' or params.get('name','Mali').casefold()!='mali'):
            return error('Climate normals cover national Mali, 1991–2020 only; no single-year or administrative allocation.')
        try:
            variables=params['variables'].split(',') if params.get('variables') else None
            month=int(params['month']) if params.get('month') else None
            data=climate_query(variables,params.get('aggregation','both'),params.get('period','1991-2020'),month)
        except ValueError:return error('Choose valid climate variables, annual/monthly/both, period 1991-2020 and optional monthly month 1–12.')
        return JSONResponse({'country':data,'evidence':climate_evidence(data)})
    if metric=='indicator':
        from country_indicators import indicator_query,indicator_evidence
        code=params.get('indicator')
        if not code:return error('Specify an indicator code.')
        try:
            year=int(params['year']) if params.get('year') else None
            if year and not 1900<=year<=2100:raise ValueError()
            data=indicator_query([code],[year] if year else None,params.get('series')=='true')
        except ValueError:return error('Unknown indicator or invalid year.')
        return JSONResponse({'country':data,'evidence':indicator_evidence(data)})
    if metric not in {'population','ranking','area','neighbours','residence','geometry'}:
        return error('Unknown country metric.')
    level=params.get('level');scope_level=params.get('scope_level')
    if any(v and v not in {'country','region','cercle','commune','arrondissement','locality'} for v in (level,scope_level)):
        return error('Unknown geographic level.')
    name=params.get('name');scope=params.get('scope')
    if any(v and len(v)>200 for v in (name,scope)):return error('Place name is too long.')
    try:
        limit=int(params.get('limit','20'))
        if not 1<=limit<=50:raise ValueError()
    except ValueError:return error('Choose a limit from 1 to 50.')
    order=params.get('order','desc')
    if order not in {'asc','desc'}:return error('Choose asc or desc.')
    if not level:return error('Specify an administrative level.')
    if metric=='geometry':
        data=await asyncio.to_thread(foundation.geometry,level,name)
        return JSONResponse(data,media_type='application/geo+json')
    if metric in ('population','ranking'):
        data=await asyncio.to_thread(foundation.population_rows,level,name,scope_level,scope,order,limit,metric=='ranking')
    elif metric=='residence':
        data=await asyncio.to_thread(foundation.residence,name or 'Mali',level)
    else:
        data=await asyncio.to_thread(foundation.spatial_rows,metric,level,name)
    evidence=[foundation.evidence(data,metric)] if data['status']=='ok' else []
    return JSONResponse({'country':data,'evidence':evidence})


async def geography(request):
    """Public aggregate geographic summaries; no credentials or user data."""
    model = await asyncio.to_thread(geographic_model)
    name = request.query_params.get("name")
    level = request.query_params.get("level")
    release = request.query_params.get("release")
    if level and level not in {"country", "region", "cercle", "commune", "arrondissement", "locality"}:
        return error("Unknown administrative level.")
    if release and release not in model.releases:
        return error("Unknown geographic release.", 404)
    if name:
        if len(name) > 150:
            return error("Place name is too long.")
        matches = model.lookup(name, level, release or model.preferred)
        return JSONResponse({"matches": matches[:50], "total_matches": len(matches), "truncated": len(matches)>50})
    uid = request.query_params.get("unit_id")
    if uid:
        if uid not in model.units:
            return error("Place not found.", 404)
        children = [model.describe(c) for c in model.children[uid]]
        return JSONResponse({"unit": model.describe(uid), "children": children[:200],
            "total_children": len(children), "truncated": len(children)>200})
    return JSONResponse(model.summary())


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


async def source_page(request):
    return FileResponse(WEB / "sources.html", headers={"Cache-Control": "no-store"})


def source_inventory_db():
    if not setting('SUPABASE_URL') or not setting('SUPABASE_SECRET_KEY'):
        raise RuntimeError('Document registry is not configured')
    return create_client(setting('SUPABASE_URL'), setting('SUPABASE_SECRET_KEY'),
                         options=ClientOptions(auto_refresh_token=False, persist_session=False))


async def sources(request):
    from source_inventory import inventory
    return JSONResponse(await asyncio.to_thread(inventory, source_inventory_db))


async def admin(request):
    return FileResponse(WEB / "admin.html", headers={"Cache-Control": "no-store"})


def admin_store():
    from admin_accounts import AdminStore
    if not setting('SUPABASE_URL') or not setting('SUPABASE_SECRET_KEY'):
        raise RuntimeError('Administration is not configured')
    db = create_client(setting('SUPABASE_URL'), setting('SUPABASE_SECRET_KEY'),
                       options=ClientOptions(auto_refresh_token=False, persist_session=False))
    bootstrap = {e.strip().casefold() for e in setting('MKH_ADMIN_EMAILS').split(',') if e.strip()}
    return AdminStore(db, bootstrap)


async def admin_actor(request):
    user, token, refreshed = await actor(request)
    if not verified_email_user(user):
        return None, None, refreshed, error('Sign in with a verified email account.', 401)
    try:
        store = admin_store()
        if not await asyncio.to_thread(store.is_admin, user.id):
            return None, None, refreshed, error('Administrator access is required.', 403)
    except Exception:
        return None, None, refreshed, error('Administrator access could not be checked. Try again later.', 503)
    return user, store, refreshed, None


async def admin_status(request):
    user, _, refreshed = await actor(request)
    if not verified_email_user(user):
        return JSONResponse({'authenticated': False, 'is_admin': False})
    try:
        store = admin_store()
        allowed = await asyncio.to_thread(store.is_admin, user.id)
        pending = None if allowed else await asyncio.to_thread(store.pending, user.email)
        return with_session(JSONResponse({'authenticated': True, 'is_admin': allowed,
                'email': user.email, 'pending_invitation': pending}), refreshed)
    except Exception:
        return error('Administration is temporarily unavailable.', 503)


async def admin_overview(request):
    user, store, refreshed, denied = await admin_actor(request)
    if denied: return denied
    try:
        result = await asyncio.to_thread(store.overview)
        return with_session(JSONResponse(result), refreshed)
    except Exception:
        return error('The administration registry is unavailable.', 503)


async def admin_invite(request):
    payload = await body(request)
    if payload is None: return error('Invalid request.',403)
    user, store, refreshed, denied = await admin_actor(request)
    if denied: return denied
    email = account_email(payload)
    if not email: return error('Enter a valid email address.')
    async with _admin_limit:
        try:
            invitation = await asyncio.to_thread(store.create, user.id, email)
        except Exception:
            return error('An invitation already exists, the recipient is already an admin, or the invitation could not be created.',409)
        try:
            if not invitation['existing']:
                await asyncio.to_thread(store.db.auth.admin.invite_user_by_email, email,
                                        {'redirect_to': auth_redirect()})
            elif invitation['confirmed']:
                await asyncio.to_thread(auth_client().auth.sign_in_with_otp, {'email': email,
                    'options': {'should_create_user': False, 'email_redirect_to': auth_redirect()}})
            else:
                await asyncio.to_thread(auth_client().auth.resend, {'type':'signup','email':email,
                    'options': {'email_redirect_to': auth_redirect()}})
            await asyncio.to_thread(store.delivered, invitation['id'], True)
        except Exception as exc:
            try: await asyncio.to_thread(store.delivered, invitation['id'], False)
            except Exception: pass
            return provider_failure(exc, 'The invitation email could not be sent. No administrator rights were granted. Revoke any pending invitation before trying again.')
    return with_session(JSONResponse({'message':'Invitation email requested. The recipient must verify their email, choose a password and accept before administrator access is granted.'},status_code=201),refreshed)


def valid_id(value):
    try: return str(uuid.UUID(str(value))) == value
    except (ValueError, TypeError, AttributeError): return False


async def admin_accept(request):
    payload = await body(request)
    if payload is None: return error('Invalid request.',403)
    user, _, _ = await actor(request)
    if not verified_email_user(user): return error('Sign in with the invited email first.',401)
    invite_id = payload.get('invitation_id')
    if not valid_id(invite_id) or not valid_new_password(payload.get('password')):
        return error('Choose a password of 12–256 characters and open a valid invitation.')
    async with _admin_limit:
        try:
            store = admin_store()
            if await asyncio.to_thread(store.check, user.id, invite_id) is not True:
                return error('This invitation has expired, was revoked, was already used or belongs to another account.',403)
        except Exception:
            return error('This invitation could not be checked.',503)
        saved = await update_password(request)
        if saved.status_code != 200: return saved
        try:
            if await asyncio.to_thread(store.accept, user.id, invite_id) is not True:
                raise ValueError('No grant')
            result = JSONResponse({'message':'Your administrator account is ready. Sign in next time using your email and password.'})
        except Exception:
            result = error('Your password was saved, but the invitation is no longer available. Ask an administrator for a new invitation.',409)
        for cookie in saved.headers.getlist('set-cookie'):
            result.headers.append('set-cookie',cookie)
        return result


async def admin_revoke(request):
    if await body(request) is None: return error('Invalid request.',403)
    user, store, refreshed, denied = await admin_actor(request)
    if denied: return denied
    iid = request.path_params['invitation_id']
    if not valid_id(iid): return error('Invalid invitation.')
    try:
        await asyncio.to_thread(store.revoke, user.id, iid)
        return with_session(JSONResponse({'message':'Invitation revoked.'}),refreshed)
    except Exception:
        return error('This invitation is no longer pending.',409)


async def admin_upload(request):
    if not same_origin(request): return error('Invalid request.',403)
    user, store, refreshed, denied = await admin_actor(request)
    if denied: return denied
    if request.headers.get('content-type','').split(';',1)[0]!='application/octet-stream':
        return error('Send a binary document.',415)
    filename = unquote(request.headers.get('x-mkh-filename',''))
    if not filename or len(filename)>250: return error('Enter a supported filename.')
    if not setting('OPENAI_API_KEY'): return error('Document processing is not configured.',503)
    from ingestion import create_job, DuplicateDocumentError, MAX_BYTES
    from ingestion_worker import schedule_job
    async with _admin_limit:
        raw = bytearray()
        try:
            async for part in request.stream():
                if len(raw)+len(part)>MAX_BYTES: return error('Documents must be smaller than 20 MB.',413)
                raw.extend(part)
            job_id = await asyncio.to_thread(create_job, store.db, filename, bytes(raw), user.id)
            await asyncio.to_thread(store.audit,user.id,'document_uploaded',job_id)
            schedule_job(setting('SUPABASE_URL'),setting('SUPABASE_SECRET_KEY'),setting('OPENAI_API_KEY'),job_id)
            return with_session(JSONResponse({'job_id':job_id,'message':'Original stored privately. Processing queued; it becomes searchable only when ready.'},status_code=202),refreshed)
        except DuplicateDocumentError as exc: return error(str(exc),409)
        except ValueError as exc: return error(str(exc),422)
        except Exception: return error('The document could not be queued. Check the registry before retrying.',503)
        finally: raw.clear()


async def admin_reprocess(request):
    payload = await body(request)
    if payload is None: return error('Invalid request.',403)
    user, store, refreshed, denied = await admin_actor(request)
    if denied: return denied
    job_id = request.path_params['job_id']
    if not valid_id(job_id): return error('Invalid job.')
    if not setting('OPENAI_API_KEY'): return error('Document processing is not configured.',503)
    from ingestion import reviewed_metadata
    from ingestion_worker import schedule_job
    corrections = payload.get('corrections')
    if corrections is not None and not isinstance(corrections,dict): return error('Invalid metadata corrections.')
    try: reviewed_metadata({}, {}, corrections)
    except (ValueError,TypeError): return error('Enter valid metadata corrections.')
    try:
        job = await asyncio.to_thread(lambda: store.db.table('ingestion_jobs').select('id,status').eq('id',job_id).limit(1).execute().data)
        if not job: return error('Job not found.',404)
        if job[0]['status'] not in ('ready','failed','partially processed','queued'): return error('This job is already processing.',409)
        await asyncio.to_thread(store.audit,user.id,'document_reprocess_requested',job_id)
        started = schedule_job(setting('SUPABASE_URL'),setting('SUPABASE_SECRET_KEY'),setting('OPENAI_API_KEY'),job_id,corrections=corrections)
        return with_session(JSONResponse({'message':'Processing requested.' if started else 'This job is already processing.'},status_code=202 if started else 409),refreshed)
    except Exception: return error('Processing could not be requested.',503)


async def admin_source_request(request):
    payload = await body(request)
    if payload is None: return error('Invalid request.',403)
    user, store, refreshed, denied = await admin_actor(request)
    if denied: return denied
    from admin_accounts import source_request
    try: data = source_request(payload)
    except ValueError as exc: return error(str(exc))
    try:
        rid = await asyncio.to_thread(store.source_request,user.id,data)
        return with_session(JSONResponse({'id':rid,'message':'Source registered for connector review. No data has been fetched or published.'},status_code=201),refreshed)
    except Exception: return error('The source request could not be saved.',503)


routes = [
    Route('/api/admin/status',admin_status),
    Route('/api/admin/overview',admin_overview),
    Route('/api/admin/invitations',admin_invite,methods=['POST']),
    Route('/api/admin/invitations/accept',admin_accept,methods=['POST']),
    Route('/api/admin/invitations/{invitation_id}',admin_revoke,methods=['DELETE']),
    Route('/api/admin/documents',admin_upload,methods=['POST']),
    Route('/api/admin/documents/{job_id}/reprocess',admin_reprocess,methods=['POST']),
    Route('/api/admin/source-requests',admin_source_request,methods=['POST']),
    Route("/api/health", health),
    Route("/api/sources", sources),
    Route("/sources", source_page),
    Route("/api/geography", geography),
    Route("/api/country", country),
    Route("/api/me", me),
    Route("/api/auth/status", auth_status),
    Route("/api/auth/signup", signup, methods=["POST"]),
    Route("/api/auth/resend", resend_confirmation, methods=["POST"]),
    Route("/api/auth/login", password_login, methods=["POST"]),
    Route("/api/auth/recover", recover_password, methods=["POST"]),
    Route("/api/auth/password", update_password, methods=["POST"]),
    Route("/api/auth/email", email_link, methods=["POST"]),
    Route("/api/auth/session", accept_link, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/chat", chat, methods=["POST"]),
    Route("/api/attachments/extract", extract_attachment, methods=["POST"]),
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
    asyncio.create_task(asyncio.to_thread(publish_operational_logged))
    asyncio.create_task(asyncio.to_thread(publish_analytical_logged))
    asyncio.create_task(asyncio.to_thread(publish_project_learning_logged))
    asyncio.create_task(asyncio.to_thread(publish_eu_logged))
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
