"""Private conversation storage through the caller's Supabase Auth JWT and RLS.

This module never uses the service-role credential. The shared evidence corpus
is referenced by ID and provenance, rather than copied into user histories.
"""

import requests


class ResearchStoreError(RuntimeError):
    pass


class ResearchStore:
    def __init__(self, url, publishable_key, access_token, user_id, session=None):
        if not all((url, publishable_key, access_token, user_id)):
            raise ResearchStoreError("Private research is not configured.")
        self.base = url.rstrip("/") + "/rest/v1"
        self.user_id = user_id
        self.session = session or requests.Session()
        self.headers = {
            "apikey": publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _request(self, method, table, *, params=None, payload=None):
        try:
            response = self.session.request(
                method, f"{self.base}/{table}", headers=self.headers,
                params=params, json=payload, timeout=15,
            )
            response.raise_for_status()
            return response.json() if response.content else []
        except (requests.RequestException, ValueError):
            # Response bodies can contain sensitive user text; keep them out of
            # exception messages and service logs.
            raise ResearchStoreError("Conversation storage is unavailable.") from None

    def list_conversations(self):
        rows = []
        while True:
            page = self._request("GET", "mkh_user_conversations", params={
                "select": "id,title,analysis_mode,archived_at,created_at,updated_at",
                "user_id": f"eq.{self.user_id}",
                "order": "updated_at.desc,id.desc", "limit": "200",
                "offset": str(len(rows)),
            })
            rows.extend(page)
            if len(page) < 200:
                return rows

    def list_messages(self, conversation_id):
        rows = []
        while True:
            page = self._request("GET", "mkh_user_messages", params={
                "select": "id,position,role,content,standalone_question,analysis_mode,evidence_refs,created_at",
                "user_id": f"eq.{self.user_id}",
                "conversation_id": f"eq.{conversation_id}",
                "order": "position.asc", "limit": "500",
                "offset": str(len(rows)),
            })
            rows.extend(page)
            if len(page) < 500:
                return rows

    def create_conversation(self, conversation_id, title, mode):
        rows = self._request("POST", "mkh_user_conversations", payload={
            "id": conversation_id, "user_id": self.user_id,
            "title": title[:120], "analysis_mode": mode,
        })
        if len(rows) != 1:
            raise ResearchStoreError("Conversation was not saved.")
        return rows[0]

    def update_conversation(self, conversation_id, **changes):
        allowed = {k: v for k, v in changes.items()
                   if k in {"title", "analysis_mode", "archived_at"}}
        if not allowed:
            return
        from datetime import datetime, timezone
        allowed["updated_at"] = datetime.now(timezone.utc).isoformat()
        rows = self._request("PATCH", "mkh_user_conversations", params={
            "id": f"eq.{conversation_id}", "user_id": f"eq.{self.user_id}",
        }, payload=allowed)
        if len(rows) != 1:
            raise ResearchStoreError("Conversation could not be updated.")

    def delete_conversation(self, conversation_id):
        rows = self._request("DELETE", "mkh_user_conversations", params={
            "id": f"eq.{conversation_id}", "user_id": f"eq.{self.user_id}",
        })
        if len(rows) != 1:
            raise ResearchStoreError("Conversation could not be deleted.")

    def save_exchange(self, conversation_id, position, question, standalone, answer,
                      mode, evidence_refs):
        # Refresh recency before the append. A successful append must never be
        # reported as failed merely because a later timestamp update times out.
        self.update_conversation(conversation_id, analysis_mode=mode)
        common = {"conversation_id": conversation_id, "user_id": self.user_id,
                  "analysis_mode": mode}
        payload = [
            {**common, "position": position, "role": "user",
             "content": question, "standalone_question": standalone},
            {**common, "position": position + 1, "role": "assistant",
             "content": answer, "evidence_refs": evidence_refs},
        ]
        try:
            rows = self._request("POST", "mkh_user_messages", payload=payload)
            if len(rows) == 2:
                return
        except ResearchStoreError:
            pass
        # A network timeout can happen after PostgREST commits the batch.
        # Verify exact rows before retrying so a duplicate does not strand it.
        existing = {row["position"]: row for row in self.list_messages(conversation_id)
                    if row["position"] in (position, position + 1)}
        if (existing.get(position, {}).get("role") == "user"
                and existing[position].get("content") == question
                and existing.get(position + 1, {}).get("role") == "assistant"
                and existing[position + 1].get("content") == answer):
            return
        raise ResearchStoreError("The exchange was not saved.")


REFERENCE_FIELDS = (
    "evidence_id", "source_type", "source_family", "document_id", "chunk_id",
    "document_title", "document_type", "organization", "publication_date",
    "valid_from", "valid_until", "version", "page", "section",
    "source_endpoint", "resource_hdx_id",
    "retrieved_at", "reference_period_start", "reference_period_end",
    "project_id", "record_id", "geographic_scope",
    "release_id", "locator", "geographic_precision",
)


def evidence_references(result):
    """Store provenance only; never copy source passages into a user's row."""
    refs = []
    for item in result.get("evidence", []):
        ref = {key: value for key in REFERENCE_FIELDS
               if (value := item.get(key)) is not None}
        if (item.get("source_type") != "knowledge_base_document"
                and not item.get("document_id") and not item.get("chunk_id")
                and item.get("content")):
            # Structured API records and generated inventory snapshots are
            # short evidence excerpts, not copies of source documents.
            ref["source_excerpt"] = str(item["content"])[:1500]
        refs.append(ref)
    return refs


def hydrate_saved_evidence(result, fetch_chunks, batch_size=100):
    """Resolve saved document references on demand from the shared corpus.

    `fetch_chunks` receives a small list of chunk IDs and returns rows with
    `id` and `content`. Missing or retired chunks keep their provenance but
    do not acquire a misleading passage from some other source.
    """
    refs = result.get("evidence") or []
    chunk_ids = list(dict.fromkeys(
        ref["chunk_id"] for ref in refs if ref.get("chunk_id") is not None
    ))
    passages = {}
    for start in range(0, len(chunk_ids), batch_size):
        for chunk in fetch_chunks(chunk_ids[start:start + batch_size]):
            passages[str(chunk["id"])] = chunk["content"]
    for ref in refs:
        if ref.get("chunk_id") is not None:
            ref["content"] = passages.get(str(ref["chunk_id"]))
    result["passages_loaded"] = True
    return len(passages)
