"""Per-query API usage and estimated cost; no prompts or credentials are logged."""

from contextvars import ContextVar, copy_context
from threading import Lock
from time import perf_counter
from uuid import uuid4

QUERY_ID = ContextVar("mkh_query_id", default=None)
PHASE = ContextVar("mkh_phase", default="other")

# USD per million tokens, standard API tier, checked 2026-09-28.
PRICES = {
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "text-embedding-3-small": (0.02, 0.0, 0.0),
}


def submit(executor, function, *args):
    context = copy_context()
    return executor.submit(context.run, function, *args)


class MeteredAPI:
    def __init__(self, parent, endpoint):
        self.parent = parent
        self.endpoint = endpoint

    def create(self, **kwargs):
        started = perf_counter()
        response = getattr(self.parent.client, self.endpoint).create(**kwargs)
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "prompt_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        model = kwargs["model"]
        prices = PRICES.get(model)
        estimated = None
        if prices:
            estimated = round(((input_tokens - cached) * prices[0]
                               + cached * prices[1] + output_tokens * prices[2])
                              / 1_000_000, 8)
        record = {
            "endpoint": self.endpoint, "model": model,
            "phase": PHASE.get(), "input_tokens": input_tokens,
            "cached_input_tokens": cached, "output_tokens": output_tokens,
            "seconds": round(perf_counter() - started, 3),
            "estimated_usd": estimated,
        }
        self.parent.add(QUERY_ID.get(), record)
        return response


class MeteredOpenAI:
    def __init__(self, client):
        self.client = client
        self.lock = Lock()
        self.records = {}
        self.external = {}
        self.responses = MeteredAPI(self, "responses")
        self.embeddings = MeteredAPI(self, "embeddings")

    def begin(self):
        query_id = uuid4().hex
        with self.lock:
            self.records[query_id] = []
            self.external[query_id] = []
        return QUERY_ID.set(query_id), query_id

    def add(self, query_id, record):
        if query_id is None:
            return
        with self.lock:
            self.records[query_id].append(record)

    def add_external(self, query_id, record):
        if query_id is None:
            return
        with self.lock:
            self.external[query_id].append(record)

    def finish(self, token, query_id):
        QUERY_ID.reset(token)
        with self.lock:
            calls = self.records.pop(query_id)
            external_calls = self.external.pop(query_id)
        return {
            "calls": calls,
            "call_count": len(calls),
            "input_tokens": sum(c["input_tokens"] for c in calls),
            "output_tokens": sum(c["output_tokens"] for c in calls),
            "estimated_usd": round(sum(c["estimated_usd"] or 0 for c in calls), 8),
            "unpriced_calls": sum(c["estimated_usd"] is None for c in calls),
            "external_calls": external_calls,
            "external_call_count": len(external_calls),
        }
