"""Project-scoped Supabase Auth and application-owned conversation state."""

import hmac
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from knowledge import Evidence, json_text

CONVERSATIONS = "/rest/v1/mkh_v3_conversations"
ATTEMPTS = "/rest/v1/mkh_v3_attempts"
COOKIE = "mkh_v3_session"
GUEST_COOKIE = "mkh_v3_guest"
EMAIL_FLOW_COOKIE = "mkh_v3_email_flow"
PASSWORD_COOKIE = "mkh_v3_password_setup"
TOP_TURNS = 12
DAILY_ASSIGNMENTS = 8


class StateError(ValueError):
    pass


class SupabaseState:
    def __init__(self, client, url, key):
        self.client = client
        self.url = url.rstrip("/")
        self.key = key

    async def request(self, method, path, *, token=None, **kwargs):
        headers = {"apikey": self.key, **kwargs.pop("headers", {})}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = await self.client.request(method, self.url + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise StateError("V3 sign-in or saved conversations are temporarily unavailable.") from None
        return response

    async def send_password_link(self, operation, email, password, challenge, redirect):
        payload = {"email": email, "code_challenge": challenge, "code_challenge_method": "s256"}
        if operation == "signup":
            payload["password"] = password
        response = await self.request("POST", "/auth/v1/" + operation, json=payload,
                                      params={"redirect_to": redirect})
        if response.is_success:
            return
        code = self.error_code(response)
        if response.status_code == 429 or code in {"over_email_send_rate_limit", "over_request_rate_limit"}:
            raise StateError("Too many email requests. Use your latest link or wait before requesting another.")
        if code == "email_address_not_authorized":
            raise StateError("Account emails are available to V3 Supabase team addresses during the preview.")
        if code in {"user_already_exists", "email_exists"}:
            raise StateError("Use Sign in or Forgot password for this email address.")
        if code == "weak_password":
            raise StateError("Choose a stronger V3 password.")
        raise StateError("V3 could not send the email. Try again shortly.")

    async def sign_in(self, email, password):
        response = await self.request("POST", "/auth/v1/token", params={"grant_type": "password"},
                                      json={"email": email, "password": password})
        if not response.is_success:
            if self.error_code(response) == "email_not_confirmed":
                raise StateError("Open the verification link in your V3 signup email.")
            if response.status_code == 429:
                raise StateError("Too many sign-in attempts. Try again shortly.")
            raise StateError("Check your email and password. Use Forgot password to set or reset it.")
        return self.session(response)

    async def exchange_code(self, code, verifier):
        response = await self.request("POST", "/auth/v1/token", params={"grant_type": "pkce"},
                                      json={"auth_code": code, "code_verifier": verifier})
        if not response.is_success:
            raise StateError("The email link expired or was opened in a different browser. Request a new link.")
        return self.session(response)

    async def set_password(self, token, password):
        response = await self.request("PUT", "/auth/v1/user", token=token, json={"password": password})
        if not response.is_success:
            if self.error_code(response) == "weak_password":
                raise StateError("Choose a stronger V3 password.")
            raise StateError("V3 could not set the password. Use the latest password setup link.")

    @staticmethod
    def session(response):
        payload = response.json()
        token = payload.get("access_token")
        age = payload.get("expires_in", 3600)
        if not isinstance(token, str) or not 1 <= len(token) <= 6000 or type(age) is not int:
            raise StateError("Supabase did not return a V3 session.")
        return token, max(1, min(3600, age))

    @staticmethod
    def error_code(response):
        try:
            return response.json().get("error_code")
        except (AttributeError, ValueError):
            return None

    async def user(self, token):
        if not token:
            return None
        response = await self.request("GET", "/auth/v1/user", token=token)
        if response.status_code in {400, 401, 403}:
            return None
        self.require(response)
        user = response.json()
        if user.get("id") and user.get("email_confirmed_at") and user.get("aud") == "authenticated":
            return user["id"]
        return None

    @staticmethod
    def require(response):
        if not response.is_success:
            raise StateError("Supabase could not complete the V3 state operation.")

    async def recent(self, token):
        response = await self.request("GET", CONVERSATIONS, token=token, params={
            "select": "id,title,updated_at", "order": "updated_at.desc", "limit": 40,
        })
        self.require(response)
        return response.json()

    async def load(self, token, conversation_id):
        response = await self.request("GET", CONVERSATIONS, token=token, params={
            "select": "id,title,turns,revision", "id": f"eq.{conversation_id}", "limit": 1,
        })
        self.require(response)
        rows = response.json()
        return rows[0] if rows else None

    async def save(self, token, conversation_id, title, turns, revision):
        body = {"turns": turns[-TOP_TURNS:], "revision": revision + 1, "updated_at": now()}
        headers = {"Prefer": "return=representation"}
        if revision == 0:
            response = await self.request("POST", CONVERSATIONS, token=token, headers=headers,
                                          json={"id": conversation_id, "title": title, **body})
        else:
            response = await self.request("PATCH", CONVERSATIONS, token=token, headers=headers,
                                          params={"id": f"eq.{conversation_id}", "revision": f"eq.{revision}"},
                                          json=body)
        if response.status_code == 409 or (response.is_success and not response.json()):
            raise StateError("The conversation changed in another session. Reopen it and try again.")
        self.require(response)

    async def delete(self, token, conversation_id):
        response = await self.request("DELETE", CONVERSATIONS, token=token,
                                      params={"id": f"eq.{conversation_id}"})
        self.require(response)

    async def reserve(self, token, daily_limit=DAILY_ASSIGNMENTS):
        after = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        response = await self.request("GET", ATTEMPTS, token=token,
                                      params={"select": "id", "attempted_at": f"gte.{after}", "limit": daily_limit})
        self.require(response)
        if len(response.json()) >= daily_limit:
            raise StateError("The preview's daily research allowance has been used. Try again tomorrow.")
        response = await self.request("POST", ATTEMPTS, token=token, json={"id": str(uuid4())})
        self.require(response)


@dataclass
class GuestChat:
    touched: float
    conversations: dict = field(default_factory=dict)
    attempts: deque = field(default_factory=deque)


class PreviewSessions:
    """Keep guest context in memory and bound admissions for the shared preview."""

    MAX_GUESTS = 128
    GUEST_IDLE_SECONDS = 3600
    DAILY_PREVIEW_ASSIGNMENTS = 64

    def __init__(self):
        self.guests = {}
        self.attempts = deque()

    def guest(self, key):
        current = time.monotonic()
        for expired in [k for k, v in self.guests.items() if current - v.touched >= self.GUEST_IDLE_SECONDS]:
            del self.guests[expired]
        if key and key in self.guests:
            self.guests[key].touched = current
            return key, self.guests[key], False
        if len(self.guests) >= self.MAX_GUESTS:
            del self.guests[min(self.guests, key=lambda k: self.guests[k].touched)]
        key = secrets.token_urlsafe(32)
        self.guests[key] = GuestChat(current)
        return key, self.guests[key], True

    def reserve(self, guest=None):
        current = time.monotonic()
        for slots in ([self.attempts, guest.attempts] if guest else [self.attempts]):
            while slots and current - slots[0] >= 86400:
                slots.popleft()
        if len(self.attempts) >= self.DAILY_PREVIEW_ASSIGNMENTS:
            raise StateError("The shared preview has reached its research limit. Try again later.")
        if guest and len(guest.attempts) >= DAILY_ASSIGNMENTS:
            raise StateError("This preview session has reached its research limit. Try again later.")
        self.attempts.append(current)
        if guest:
            guest.attempts.append(current)


def now():
    return datetime.now(timezone.utc).isoformat()


class History:
    """Verify history written by the companion before trusting prior answers or evidence."""

    def __init__(self, key, knowledge, web_enabled):
        self.key = hmac.digest(key.encode(), b"MKH V3 history signing v1", "sha256") if key else None
        self.knowledge = knowledge
        self.web_enabled = web_enabled

    def digest(self, conversation_id, owner_id, turn):
        if self.key is None:
            raise StateError("Research history signing is unavailable.")
        content = {field: value for field, value in turn.items() if field != "signature"}
        payload = json_text([conversation_id, owner_id, content]).encode()
        return hmac.digest(self.key, payload, "sha256").hex()

    def sign(self, conversation_id, owner_id, turn):
        return {**turn, "signature": self.digest(conversation_id, owner_id, turn)}

    def verified(self, conversation_id, owner_id, turn):
        signature = turn.get("signature")
        if not self.key or not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
            return False
        try:
            return hmac.compare_digest(signature, self.digest(conversation_id, owner_id, turn))
        except (TypeError, ValueError, RecursionError):
            return False

    def accessible(self, conversation_id, owner_id, turns):
        ledger = Evidence(self.knowledge, self.web_enabled)
        for turn in turns[-TOP_TURNS:]:
            if not isinstance(turn, dict) or not isinstance(turn.get("prompt"), str):
                continue
            prompt = turn["prompt"][:5000]
            if not self.verified(conversation_id, owner_id, turn):
                yield {"prompt": prompt}
                continue
            evidence = turn.get("evidence", [])
            if (turn.get("web_used") and not self.web_enabled) or not all(ledger.allowed(e) for e in evidence):
                yield {"prompt": prompt, "withdrawn": True}
                continue
            yield {**turn, "prompt": prompt}

    def context(self, accessible_turns):
        inputs, evidence = [], []
        for turn in accessible_turns[-5:]:
            inputs.append({"role": "user", "content": turn["prompt"][:3200]})
            if turn.get("answer") and turn.get("evidence"):
                inputs.append({"role": "assistant", "content": turn["answer"][:4500]})
                evidence.extend(turn["evidence"])
            elif turn.get("answer") and not turn.get("web_used"):
                inputs.append({"role": "assistant", "content": turn["answer"][:2500]})
        return inputs, evidence[-12:]
