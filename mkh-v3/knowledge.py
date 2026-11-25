"""Published source discovery, evidence and bounded read-only analysis."""

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

CANON = Path(__file__).resolve().parent / "canon"
SQL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
SOURCE_ID = re.compile(r"[a-z][a-z0-9-]{0,89}\Z")
EVIDENCE_REF = re.compile(r"\[\[(E-[a-f0-9]{16})\]\]")
SOURCE_TYPES = {"document", "dataset", "reference", "live"}
SQL_TYPES = {"TEXT", "INTEGER", "REAL"}
SQL_FUNCTIONS = {
    "abs", "avg", "coalesce", "count", "date", "floor", "ifnull", "length", "like",
    "lower", "ltrim", "max", "min", "nullif", "replace", "round", "rtrim",
    "substr", "substring", "sum", "trim", "upper",
}
STOPWORDS = {
    "and", "are", "avec", "dans", "des", "est", "for", "from", "les", "par",
    "pour", "que", "sur", "that", "the", "this", "une", "what", "which", "with",
}


class KnowledgeError(ValueError):
    """A source or operation is unavailable within the published research boundary."""


def normalize(value):
    return "".join(
        char for char in unicodedata.normalize("NFKD", str(value).casefold())
        if not unicodedata.combining(char)
    )


def words(value):
    return set(re.findall(r"[a-z0-9]{2,}", normalize(value))) - STOPWORDS


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def https_url(url):
    try:
        parts = urlsplit(url)
        return parts.scheme == "https" and bool(parts.hostname) and not (parts.username or parts.password)
    except (TypeError, ValueError):
        return False


class Evidence:
    def __init__(self, knowledge, web_enabled, prior=()):
        self.knowledge = knowledge
        self.web_enabled = web_enabled
        self.items = {
            item["id"]: item for item in prior if self.allowed(item)
        }

    def allowed(self, item):
        if item.get("origin") == "public_web":
            return self.web_enabled and https_url(item.get("url"))
        source = self.knowledge.sources.get(item.get("source_id"))
        if not source or item.get("origin") != "canon" or item.get("release") != source["release"]:
            return False
        for input_release in item.get("data", {}).get("input_releases", []):
            current = self.knowledge.sources.get(input_release["source_id"])
            if current is None or current["release"] != input_release["release"]:
                return False
        return True

    def add(self, source, kind, locator, data, *, url=None, related_sources=()):
        item = {
            "origin": "canon",
            "source_id": source["id"],
            "title": source["title"],
            "publisher": source["publisher"],
            "release": source["release"],
            "source_period": source["period"],
            "geography": source["geography"],
            "url": url or source["url"],
            "kind": kind,
            "locator": locator,
            "data": data,
            "related_sources": list(related_sources),
        }
        return self._register(item)

    def add_web(self, url, title):
        if not self.web_enabled or not https_url(url):
            raise KnowledgeError("Web evidence is unavailable.")
        return self._register({
            "origin": "public_web", "kind": "external_reference",
            "url": url, "title": title, "locator": "External web result",
            "data": {"retrieved_at": datetime.now(timezone.utc).isoformat()},
        })

    def _register(self, item):
        identifier = "E-" + hashlib.sha256(json_text(item).encode()).hexdigest()[:16]
        item["id"] = identifier
        self.items[identifier] = item
        return item

    def citations(self, text):
        return [
            self.items[citation]
            for citation in dict.fromkeys(EVIDENCE_REF.findall(text))
            if citation in self.items
        ]


class Knowledge:
    def __init__(self, directory=CANON):
        self.sources = {}
        for path in sorted(Path(directory).glob("*.json")):
            source = json.loads(path.read_text(encoding="utf-8"))
            if source.get("review") != "published":
                continue
            if not SOURCE_ID.fullmatch(source["id"]) or source["id"] in self.sources:
                raise ValueError(f"Invalid published source ID in {path.name}")
            if not https_url(source["url"]) or source["type"] not in SOURCE_TYPES:
                raise ValueError(f"Invalid published source metadata in {path.name}")
            if source["type"] in {"dataset", "reference"}:
                self._validate_table(source, path.name)
            self.sources[source["id"]] = source

    @staticmethod
    def _validate_table(source, filename):
        columns = source["columns"]
        if not SQL_NAME.fullmatch(source["table"]) or not {"id", "locator"} <= columns.keys():
            raise ValueError(f"Invalid table metadata in {filename}")
        if not all(SQL_NAME.fullmatch(n) and t in SQL_TYPES for n, t in columns.items()):
            raise ValueError(f"Invalid table columns in {filename}")
        identifiers = [row["id"] for row in source["records"]]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError(f"Duplicate record ID in {filename}")

    def source(self, source_id):
        if not isinstance(source_id, str) or source_id not in self.sources:
            raise KnowledgeError("The requested source is outside the published catalogue.")
        return self.sources[source_id]

    @staticmethod
    def describes(source):
        return {k: v for k, v in source.items() if k not in {"passages", "records", "adapter", "join_group"}}

    def discover(self, query="", kind=None, limit=8):
        keywords = words(query)
        ranked = []
        for source in self.sources.values():
            if kind and kind != source["type"]:
                continue
            tags = source["topics"] + [source["title"], source["id"]]
            title_and_topics = words(" ".join(tags))
            description = words(" ".join((source["description"], source["geography"], source["period"])))
            score = 3 * len(keywords & title_and_topics) + len(keywords & description)
            if score or not keywords:
                ranked.append((score, source["title"], source))
        return [self.describes(source) for _, _, source in sorted(
            ranked, key=lambda entry: (-entry[0], entry[1])
        )[:limit]]

    def search_documents(self, query, source_id, ledger, limit=4):
        keywords = words(query)
        ranked = []
        sources = [self.source(source_id)] if source_id else self.sources.values()
        for source in sources:
            if source["type"] != "document":
                continue
            for passage in source["passages"]:
                tags = words(" ".join(passage.get("topics", [])))
                score = 3 * len(keywords & tags) + len(keywords & words(passage["text"]))
                if score or not keywords:
                    ranked.append((score, passage["page"], source, passage))
        results = []
        for _, _, source, passage in sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]:
            page_url = f"{source['url'].split('#')[0]}#page={passage['page']}"
            results.append(ledger.add(source, passage["kind"], passage["locator"], {
                "text": passage["text"][:6200], "page": passage["page"],
            }, url=page_url))
        return results

    def geography(self, name, level, ledger):
        normalized = normalize(name).strip()
        if not normalized:
            raise KnowledgeError("Provide an administrative place name.")
        candidates = []
        for source in self.sources.values():
            if source["type"] != "reference":
                continue
            for row in source["records"]:
                if normalize(row.get("place")) == normalized and (not level or level == row.get("level")):
                    candidates.append(ledger.add(source, "source_record", row["locator"], row))
        return candidates[:12]

    def inspect(self, source_id):
        source = self.source(source_id)
        detail = self.describes(source)
        if source["type"] in {"dataset", "reference"}:
            detail["row_count"] = len(source["records"])
            detail["samples"] = source["records"][:3]
        elif source["type"] == "document":
            detail["pages"] = [
                {"page": p["page"], "locator": p["locator"]} for p in source["passages"]
            ]
        return detail

    def query(self, source_ids, sql, ledger):
        if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 3:
            raise KnowledgeError("Select one to three published tables.")
        sources = [self.source(s) for s in dict.fromkeys(source_ids)]
        if any(s["type"] not in {"dataset", "reference"} for s in sources):
            raise KnowledgeError("SQL uses published structured datasets and reference tables.")
        groups = {s.get("join_group") for s in sources}
        if len(sources) > 1 and (len(groups) != 1 or None in groups):
            raise KnowledgeError("These releases have no approved shared join key. Query them separately.")
        if not isinstance(sql, str) or not 1 <= len(sql) <= 4000:
            raise KnowledgeError("Provide a single SQL SELECT, up to 4,000 characters.")

        conn = sqlite3.connect(":memory:")
        try:
            names = set()
            for source in sources:
                table, columns = source["table"], source["columns"]
                if table in names:
                    raise KnowledgeError("The selected table names collide.")
                names.add(table)
                definition = ", ".join(f'"{name}" {kind}' for name, kind in columns.items())
                conn.execute(f'CREATE TABLE "{table}" ({definition})')
                slots = ", ".join("?" for _ in columns)
                conn.executemany(f'INSERT INTO "{table}" VALUES ({slots})', (
                    tuple(row.get(key) for key in columns) for row in source["records"]
                ))
            conn.execute("PRAGMA query_only = ON")
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65536)
            conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 32)
            conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 32)
            conn.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 16)
            conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
            deadline = time.monotonic() + 0.35
            conn.set_progress_handler(lambda: time.monotonic() >= deadline, 500)

            def authorize(action, first, second, database, context):
                if action == sqlite3.SQLITE_SELECT:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_READ and first in names and database in {"main", None}:
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_FUNCTION and second and second.lower() in SQL_FUNCTIONS:
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY

            conn.set_authorizer(authorize)
            cursor = conn.execute(sql)
            if not cursor.description:
                raise KnowledgeError("The query must return a result set.")
            columns = [column[0] for column in cursor.description]
            if len(columns) != len(set(columns)):
                raise KnowledgeError("Use distinct output column names.")
            raw_rows = cursor.fetchmany(31)
            if any(isinstance(value, bytes) for row in raw_rows for value in row):
                raise KnowledgeError("Binary SQL results are outside the analytical result contract.")
            rows = [dict(zip(columns, row)) for row in raw_rows[:30]]
            if len(json_text(rows)) > 14000:
                raise KnowledgeError("The result is too large. Select fewer rows or columns.")
        except (sqlite3.Error, OverflowError, ValueError) as error:
            if isinstance(error, KnowledgeError):
                raise
            raise KnowledgeError("SQL was rejected or could not finish within its limits. Check the table, columns and SQL.") from None
        finally:
            conn.close()

        releases = [
            {"source_id": s["id"], "release": s["release"], "period": s["period"],
             "release_id": s.get("release_id"), "table": s["table"], "record_count": len(s["records"]),
             "url": s["url"]}
            for s in sources
        ]
        row_ids = {row.get("id") for row in rows if isinstance(row.get("id"), str)}
        input_locations = [
            {"source_id": s["id"], "id": row["id"], "locator": row["locator"]}
            for s in sources for row in s["records"] if row["id"] in row_ids
        ]
        return ledger.add(sources[0], "calculation", "Reproducible SQL over approved release snapshots", {
            "sql": sql, "input_releases": releases, "input_records": input_locations,
            "rows": rows, "truncated": len(raw_rows) > 30,
        }, related_sources=[s["id"] for s in sources[1:]])

    async def live(self, source_id, series_code, start_year, end_year, ledger, client: httpx.AsyncClient):
        source = self.source(source_id)
        if source["type"] != "live" or source.get("adapter") != "world_bank_wdi":
            raise KnowledgeError("This source has no enabled live connector.")
        if series_code not in source["series"]:
            raise KnowledgeError("The indicator is outside this published connection's coverage.")
        if (type(start_year) is not int or type(end_year) is not int
                or not 1960 <= start_year <= end_year <= date.today().year + 1
                or end_year - start_year > 25):
            raise KnowledgeError("Specify an inclusive year range spanning at most 26 observations.")
        country = source["country_code"]
        series = source["series"][series_code]
        endpoint = f"https://api.worldbank.org/v2/country/{country}/indicator/{series_code}"
        try:
            response = await client.get(endpoint, params={
                "format": "json", "date": f"{start_year}:{end_year}", "per_page": 30,
            }, timeout=8.0, follow_redirects=False)
            response.raise_for_status()
            if len(response.content) > 100000:
                raise ValueError("Upstream body too large")
            metadata, values = response.json()
            if not isinstance(values, list) or not isinstance(metadata, dict):
                raise ValueError("Unexpected upstream response")
            rows = []
            for row in values:
                year = int(row["date"])
                if (row["countryiso3code"] != country or row["indicator"]["id"] != series_code
                        or not start_year <= year <= end_year):
                    raise ValueError("Upstream response outside requested scope")
                value = row["value"]
                if value is not None and type(value) not in {int, float}:
                    raise ValueError("Unexpected observation type")
                rows.append({"year": year, "value": value})
        except (httpx.HTTPError, TypeError, ValueError, KeyError, IndexError):
            raise KnowledgeError("The approved live API did not return usable observations for this request.") from None
        return ledger.add(source, "live_observations", f"WDI {country} · {series_code} · {start_year}–{end_year}", {
            "series": series_code, "label": series["label"], "unit": series["unit"], "rows": rows,
            "country": country, "provider_last_updated": metadata.get("lastupdated"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }, url=str(response.request.url))
