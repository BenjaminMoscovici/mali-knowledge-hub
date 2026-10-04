"""Runtime access and idempotent publication for the first public-source wave."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata

import requests


SNAPSHOT_GZ = Path(__file__).with_name("source_wave1.sqlite.gz")
SNAPSHOT = Path(tempfile.gettempdir()) / "mkh-source-wave1.sqlite"
TABLES = (
    "mkh_sources", "mkh_datasets", "mkh_ingestion_runs",
    "mkh_source_releases", "mkh_geo_units", "mkh_geo_names",
    "mkh_geo_identifiers", "mkh_evidence_spans",
    "mkh_population_observations", "mkh_humanitarian_observations",
    "mkh_document_pages", "mkh_geo_crosswalks", "mkh_geo_unresolved",
)
JSON_FIELDS = {"quality_json", "geometry_json", "candidates_json"}
_lock = threading.Lock()


def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def snapshot_path():
    if SNAPSHOT.exists() and SNAPSHOT.stat().st_mtime >= SNAPSHOT_GZ.stat().st_mtime:
        return SNAPSHOT
    with _lock:
        if not SNAPSHOT.exists() or SNAPSHOT.stat().st_mtime < SNAPSHOT_GZ.stat().st_mtime:
            temporary = SNAPSHOT.with_suffix(".part")
            with gzip.open(SNAPSHOT_GZ, "rb") as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
            os.replace(temporary, SNAPSHOT)
    return SNAPSHOT


def _rows(db, query, values=()):
    return [dict(row) for row in db.execute(query, values)]


def _parent_path(db, unit):
    names = [unit["canonical_name"] if "canonical_name" in unit else unit["name"]]
    parent = unit.get("parent_id")
    while parent:
        row = db.execute("select id,parent_id,name from mkh_geo_units where id=?", (parent,)).fetchone()
        if not row:
            break
        names.append(row["name"])
        parent = row["parent_id"]
    return " > ".join(reversed(names))


from evidence_cache import snapshot_cached

@snapshot_cached("source_wave1.sqlite.gz")
def retrieve_source_evidence(question, limit=8):
    """Return page-cited COD/INSTAT evidence when the question calls for it."""
    folded = _fold(question)
    population_intent = bool(re.search(
        r"\b(population|habitants?|demograph|recensement|rgph|femmes?|hommes?|"
        r"women|men|people|sex|sexe)\b", folded))
    geography_intent = bool(re.search(
        r"\b(region|cercle|commune|arrondissement|localit|administrative|p code|pcode|boundary|boundaries)\b",
        folded))
    hpc_intent = bool(re.search(r"\b(needs|besoins|hpc|hno|hnrp|hrp|target\w*|cible\w*|reached|atteint\w*|funding|financement)\b", folded))
    if not (population_intent or geography_intent or hpc_intent):
        return []

    db = sqlite3.connect(f"file:{snapshot_path()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        # Query exact phrases present in the question, not 14,000 per-name regexes.
        # The normalized names index preserves compound names and every homonym.
        words = folded.split()
        phrases = sorted({" ".join(words[i:i+size]) for i in range(len(words))
                          for size in range(1, min(12, len(words)-i)+1)
                          if len(" ".join(words[i:i+size])) > 2})
        matched = []
        for start in range(0, len(phrases), 400):
            batch = phrases[start:start+400]
            placeholders = ",".join("?" for _ in batch)
            matched += _rows(db, f"""select n.unit_id,n.name,n.folded_name,n.kind,u.level,u.name canonical_name,
                              u.parent_id,u.release_id,u.boundary_version
                       from mkh_geo_names n join mkh_geo_units u on u.id=n.unit_id
                       where n.folded_name in ({placeholders})""", batch)
        if matched:
            longest = max(len(row["folded_name"]) for row in matched)
            matched = [row for row in matched if len(row["folded_name"]) == longest]
        unique = {}
        for row in matched:
            unique[row["unit_id"]] = row
        matched = list(unique.values())[:20]
        evidence = []

        if hpc_intent:
            observations = _rows(db, """select h.*,s.passage,s.locator,r.source_url,r.retrieved_at,r.publication_date,
                       r.upstream_version,d.title from mkh_humanitarian_observations h
                       join mkh_evidence_spans s on s.id=h.span_id
                       join mkh_source_releases r on r.id=h.release_id
                       join mkh_datasets d on d.id=r.dataset_id where d.id='mli-hpc-hno-2026'""")
            if observations:
                first = observations[0]
                labels = {'all': 'national population estimate', 'INN': 'People in Need', 'TGT': 'targeted'}
                evidence.append({"source_type": "humanitarian_planning_snapshot", "source_family": "OCHA Global HPC HNO 2026",
                    "document_title": first["title"], "document_type": "national_planning_snapshot", "organization": "OCHA",
                    "version": first["upstream_version"], "publication_date": first["publication_date"],
                    "retrieved_at": first["retrieved_at"], "reference_period_start": first["reference_start"],
                    "reference_period_end": first["reference_end"], "geographic_scope": "Mali — national only",
                    "page": None, "section": first["locator"], "locator": first["locator"],
                    "source_endpoint": first["source_url"], "record_id": first["id"], "release_id": first["release_id"],
                    "content": "2026 NATIONAL planning context: " + "; ".join(f"{labels.get(r['population_status'], r['population_status'])}: {r['value']:,} people" for r in observations)
                    + ". Methodology: GHO Estimates. These are distinct planning measures, not counts reached. This stored layer has no financial requirements, funding, reached figures, sector severity or subnational breakdown; it cannot establish the needs in any selected region/commune. The national population estimate is distinct from INSTAT census/projection releases."})

        if population_intent:
            pop_units = [row for row in matched if db.execute(
                "select 1 from mkh_population_observations where unit_id=? limit 1",
                (row["unit_id"],)).fetchone()]
            for unit in pop_units[:limit]:
                observations = _rows(db, """select p.*,s.page,s.printed_page,s.section,s.passage,s.locator,
                                             r.retrieved_at,r.publication_date,r.source_url,r.upstream_version,
                                             d.title dataset_title,src.provider
                                      from mkh_population_observations p
                                      join mkh_evidence_spans s on s.id=p.span_id
                                      join mkh_source_releases r on r.id=p.release_id
                                      join mkh_datasets d on d.id=r.dataset_id
                                      join mkh_sources src on src.id=d.source_id
                                      where p.unit_id=? order by p.sex""", (unit["unit_id"],))
                if not observations:
                    continue
                values = {row["sex"]: row["value"] for row in observations}
                row = observations[0]
                parts = [f"total {values['total']:,}" if "total" in values else None,
                         f"female {values['female']:,}" if "female" in values else None,
                         f"male {values['male']:,}" if "male" in values else None]
                evidence.append({
                    "source_type": "official_population_table",
                    "source_family": "INSTAT RGPH5 population",
                    "document_title": row["dataset_title"], "document_type": "official_statistical_release",
                    "organization": row["provider"], "version": row["upstream_version"],
                    "publication_date": row["publication_date"], "valid_from": row["reference_start"],
                    "valid_until": row["reference_end"], "reference_period_start": row["reference_start"],
                    "reference_period_end": row["reference_end"], "retrieved_at": row["retrieved_at"],
                    "geographic_scope": _parent_path(db, unit), "page": row["page"],
                    "section": row["section"], "record_id": row["id"],
                    "source_endpoint": row["source_url"],
                    "content": (f"{unit['level'].capitalize()} {_parent_path(db, unit)}: "
                                + ", ".join(p for p in parts if p) + " people. "
                                + f"Reference period {row['reference_start']} to {row['reference_end']}. "
                                + f"Method: {row['methodology']}. Exact locator: {row['locator']}. "
                                + "This is a 2023 DNP projection based on RGPH5 2022, not an enumerated current count."),
                })

        if geography_intent:
            for unit in matched[:max(0, limit - len(evidence))]:
                identifiers = _rows(db, "select namespace,identifier from mkh_geo_identifiers where unit_id=?",
                                    (unit["unit_id"],))
                release = db.execute("""select r.*,d.title dataset_title,s.provider
                                        from mkh_source_releases r join mkh_datasets d on d.id=r.dataset_id
                                        join mkh_sources s on s.id=d.source_id where r.id=?""",
                                     (unit["release_id"],)).fetchone()
                if not release or release["dataset_title"] != "Mali - Subnational Administrative Boundaries":
                    continue
                codes = ", ".join(f"{x['namespace']}={x['identifier']}" for x in identifiers) or "no printed identifier"
                evidence.append({
                    "source_type": "official_geography_registry",
                    "source_family": "OCHA COD administrative geography",
                    "document_title": release["dataset_title"],
                    "document_type": "authoritative_common_operational_dataset",
                    "organization": release["provider"], "version": release["upstream_version"],
                    "publication_date": release["publication_date"], "retrieved_at": release["retrieved_at"],
                    "geographic_scope": _parent_path(db, unit), "page": None,
                    "section": f"COD {unit['level']} record", "record_id": unit["unit_id"],
                    "source_endpoint": release["source_url"],
                    "content": (f"COD exact-name match: {_parent_path(db, unit)}; administrative level "
                                f"{unit['level']}; boundary version {unit['boundary_version']}; {codes}. "
                                "An exact name can occur at more than one administrative level, so level and parent path must be retained."),
                })
        return evidence[:limit]
    finally:
        db.close()


def _converted(row, table):
    item = dict(row)
    if table == "mkh_datasets":
        item["current_release_id"] = None
    if table == "mkh_geo_units" and "unit_type" not in item:
        item["unit_type"] = "district" if item["level"] == "region" and item["name"].casefold() == "bamako" else item["level"]
    for field in JSON_FIELDS & item.keys():
        if item[field] is not None and isinstance(item[field], str):
            item[field] = json.loads(item[field])
    return item


def _batches(rows, max_rows=200, max_bytes=700_000):
    batch, size = [], 2
    for row in rows:
        row_size = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if batch and (len(batch) >= max_rows or size + row_size > max_bytes):
            yield batch
            batch, size = [], 2
        batch.append(row)
        size += row_size
    if batch:
        yield batch


def publish_snapshot():
    """Idempotently copy the validated snapshot to private Supabase tables."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY", "")
    if not url or not key or not SNAPSHOT_GZ.exists():
        return {"status": "not_configured"}
    session = requests.Session()
    session.headers.update({"apikey": key, "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "Prefer": "resolution=ignore-duplicates,return=minimal"})
    db = sqlite3.connect(f"file:{snapshot_path()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        expected = db.execute("select count(*) from mkh_population_observations").fetchone()[0]
        check = session.get(url + "/rest/v1/mkh_population_observations",
                            params={"select": "id", "limit": "1"}, headers={"Prefer": "count=exact"}, timeout=20)
        if check.ok and int(check.headers.get("Content-Range", "0/0").split("/")[-1]) >= expected:
            return {"status": "already_current", "population": expected}
        for table in TABLES:
            query = f"select * from {table}"
            if table == "mkh_geo_units":
                query += " order by case level when 'country' then 1 when 'region' then 2 when 'cercle' then 3 when 'commune' then 4 when 'arrondissement' then 4 else 5 end,rowid"
            rows = (_converted(row, table) for row in db.execute(query))
            for batch in _batches(rows):
                response = session.post(url + "/rest/v1/" + table, json=batch, timeout=45)
                if not response.ok:
                    raise RuntimeError(f"source publication failed: {table} HTTP {response.status_code}")
        for row in db.execute("select id,current_release_id from mkh_datasets"):
            response = session.patch(url + "/rest/v1/mkh_datasets", params={"id": "eq." + row["id"]},
                                     json={"current_release_id": row["current_release_id"]}, timeout=20)
            if not response.ok:
                raise RuntimeError(f"source activation failed: HTTP {response.status_code}")
        return {"status": "published", "population": expected}
    finally:
        db.close()
        session.close()


def publish_snapshot_logged():
    started = time.monotonic()
    try:
        result = publish_snapshot()
        print("MKH_SOURCE_WAVE " + json.dumps({**result, "seconds": round(time.monotonic() - started, 2)}), flush=True)
    except Exception as exc:
        print("MKH_SOURCE_WAVE " + json.dumps({"status": "failed", "error_type": type(exc).__name__}), flush=True)
