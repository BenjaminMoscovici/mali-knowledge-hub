"""Rank published catalogue entries, passages and selected record labels in one index."""

import asyncio
import base64
import math
import re
import time
import unicodedata
from collections import Counter

import httpx


def normalize(value):
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(value).casefold())
        if not unicodedata.combining(char)
    )


def tokens(value):
    return re.findall(r"[^\W_]+", normalize(value).replace("_", " "), re.UNICODE)


# Function words carry little evidence for matching sections across languages.
SEARCH_STOP = set("a an and are as at be by can de des du en et for how in is la le les of on or ou par pour que quel quelle quels quelles qui sur the to un une what which who with comment est il elle peut ont".split())


def chunks(text, size=1700, overlap=200):
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        yield start, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


class SearchIndex:
    def __init__(self, sources, profiles=None):
        self.entries = []
        embedded = []
        self.vector_rows = []
        for source in sources.values():
            labels = " ".join([source["title"], source["id"], source["publisher"], *source["topics"]])
            fields = list(source.get("columns", {})) + [
                f"{code} {series['label']}" for code, series in source.get("series", {}).items()
            ]
            for key, value in source.get("definitions", {}).items():
                if isinstance(value, dict):
                    fields.append(f"{key} {value.get('label', '')} {value.get('unit', '')}")
            for field, profile in (profiles or {}).get(source["id"], {}).items():
                fields.append(field + " " + " ".join(map(str, profile["examples"])))
            snapshot = source.get("document_snapshot", {})
            fields.extend(snapshot.get("keywords", []))
            fields.extend(str(value) for value in snapshot.get("metadata", {}).values())
            self.add("source", source, None, labels, " ".join([
                source["description"], source["geography"], source["period"], *fields,
            ]))
            for passage in source.get("passages", []):
                if "embedding" in passage:
                    import numpy as np
                    vec = np.frombuffer(base64.b64decode(passage["embedding"], validate=True), dtype="<f2")
                    if vec.shape != (128,) or not np.isfinite(vec).all():
                        raise ValueError("Invalid document section embedding")
                    self.vector_rows.append(len(self.entries))
                    embedded.append(vec)
                    self.add("passage", source, (passage, 0, passage["text"]),
                             " ".join([source["title"], *passage["path"], *passage["topics"]]), passage["text"])
                    continue
                for start, text in chunks(passage["text"]):
                    self.add("passage", source, (passage, start, text),
                             " ".join([source["title"], passage["locator"], *passage.get("topics", [])]), text)
            for row in source.get("records", []):
                if source.get("search_fields"):
                    values = [str(row[key]) for key in source["search_fields"] if row.get(key) is not None]
                    self.add("record", source, row, " ".join(values), source["title"])
        self.vector_matrix = None
        self.precomputed = frozenset(self.vector_rows)
        if embedded:
            self.vector_matrix = np.asarray(embedded, dtype="float32")
        self.catalogue = {e["source"]["id"]: e for e in self.entries if e["kind"] == "source"}
        self.df = Counter(term for entry in self.entries for term in entry["counts"])
        self.stem_terms = {}
        self.stemmer = None
        if self.precomputed:
            import snowballstemmer
            self.stemmer = snowballstemmer.stemmer("french")
            for term in self.df:
                if len(term) >= 4 and term.isalpha():
                    self.stem_terms.setdefault(self.stemmer.stemWord(term), []).append(term)
        self.mean_length = sum(e["length"] for e in self.entries) / max(1, len(self.entries))

    def add(self, kind, source, payload, heading, body):
        words = tokens(heading) * 2 + tokens(body)
        text = heading + "\n" + body
        self.entries.append({"kind": kind, "source": source, "payload": payload, "counts": Counter(words),
                             "length": len(words), "text": text[:4500]})

    def rank(self, query, kind, limit, source_id=None, source_type=None, affinities=None):
        terms = set(tokens(query))
        candidates = [i for i, e in enumerate(self.entries) if (kind is None or e["kind"] == kind)
                      and (not source_id or e["source"]["id"] == source_id)
                      and (not source_type or e["source"]["type"] == source_type)]
        if not terms:
            return [self.entries[i] for i in candidates[:limit]]
        terms = terms - SEARCH_STOP or terms
        related = {}
        if self.stemmer:
            for term in terms:
                for variant in self.stem_terms.get(self.stemmer.stemWord(term), []):
                    if variant not in terms:
                        related[variant] = .85
        lexical = {}
        exact_headings = {}
        phrase = " ".join(tokens(query))
        for i in candidates:
            e = self.entries[i]
            scale = 1.2 * (0.25 + 0.75 * e["length"] / max(1, self.mean_length))
            score = sum(math.log1p((len(self.entries) - self.df[t] + 0.5) / (self.df[t] + 0.5))
                        * f * 2.2 / (f + scale) for t in terms if (f := e["counts"].get(t)))
            if i in self.precomputed:
                score += sum(weight * math.log1p((len(self.entries)-self.df[t]+.5)/(self.df[t]+.5))
                             * f * 2.2/(f+scale) for t,weight in related.items() if (f:=e["counts"].get(t)))
            if score:
                lexical[i] = score
            if i in self.precomputed and e["payload"][0]["path"]:
                heading = " ".join(tokens(e["payload"][0]["path"][-1]))
                if phrase == heading:
                    exact_headings[i] = 1
        semantic = {i: affinities[i] for i in candidates if affinities is not None and affinities.get(i, 0) >= 0.26}
        if self.vector_matrix is not None and kind in (None,"passage"):
            scores = self.document_scores(query)
            for i in candidates:
                if i in self.precomputed and scores.get(i, 0) >= 0.23:
                    semantic[i] = scores[i]
        # For discovery, take the best hit per release in each ranking. A source
        # with multiple formats or many similar rows still gets one vote per channel.
        ranks = Counter()
        for scores, weight in ((lexical, 1.6), (semantic, 1), (exact_headings, 4)):
            ordered = sorted(scores, key=scores.get, reverse=True)
            if kind is None:
                ordered = list(dict.fromkeys(self.entries[i]["source"]["id"] for i in ordered))
            for rank, key in enumerate(ordered):
                ranks[key] += weight / (6 + rank)
        ranked = [key for key, _ in ranks.most_common(limit)]
        if kind is None:
            return [self.catalogue[key] for key in ranked]
        return [self.entries[i] for i in ranked]

    def document_scores(self, query):
        from document_vectors import encode
        import numpy as np
        # Elementwise contraction avoids a multithreaded BLAS operation per guest query.
        similarities = np.einsum("ij,j->i", self.vector_matrix, encode(query))
        return dict(zip(self.vector_rows, similarities.tolist()))

    def find_sources(self, query, limit, source_type, affinities):
        kind = None if query.strip() else "source"
        return self.rank(query, kind, limit, source_type=source_type, affinities=affinities)


class EmbeddingBudgetReached(Exception):
    pass


class SemanticSearch:
    """Keep only published text vectors between requests. Query vectors live for one assignment."""

    MODEL = "text-embedding-3-small"
    DIMENSIONS = 256
    RATE_PER_MILLION = 0.02

    def __init__(self, index, client, key):
        self.index = index
        self.client = client
        self.key = key
        self.vectors = {}
        self.lock = asyncio.Lock()
        self.retry_after = 0

    async def embed(self, texts, usage, allowed=None):
        if allowed and not allowed(texts):
            raise EmbeddingBudgetReached
        response = await self.client.post("https://api.openai.com/v1/embeddings",
            headers={"Authorization": "Bearer " + self.key},
            json={"model": self.MODEL, "input": texts, "dimensions": self.DIMENSIONS}, timeout=6)
        response.raise_for_status()
        payload = response.json()
        usage["embedding_tokens"] += payload["usage"]["total_tokens"]
        items = sorted(payload["data"], key=lambda x: x["index"])
        if [x["index"] for x in items] != list(range(len(texts))):
            raise ValueError("Incomplete embedding batch")
        vectors = []
        for item in items:
            vec = item["embedding"]
            if len(vec) != self.DIMENSIONS or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in vec):
                raise ValueError("Invalid embedding vector")
            vectors.append(vec)
        return vectors

    async def search(self, query, cache, usage, allowed=None, *, kind=None, source_id=None, source_type=None):
        if not query.strip():
            return None
        selection = (query, kind, source_id, source_type)
        if selection in cache:
            return cache[selection]
        candidates = [i for i, entry in enumerate(self.index.entries)
                      if i not in self.index.precomputed and (not kind or entry["kind"] == kind)
                      and (not source_id or entry["source"]["id"] == source_id)
                      and (not source_type or entry["source"]["type"] == source_type)]
        if not candidates:
            return None
        if time.monotonic() < self.retry_after:
            usage["retrieval_fallback"] = True
            return None
        try:
            async with self.lock:
                missing = [i for i in candidates if i not in self.vectors]
                for offset in range(0, len(missing), 64):
                    batch = missing[offset:offset + 64]
                    vectors = await self.embed([self.index.entries[i]["text"] for i in batch], usage, allowed)
                    self.vectors.update(zip(batch, vectors))
            if query not in cache:
                cache[query], = await self.embed([query], usage, allowed)
            scores = {i: sum(x * y for x, y in zip(self.vectors[i], cache[query])) for i in candidates}
            cache[selection] = scores
            return scores
        except EmbeddingBudgetReached:
            usage["retrieval_fallback"] = True
            return None
        except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError):
            self.retry_after = time.monotonic() + 90
            usage["retrieval_fallback"] = True
            return None
