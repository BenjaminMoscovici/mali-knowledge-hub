"""Offline validation store for versioned public source packages.

This store is a staging/acceptance harness, not a replacement for Supabase.
No existing production tables or research paths are changed. The matching
PostgreSQL migration is applied only after the live schema audit passes.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import sqlite3
import uuid

from normalization import key

TRANSFORM_VERSION = "mkh-source-foundation/1"
LEVELS = {"country", "region", "cercle", "commune", "arrondissement", "locality"}
PARENTS = {"country": set(), "region": {"country"}, "cercle": {"region"},
           "commune": {"cercle"}, "arrondissement": {"region"},
           "locality": {"commune", "arrondissement"}}


def stable_id(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(parts, ensure_ascii=False)))


def now():
    return datetime.now(timezone.utc).isoformat()


def release_identity(dataset, checksum, version):
    return stable_id(dataset, checksum, version, TRANSFORM_VERSION)


SCHEMA = """
create table if not exists mkh_sources (
 id text primary key, provider text not null, title text not null, url text not null);
create table if not exists mkh_datasets (
 id text primary key, source_id text not null references mkh_sources(id),
 title text not null, refresh_policy text not null, current_release_id text);
create table if not exists mkh_ingestion_runs (
 id text primary key, dataset_id text not null, started_at text not null,
 finished_at text, status text not null, release_id text, error_class text);
create table if not exists mkh_source_releases (
 id text primary key, dataset_id text not null references mkh_datasets(id),
 checksum text not null, upstream_version text not null, retrieved_at text not null,
 publication_date text, reference_start text, reference_end text,
 source_url text not null, original_file text not null, license text not null,
 license_url text not null, attribution text not null, access text not null,
 transformation text not null, quality_json text not null,
 run_id text not null references mkh_ingestion_runs(id), status text not null);
create table if not exists mkh_geo_units (
 id text primary key, release_id text not null references mkh_source_releases(id),
 parent_id text references mkh_geo_units(id), level text not null,
 name text not null, unit_type text not null, boundary_version text not null, valid_on text,
 valid_to text, geometry_json text, original_record_id text not null,
 unique(release_id,original_record_id));
create table if not exists mkh_geo_names (
 id text primary key, unit_id text not null references mkh_geo_units(id),
 name text not null, folded_name text not null, language text, kind text not null);
create table if not exists mkh_geo_identifiers (
 id text primary key, unit_id text not null references mkh_geo_units(id),
 namespace text not null, identifier text not null,
 unique(unit_id,namespace,identifier));
create table if not exists mkh_evidence_spans (
 id text primary key, release_id text not null references mkh_source_releases(id),
 original_record_id text not null, page integer, printed_page text,
 section text, passage text not null, locator text not null);
create table if not exists mkh_population_observations (
 id text primary key, release_id text not null references mkh_source_releases(id),
 unit_id text not null references mkh_geo_units(id),
 span_id text not null references mkh_evidence_spans(id),
 sex text not null, value integer not null, unit text not null,
 reference_start text not null, reference_end text not null,
 methodology text not null, geographic_precision text not null,
 unique(release_id,unit_id,sex));
create table if not exists mkh_humanitarian_observations (
 id text primary key, release_id text not null references mkh_source_releases(id),
 unit_id text not null references mkh_geo_units(id),
 span_id text not null references mkh_evidence_spans(id),
 sector text not null, category text not null, population_status text not null,
 value integer not null, unit text not null, reference_start text not null,
 reference_end text not null, methodology text not null,
 geographic_precision text not null,
 unique(release_id,unit_id,sector,category,population_status));
create table if not exists mkh_document_pages (
 release_id text not null references mkh_source_releases(id), page integer not null,
 content text not null, primary key(release_id,page));
create table if not exists mkh_geo_crosswalks (
 id text primary key, from_unit_id text not null references mkh_geo_units(id),
 to_unit_id text not null references mkh_geo_units(id), relation text not null,
 method text not null, confidence real not null, status text not null,
 supersedes text references mkh_geo_crosswalks(id), rationale text not null,
 recorded_at text not null);
create table if not exists mkh_geo_unresolved (
 id text primary key, release_id text not null references mkh_source_releases(id),
 unit_id text not null references mkh_geo_units(id),
 raw_name text not null, level text not null, parent_name text,
 candidates_json text not null, reason text not null, status text not null);
create index if not exists mkh_geo_lookup on mkh_geo_names(folded_name,unit_id);
create index if not exists mkh_geo_parent on mkh_geo_units(parent_id);
create index if not exists mkh_population_geo on mkh_population_observations(unit_id,sex);
"""


def validate_package(package):
    """Reject incomplete, inconsistent or unsafe packages before any publication."""
    p = deepcopy(package)
    for field in ("source", "dataset", "release", "units", "spans", "population", "pages"):
        if field not in p:
            raise ValueError(f"Missing {field}")
    r = p["release"]
    for field in ("id", "checksum", "upstream_version", "retrieved_at", "source_url",
                  "original_file", "license", "license_url", "attribution", "access"):
        if not str(r.get(field) or "").strip():
            raise ValueError(f"Missing release {field}")
    if len(r["checksum"]) != 64 or any(c not in "0123456789abcdef" for c in r["checksum"]):
        raise ValueError("Invalid source checksum")
    if r["access"] != "public_aggregate":
        raise ValueError("Only public aggregate packages supported")
    if not p["units"] and not p["pages"]:
        raise ValueError("Empty release")
    for start, end in ((r.get("reference_start"), r.get("reference_end")),):
        if start: date.fromisoformat(start)
        if end: date.fromisoformat(end)
        if start and end and start > end: raise ValueError("Reversed period")
    units = {u["id"]: u for u in p["units"]}
    if len(units) != len(p["units"]): raise ValueError("Duplicate geographic identity")
    records = set()
    for u in units.values():
        if u["level"] not in LEVELS or not u["name"].strip():
            raise ValueError("Invalid geography")
        if u.get("unit_type", u["level"]) not in ({"region", "district"} if u["level"] == "region" else {u["level"]}):
            raise ValueError("Invalid administrative type")
        if u["original_record_id"] in records: raise ValueError("Duplicate source record")
        records.add(u["original_record_id"])
        parent = units.get(u.get("parent_id"))
        if u["level"] == "country":
            if u.get("parent_id"): raise ValueError("Country has parent")
        elif not parent or parent["level"] not in PARENTS[u["level"]]:
            raise ValueError("Invalid parent or administrative level")
        if u.get("valid_on"): date.fromisoformat(u["valid_on"])
        if u.get("valid_to"): date.fromisoformat(u["valid_to"])
        if u.get("valid_to") and u.get("valid_on") and u["valid_to"] < u["valid_on"]:
            raise ValueError("Reversed geography validity")
    spans = {s["id"]: s for s in p["spans"]}
    if len(spans) != len(p["spans"]): raise ValueError("Duplicate span")
    page_numbers = {page["page"] for page in p["pages"]}
    if len(page_numbers) != len(p["pages"]): raise ValueError("Duplicate document page")
    observations = set()
    for o in p["population"]:
        if o["unit_id"] not in units or o["span_id"] not in spans:
            raise ValueError("Observation missing geography or citation")
        span = spans[o["span_id"]]
        if span.get("page") not in page_numbers or not span["passage"].strip():
            raise ValueError("Observation missing source page")
        if o["sex"] not in {"male", "female", "total"} or isinstance(o["value"], bool):
            raise ValueError("Invalid population category")
        if not isinstance(o["value"], int) or o["value"] < 0:
            raise ValueError("Invalid population value")
        if o["unit"] != "people" or o["geographic_precision"] != units[o["unit_id"]]["level"]:
            raise ValueError("Invalid unit or precision")
        start, end = date.fromisoformat(o["reference_start"]), date.fromisoformat(o["reference_end"])
        if start > end or not o["methodology"]: raise ValueError("Invalid observation period")
        identity = (o["unit_id"], o["sex"])
        if identity in observations: raise ValueError("Duplicate population observation")
        observations.add(identity)
    needs_keys = set()
    for o in p.get("humanitarian", []):
        if o["unit_id"] not in units or o["span_id"] not in spans:
            raise ValueError("Humanitarian observation missing geography or citation")
        if o["population_status"] not in {"all", "INN", "TGT", "AFF", "REA"}:
            raise ValueError("Unrecognised population status")
        if not isinstance(o["value"], int) or isinstance(o["value"], bool) or o["value"] < 0:
            raise ValueError("Invalid humanitarian population")
        if o["unit"] != "people" or o["geographic_precision"] != units[o["unit_id"]]["level"]:
            raise ValueError("Invalid humanitarian unit or geographic precision")
        if date.fromisoformat(o["reference_start"]) > date.fromisoformat(o["reference_end"]) or not o["methodology"]:
            raise ValueError("Invalid humanitarian reference period")
        identity = (o["unit_id"], o["sector"], o["category"], o["population_status"])
        if identity in needs_keys: raise ValueError("Duplicate humanitarian observation")
        needs_keys.add(identity)
    return p


class SourceStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma foreign_keys=on")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def publish(self, package, *, reviewed_shrink_reason=None):
        """Atomic validated publication; reruns never reactivate an old release."""
        run_id = str(uuid.uuid4())
        dataset_id = package.get("dataset", {}).get("id", "unknown")
        with self.db:
            self.db.execute("insert into mkh_ingestion_runs values (?,?,?,?,?,?,?)",
                            (run_id, dataset_id, now(), None, "running", None, None))
        try:
            p = validate_package(package)
            r, s, d = p["release"], p["source"], p["dataset"]
            if self.db.execute("select 1 from mkh_source_releases where id=?", (r["id"],)).fetchone():
                with self.db:
                    self.db.execute("update mkh_ingestion_runs set status='no_op',finished_at=?,release_id=? where id=?",
                                    (now(), r["id"], run_id))
                return {"status": "no_op", "release_id": r["id"], "run_id": run_id}
            previous = self.db.execute("select current_release_id from mkh_datasets where id=?", (d["id"],)).fetchone()
            if previous and previous[0]:
                old = self.db.execute("select count(*) from mkh_geo_units where release_id=?", (previous[0],)).fetchone()[0]
                old_pages = self.db.execute("select count(*) from mkh_document_pages where release_id=?", (previous[0],)).fetchone()[0]
                if ((old and len(p["units"]) < old * .75) or
                        (old_pages and len(p["pages"]) < old_pages * .75)) and not reviewed_shrink_reason:
                    raise ValueError("Unexpected shrinking release; retain previous release")
            with self.db:
                self.db.execute("insert into mkh_sources values (?,?,?,?) on conflict(id) do nothing",
                                (s["id"], s["provider"], s["title"], s["url"]))
                self.db.execute("insert into mkh_datasets values (?,?,?,?,null) on conflict(id) do nothing",
                                (d["id"], s["id"], d["title"], d["refresh_policy"]))
                quality = dict(r.get("quality", {}))
                if reviewed_shrink_reason: quality["reviewed_shrink_reason"] = reviewed_shrink_reason
                self.db.execute("insert into mkh_source_releases values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], d["id"], r["checksum"], r["upstream_version"], r["retrieved_at"],
                     r.get("publication_date"), r.get("reference_start"), r.get("reference_end"),
                     r["source_url"], r["original_file"], r["license"], r["license_url"],
                     r["attribution"], r["access"], TRANSFORM_VERSION, json.dumps(quality, ensure_ascii=False),
                     run_id, "validated"))
                # Topological ordering is mandatory; a child can never precede its parent.
                remaining, inserted = list(p["units"]), set()
                while remaining:
                    ready = [u for u in remaining if not u.get("parent_id") or u["parent_id"] in inserted]
                    if not ready: raise ValueError("Geographic cycle")
                    for u in ready:
                        self.db.execute("insert into mkh_geo_units values (?,?,?,?,?,?,?,?,?,?,?)",
                            (u["id"], r["id"], u.get("parent_id"), u["level"], u["name"],
                             u.get("unit_type", u["level"]), u["boundary_version"], u.get("valid_on"), u.get("valid_to"),
                             json.dumps(u["geometry"]) if u.get("geometry") else None, u["original_record_id"]))
                        names = {(u["name"], "official")}
                        names.update((name, "source_alternative") for name in u.get("aliases", []) if name != u["name"])
                        for name, kind in sorted(names):
                            self.db.execute("insert into mkh_geo_names values (?,?,?,?,?,?)",
                                (stable_id(u["id"], name, kind), u["id"], name, key(name),
                                 u.get("name_languages", {}).get(name), kind))
                        for namespace, identifier in u.get("identifiers", {}).items():
                            self.db.execute("insert into mkh_geo_identifiers values (?,?,?,?)",
                                (stable_id(u["id"], namespace, identifier), u["id"], namespace, identifier))
                        inserted.add(u["id"])
                    remaining = [u for u in remaining if u["id"] not in inserted]
                for span in p["spans"]:
                    self.db.execute("insert into mkh_evidence_spans values (?,?,?,?,?,?,?,?)",
                        (span["id"], r["id"], span["original_record_id"], span.get("page"),
                         span.get("printed_page"), span.get("section"), span["passage"], span["locator"]))
                for o in p["population"]:
                    self.db.execute("insert into mkh_population_observations values (?,?,?,?,?,?,?,?,?,?,?)",
                        (o["id"], r["id"], o["unit_id"], o["span_id"], o["sex"], o["value"],
                         o["unit"], o["reference_start"], o["reference_end"], o["methodology"], o["geographic_precision"]))
                for o in p.get("humanitarian", []):
                    self.db.execute("insert into mkh_humanitarian_observations values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (o["id"], r["id"], o["unit_id"], o["span_id"], o["sector"], o["category"],
                         o["population_status"], o["value"], o["unit"], o["reference_start"],
                         o["reference_end"], o["methodology"], o["geographic_precision"]))
                self.db.executemany("insert into mkh_document_pages values (?,?,?)",
                    [(r["id"], page["page"], page["content"]) for page in p["pages"]])
                self.db.execute("update mkh_datasets set current_release_id=? where id=?", (r["id"], d["id"]))
                self.db.execute("update mkh_ingestion_runs set status='succeeded',finished_at=?,release_id=? where id=?",
                                (now(), r["id"], run_id))
            return {"status": "succeeded", "release_id": r["id"], "run_id": run_id}
        except Exception as error:
            with self.db:
                self.db.execute("update mkh_ingestion_runs set status='failed',finished_at=?,error_class=? where id=?",
                                (now(), type(error).__name__, run_id))
            raise

    def resolve(self, name, *, dataset_id, level, parent_id=None):
        if level not in LEVELS: raise ValueError("Administrative level required")
        rows = self.db.execute("""select distinct u.* from mkh_geo_units u
          join mkh_geo_names n on n.unit_id=u.id
          join mkh_datasets d on d.current_release_id=u.release_id
          where d.id=? and n.folded_name=? and u.level=?""", (dataset_id, key(name), level)).fetchall()
        candidates = [dict(row) for row in rows if parent_id is None or row["parent_id"] == parent_id]
        return {"status": "resolved" if len(candidates) == 1 else "ambiguous" if candidates else "unresolved",
                "candidates": candidates}

    def population(self, name, *, dataset_id, level, parent_id=None):
        match = self.resolve(name, dataset_id=dataset_id, level=level, parent_id=parent_id)
        if match["status"] != "resolved": return match
        uid = match["candidates"][0]["id"]
        rows = self.db.execute("""select o.*,s.page,s.printed_page,s.passage,r.source_url,
          r.upstream_version,r.retrieved_at,r.publication_date,r.license,r.license_url,r.attribution
          from mkh_population_observations o join mkh_evidence_spans s on s.id=o.span_id
          join mkh_source_releases r on r.id=o.release_id where o.unit_id=? and o.sex='total'""", (uid,)).fetchall()
        return {"status": "reported" if rows else "not_reported", "geography": match["candidates"][0],
                "evidence": [dict(row) for row in rows],
                "limitations": ["Historical reference period; not current population.",
                    "Population is not a humanitarian need, target, reach or coverage measure.",
                    "No allocation across boundary releases without an approved crosswalk."]}

    def crosswalk_proposals(self, from_dataset, to_dataset):
        """Names/parents propose identity; they do not establish equal boundaries."""
        def units(dataset):
            return [dict(r) for r in self.db.execute("""select u.*,p.name parent_name
              from mkh_geo_units u left join mkh_geo_units p on p.id=u.parent_id
              join mkh_datasets d on d.current_release_id=u.release_id where d.id=?""", (dataset,))]
        target = units(to_dataset)
        proposals = []
        with self.db:
            for u in units(from_dataset):
                matches = [v for v in target if u["level"] == v["level"] and key(u["name"]) == key(v["name"])
                           and key(u["parent_name"]) == key(v["parent_name"])]
                for v in matches:
                    ident = stable_id(u["id"], v["id"], "name_parent_proposal", 1)
                    self.db.execute("insert into mkh_geo_crosswalks values (?,?,?,?,?,?,?,?,?,?) on conflict(id) do nothing",
                        (ident, u["id"], v["id"], "candidate_identity", "name_parent_exact", .90,
                         "proposed", None, "Boundary equivalence and identifiers require review", now()))
                    proposals.append(ident)
                if len(matches) != 1:
                    self.db.execute("insert into mkh_geo_unresolved values (?,?,?,?,?,?,?,?,?) on conflict(id) do nothing",
                        (stable_id(u["id"], to_dataset, "unresolved"), u["release_id"], u["id"], u["name"], u["level"],
                         u["parent_name"], json.dumps([v["id"] for v in matches]),
                         "ambiguous" if matches else "no_name_parent_match", "open"))
        return len(proposals)

    def approved_targets(self, unit_id):
        return [dict(r) for r in self.db.execute("""select c.* from mkh_geo_crosswalks c
          where c.from_unit_id=? and c.status='approved'
          and not exists (select 1 from mkh_geo_crosswalks newer where newer.supersedes=c.id)""", (unit_id,))]

    def humanitarian(self, name, *, dataset_id, level, status="INN", sector="ALL"):
        match = self.resolve(name, dataset_id=dataset_id, level=level)
        if match["status"] != "resolved": return match
        unit = match["candidates"][0]
        evidence = [dict(r) for r in self.db.execute("""select o.*,s.passage,s.locator,
          r.source_url,r.upstream_version,r.retrieved_at,r.license,r.license_url,r.attribution
          from mkh_humanitarian_observations o join mkh_evidence_spans s on s.id=o.span_id
          join mkh_source_releases r on r.id=o.release_id
          where o.unit_id=? and o.population_status=? and o.sector=?""", (unit["id"], status, sector))]
        return {"status": "reported" if evidence else "not_reported", "geography": unit, "evidence": evidence,
                "limitations": ["Needs, targeted, affected and reached are separate measures.",
                    "Do not sum across sectors or population groups.",
                    "No subnational allocation from national figures; missing values are not zero."]}

    def freshness(self):
        return [dict(r) for r in self.db.execute("""select d.id,d.title,d.refresh_policy,
          r.upstream_version,r.retrieved_at,r.reference_start,r.reference_end,r.status,r.quality_json
          from mkh_datasets d left join mkh_source_releases r on r.id=d.current_release_id""")]
