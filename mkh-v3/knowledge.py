"""Published source discovery, evidence and bounded read-only analysis."""

from collections import Counter, defaultdict
import gzip
import hashlib
import json
import re
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from retrieval import SearchIndex, normalize

CANON = Path(__file__).resolve().parent / "canon"
SQL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
SOURCE_ID = re.compile(r"[a-z][a-z0-9-]{0,89}\Z")
EVIDENCE_REF = re.compile(r"\[\[(E-[a-f0-9]{16})\]\]")
SOURCE_TYPES = {"document", "dataset", "reference", "live"}
SQL_TYPES = {"TEXT", "INTEGER", "REAL"}
SQL_FUNCTIONS = {
    "abs", "avg", "coalesce", "count", "date", "floor", "ifnull", "length", "like",
    "lower", "ltrim", "max", "min", "nullif", "replace", "round", "rtrim",
    "substr", "substring", "sum", "trim", "upper", "strftime", "julianday", "lag", "lead",
    "row_number", "rank", "dense_rank", "percent_rank", "sqrt", "power", "ceil", "total",
}
class KnowledgeError(ValueError):
    """A source or operation is unavailable within the published research boundary."""


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
        self.consulted = {}
        self.artifacts = {}
        self.new_evidence = set()
        self.requested_figures = set()
        self.recalled_web = False
        self.items = {
            item["id"]: item for item in prior if self.allowed(item)
        }

    def allowed(self, item):
        if item.get("origin") == "public_web":
            return self.web_enabled and https_url(item.get("url"))
        source = self.knowledge.sources.get(item.get("source_id"))
        if not source or item.get("origin") != "canon" or item.get("release") != source["release"]:
            return False
        if item.get("fingerprint") and not self.knowledge.current_release(source["id"], item["fingerprint"]):
            return False
        for input_release in item.get("data", {}).get("input_releases", []):
            current = self.knowledge.sources.get(input_release["source_id"])
            if (current is None or current["release"] != input_release["release"] or
                    (input_release.get("fingerprint") and not self.knowledge.current_release(current["id"], input_release["fingerprint"]))):
                return False
        return True

    def present(self, evidence_id, kind, title, label_field, value_field):
        if kind in {"chart", "map", "table"}:
            self.requested_figures.add(kind)
        item = self.items.get(evidence_id)
        rows = item["data"].get("rows") if item else None
        if not rows or kind not in {"table", "chart", "map"} or not title.strip():
            raise KnowledgeError("Choose issued evidence with result rows and a title for the exhibit.")
        if kind in {"chart", "map"}:
            if not all(label_field in r and value_field in r for r in rows):
                raise KnowledgeError("Choose label and value columns from these result rows.")
            if not any(type(row[value_field]) in {int, float} for row in rows):
                raise KnowledgeError("At least one observation must have a numeric value.")
            if any(value is not None and type(value) not in {int, float} for value in (r[value_field] for r in rows)):
                raise KnowledgeError("Choose a numeric value column.")
        result = {"kind": kind, "title": title[:160], "label_field": label_field, "value_field": value_field,
                  "evidence_id": evidence_id}
        if kind == "map":
            inputs = [self.knowledge.source(r["source_id"]) for r in item["data"].get("input_releases", [])]
            boundaries_used = [s for s in inputs if s.get("map_key")]
            if len(boundaries_used) != 1:
                raise KnowledgeError("Include a published boundary release. Join through a registered geographic identifier before mapping another dataset.")
            source = boundaries_used[0]
            relationship = item["data"].get("relationship") or {}
            if len(inputs) > 1 and relationship.get("entity") not in source.get("entity_keys", {}):
                raise KnowledgeError("Mapping multiple inputs requires a registered geographic relationship to the boundary release.")
            boundaries = source["geometries"]
            code_column = source["map_key"]
            # A display label may be a place name or an SQL alias. Bind the geometry
            # using the release's data values; never infer cross-vintage place matches.
            candidates = [column for column in rows[0] if all(
                isinstance(r.get(column), str) and r[column] in boundaries for r in rows)]
            if code_column in candidates:
                field = code_column
            elif candidates and all([r[c] for r in rows] == [r[candidates[0]] for r in rows] for c in candidates):
                field = candidates[0]
            else:
                raise KnowledgeError("Include the release's boundary identifier in the result for every map row.")
            if len({r[field] for r in rows}) != len(rows):
                raise KnowledgeError("Return one observation for each displayed geographic identifier.")
            result.update(map_source=source["id"], map_field=field)
        identity = (evidence_id, kind, label_field, value_field)
        self.artifacts[identity] = result
        return result

    def add(self, source, kind, locator, data, *, url=None, related_sources=()):
        self.consulted[source["id"]] = self.knowledge.stamps[source["id"]]
        for release in data.get("input_releases", []):
            self.consulted[release["source_id"]] = self.knowledge.stamps[release["source_id"]]
        item = {
            "origin": "canon",
            "source_id": source["id"],
            "title": source["title"],
            "publisher": source["publisher"],
            "release": source["release"], "fingerprint": self.knowledge.stamps[source["id"]],
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
        self.new_evidence.add(identifier)
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
        directory = Path(directory)
        for path in sorted([*directory.glob("*.json"), *directory.glob("*.json.gz")]):
            raw = path.read_bytes()
            source = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
            if source.get("review") != "published":
                continue
            if not SOURCE_ID.fullmatch(source["id"]) or source["id"] in self.sources:
                raise ValueError(f"Invalid published source ID in {path.name}")
            if not https_url(source["url"]) or source["type"] not in SOURCE_TYPES:
                raise ValueError(f"Invalid published source metadata in {path.name}")
            if source["type"] in {"dataset", "reference"}:
                self._validate_table(source, path.name)
            if any(key not in source.get("columns", {}) for key in source.get("search_fields", [])):
                raise ValueError(f"Unknown search field in {path.name}")
            self.sources[source["id"]] = source
        self.stamps = {key: hashlib.sha256(json_text(s).encode()).hexdigest() for key, s in self.sources.items()}
        self.profiles = {}
        for key, source in self.sources.items():
            dims = {}
            for column in source.get("dimensions", []):
                if column not in source["columns"]:
                    raise ValueError(f"Unknown dimension {column} in {key}")
                counts = Counter(r.get(column) for r in source["records"] if r.get(column) is not None)
                dims[column] = {"distinct_count": len(counts), "examples": [v for v, _ in counts.most_common(20)]}
            self.profiles[key] = dims
        self.index = SearchIndex(self.sources, self.profiles)

    def current_release(self, source_id, version):
        source = self.sources.get(source_id)
        return bool(source and (version in (source["release"], self.stamps[source_id])
                                or version in source.get("compatible_fingerprints", [])))

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
        return {k: v for k, v in source.items() if k not in {"passages", "records", "adapter", "join_group", "geometries"}}

    def discover(self, query="", kind=None, limit=8, affinities=None):
        entries = self.index.find_sources(query, limit, kind, affinities)
        return [self.describes(entry["source"]) for entry in entries]

    def passage(self, entry, ledger):
        source = entry["source"]
        p, start, text = entry["payload"]
        page = p.get("page")
        url = source["url"] if not page else f"{source['url'].split('#')[0]}#page={page}"
        data = {"text": text, "page": page, "offset": start, "period": p.get("period", source["period"])}
        return ledger.add(source, p["kind"], p["locator"], data, url=url)

    def search_documents(self, query, source_id, ledger, limit=4, affinities=None):
        if source_id:
            self.source(source_id)
        entries = self.index.rank(query, "passage", limit, source_id, affinities=affinities)
        return [self.passage(e, ledger) for e in entries]

    def definition(self, source_id, key, ledger):
        src = self.source(source_id)
        value = src.get("definitions", {}).get(key)
        if value is None:
            raise KnowledgeError("Select a published definition key from inspect_source.")
        document = value if isinstance(value, dict) else {"definition": value}
        original = document.get("original")
        return ledger.add(src, "definition", "Published definition / " + key,
                          {"text": json_text(document), "key": key},
                          url=original if original and https_url(original) else src["url"])

    def read_passage(self, source_id, locator, offset, ledger):
        source = self.source(source_id)
        passage = next((p for p in source.get("passages", []) if p["locator"] == locator), None)
        if not passage or type(offset) is not int or not 0 <= offset < len(passage["text"]):
            raise KnowledgeError("Choose a published passage locator and a valid character offset.")
        text = passage["text"][offset:offset + 3000]
        return self.passage({"source": source, "payload": (passage, offset, text)}, ledger)

    def search_records(self, query, source_id, ledger, affinities=None):
        if source_id:
            self.source(source_id)
        entries = self.index.rank(query, "record", 5, source_id, affinities=affinities)
        return [ledger.add(e["source"], "source_record", e["payload"]["locator"], e["payload"]) for e in entries]

    def geography(self, name, level, ledger):
        normalized = normalize(name).strip()
        if not normalized:
            raise KnowledgeError("Provide an administrative place name.")
        candidates = []
        for source in self.sources.values():
            fields = source.get("place_fields", ["place"] if source["type"] == "reference" else [])
            if not fields:
                continue
            for row in source["records"]:
                if (any(normalize(row.get(k, "")) == normalized for k in fields)
                        and (not level or normalize(level) == normalize(row.get("level", "")))):
                    candidates.append(ledger.add(source, "source_record", row["locator"], row))
        return candidates[:12]

    def inspect(self, source_id):
        source = self.source(source_id)
        detail = self.describes(source)
        if source["type"] in {"dataset", "reference"}:
            detail["row_count"] = len(source["records"])
            detail["samples"] = source["records"][:3]
            if self.profiles[source_id]:
                detail["dimension_values"] = self.profiles[source_id]
            detail["relationships"] = [
                {"entity": entity, "source": other["id"], "key": key, "other_key": other["entity_keys"][entity]}
                for entity, key in source.get("entity_keys", {}).items() for other in self.sources.values()
                if other["id"] != source_id and entity in other.get("entity_keys", {})
            ]
        elif source["type"] == "document":
            detail["pages"] = [
                {"page": p.get("page"), "locator": p["locator"], "characters": len(p["text"])} for p in source["passages"]
            ]
        return detail

    def query(self, source_ids, sql, ledger):
        if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= 3:
            raise KnowledgeError("Select one to three published tables.")
        sources = [self.source(s) for s in dict.fromkeys(source_ids)]
        if any(s["type"] not in {"dataset", "reference"} for s in sources):
            raise KnowledgeError("SQL uses published structured datasets and reference tables.")
        if len(sources) > 1:
            raise KnowledgeError("Use link_records with a shared registered identifier to join releases.")
        return self._calculate(sources, sql, ledger, sources)

    def link_records(self, left_id, right_id, entity, sql, ledger):
        left, right = self.source(left_id), self.source(right_id)
        lk, rk = [s.get("entity_keys", {}).get(entity) for s in [left, right]]
        if left_id == right_id or not lk or not rk or lk not in left["columns"] or rk not in right["columns"]:
            raise KnowledgeError("These two releases do not share that registered entity identifier.")
        index = defaultdict(list)
        for row in right["records"]:
            if row[rk] not in ("", None):
                index[row[rk]].append(row)
        left_counts = Counter(r[lk] for r in left["records"] if r[lk] not in ("", None))
        shared = left_counts.keys() & index.keys()
        if any(left_counts[key] > 1 and len(index[key]) > 1 for key in shared):
            raise KnowledgeError("Both sources repeat a shared identifier. A raw join would multiply observations. Aggregate each native table to the intended grain and compare the results separately.")
        pairs = []
        for lrow in left["records"]:
            for rrow in index.get(lrow[lk], ()):
                if len(pairs) >= 20000:
                    raise KnowledgeError("The published identity mapping exceeds the join budget.")
                pairs.append({**{"l_" + k: v for k, v in lrow.items()},
                              **{"r_" + k: v for k, v in rrow.items()}})
        columns = {alias + k: v for alias, source in (("l_", left), ("r_", right))
                   for k, v in source["columns"].items()}
        relation = {"entity": entity, "left": left_id, "left_key": lk, "right": right_id,
                    "right_key": rk, "method": "inner equality on the registered nonempty identifier",
                    "matched_pairs": len(pairs), "matched_identifiers": len(shared),
                    "left_unmatched_rows": len(left["records"]) - sum(left_counts[key] for key in shared),
                    "right_unmatched_rows": len(right["records"]) - sum(len(index[key]) for key in shared),
                    "left_missing_keys": sum(r[lk] in (None, "") for r in left["records"]),
                    "right_missing_keys": sum(r[rk] in (None, "") for r in right["records"])}
        return self._calculate([{"table": "linked", "columns": columns, "records": pairs}], sql,
                               ledger, [left, right], relation=relation)

    def query_result(self, evidence_id, sql, ledger):
        item = ledger.items.get(evidence_id)
        if not item or item["origin"] != "canon":
            raise KnowledgeError("Select an issued calculation or live-series evidence ID.")
        data = item["data"]
        if not data.get("rows") or data.get("truncated"):
            raise KnowledgeError("This result is empty or truncated. Aggregate or filter the original source.")
        if data.get("parent_evidence"):
            raise KnowledgeError("Recalculate from the original evidence rows for a reproducible operation.")
        names = list(data["rows"][0])
        if not all(SQL_NAME.fullmatch(name) for name in names):
            raise KnowledgeError("Use simple lowercase column aliases for further calculations.")
        columns = {n: ("REAL" if any(type(r.get(n)) in {int, float} for r in data["rows"]) else "TEXT") for n in names}
        source = self.source(item["source_id"])
        inputs = [self.source(r["source_id"]) for r in data.get("input_releases", [])] or [source]
        table = {"table": "prior_result", "columns": columns, "records": data["rows"]}
        return self._calculate([table], sql, ledger, inputs, item)

    def _calculate(self, tables, sql, ledger, sources, parent=None, relation=None):
        if not isinstance(sql, str) or not 1 <= len(sql) <= 4000:
            raise KnowledgeError("Provide a single SQL SELECT, up to 4,000 characters.")

        conn = sqlite3.connect(":memory:")
        try:
            names = set()
            for source in tables:
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
             "release_id": s.get("release_id"), "fingerprint": self.stamps[s["id"]], "table": s.get("table"), "record_count": len(s["records"]) if "records" in s else None,
             "url": s["url"]}
            for s in sources
        ]
        row_ids = {row[key] for row in rows for key in ("id", "l_id", "r_id") if isinstance(row.get(key), str)}
        input_locations = [
            {"source_id": s["id"], "id": row["id"], "locator": row["locator"]}
            for s in sources for row in s.get("records", []) if row["id"] in row_ids
        ]
        derivation = {"relationship": relation} if relation else {}
        if parent:
            derivation["parent_evidence"] = {key: parent[key] for key in
                ("id", "source_id", "release", "locator", "url", "kind", "data")}
        return ledger.add(sources[0], "calculation", "Reproducible SQL over approved release snapshots", {
            "sql": sql, "input_releases": releases, "input_records": input_locations,
            "rows": rows, "truncated": len(raw_rows) > 30, **derivation,
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
