"""Project-scoped Supabase Auth and application-owned conversation state."""

import hmac
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

from knowledge import Evidence, json_text

CONVERSATIONS = "/rest/v1/mkh_v3_conversations"
ATTEMPTS = "/rest/v1/mkh_v3_attempts"
COOKIE = "mkh_v3_session"
TOP_TURNS = 12


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

    async def send_code(self, email):
        response = await self.request("POST", "/auth/v1/otp", json={"email": email, "create_user": True})
        if response.is_success:
            return
        code = self.error_code(response)
        if response.status_code == 429 or code == "over_email_send_rate_limit":
            raise StateError("Too many code requests. Use your latest code or wait before requesting a new one.")
        if code == "email_address_not_authorized":
            raise StateError("Sign-in emails are available to V3 Supabase team email addresses.")
        raise StateError("V3 could not send a sign-in code. Try again shortly.")

    async def verify_code(self, email, code):
        response = await self.request("POST", "/auth/v1/verify", json={"email": email, "token": code, "type": "email"})
        if not response.is_success:
            raise StateError("That sign-in code is invalid or has expired. Use the code in the newest email.")
        payload = response.json()
        if not payload.get("access_token"):
            raise StateError("Supabase did not return a V3 session.")
        return payload["access_token"], max(1, min(3600, int(payload.get("expires_in", 3600))))

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

    async def reserve(self, token, daily_limit=8):
        after = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        response = await self.request("GET", ATTEMPTS, token=token,
                                      params={"select": "id", "attempted_at": f"gte.{after}", "limit": daily_limit})
        self.require(response)
        if len(response.json()) >= daily_limit:
            raise StateError("The preview's daily research allowance has been used. Try again tomorrow.")
        response = await self.request("POST", ATTEMPTS, token=token, json={"id": str(uuid4())})
        self.require(response)


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
