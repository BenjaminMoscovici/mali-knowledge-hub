"""Citable operational presence and displacement, with bounded retrieval."""
from collections import Counter
from functools import lru_cache
import gzip
import json
import logging
import os
from pathlib import Path
import re

import requests
from source_wave import _fold, _batches

SNAPSHOT = Path(__file__).with_name("source_wave2.json.gz")


@lru_cache(maxsize=1)
def package():
    with gzip.open(SNAPSHOT, "rt", encoding="utf-8") as file:
        return json.load(file)


def _scope(question, records):
    folded = _fold(question)
    matches = []
    for level in ("region", "cercle", "commune"):
        labels = {_fold(r["payload"]["geography"].get(level)): r["payload"]["geography"].get(level)
                  for r in records}
        for name, raw in labels.items():
            if len(name) > 2 and re.search(r"(?:^| )" + re.escape(name) + r"(?: |$)", folded):
                explicit = bool(re.search(r"\b" + level + r" (?:de |of )?" + re.escape(name) + r"\b|\b" + re.escape(name) + " " + level + r"\b", folded))
                matches.append((explicit, len(name), level, name, raw))
    if not matches:
        return records, "Mali; source-reported locations", "country"
    explicit = [m for m in matches if m[0]]
    candidates = explicit or matches
    # A place appearing at several levels defaults to regional context; never
    # silently assumes a commune. Explicit level requests override that default.
    candidates.sort(key=lambda m: (-m[1], ("region", "cercle", "commune").index(m[2])))
    _, _, level, name, raw = candidates[0]
    selected = [r for r in records if _fold(r["payload"]["geography"].get(level)) == name]
    return selected, f"Source-reported {level}: {raw}", level


def _displacement_scope(question, records):
    """Keep every explicitly compared source locality, never invent a total."""
    folded = _fold(question)
    if re.search(r"\b(and|et|versus|vs|compare|comparer)\b", folded):
        labels = {_fold(r['payload']['geography'].get('commune'))
                  for r in records}
        requested = {name for name in labels if len(name) > 2 and
                     re.search(r"(?:^| )" + re.escape(name) + r"(?: |$)", folded)}
        higher_labels = {_fold(r['payload']['geography'].get(level))
                         for r in records for level in ('region', 'cercle')}
        explicit_local = bool(re.search(r'\b(communes?|localit\w*)\b', folded))
        explicit_higher = bool(re.search(r'\b(regions?|regional|cercles?)\b', folded))
        if len(requested) >= 2 and not explicit_higher and (explicit_local or requested - higher_labels):
            selected = [r for r in records
                        if _fold(r['payload']['geography'].get('commune')) in requested]
            # These are labels in a commune-level source. A name shared with a
            # region/cercle does not turn its observation into a higher total.
            return selected, 'Requested source commune labels; no region/cercle aggregate', 'commune'
    return _scope(question, records)


def _locator(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["sheet"], []).append(row["row"])
    parts = []
    for sheet, numbers in grouped.items():
        ranges = []
        start = end = None
        for number in sorted(set(numbers)):
            if end is not None and number == end + 1:
                end = number
            else:
                if start is not None:
                    ranges.append(str(start) if start == end else f"{start}-{end}")
                start = end = number
        if start is not None:
            ranges.append(str(start) if start == end else f"{start}-{end}")
        parts.append(f"{sheet} rows " + ",".join(ranges))
    return "; ".join(parts)


def _evidence(rows, scope, content, title):
    first = rows[0]
    metadata_date = next(r["publication_date"] for r in package()["tables"]["mkh_source_releases"] if r["id"] == first["release_id"])
    return {"source_type": first["source_type"], "source_family": "OCHA Mali 3W operational presence" if first["source_type"] == "operational_presence" else "IOM DTM displacement",
            "document_title": title, "document_type": "public_aggregate_spreadsheet",
            "organization": "OCHA Mali" if first["source_type"] == "operational_presence" else "IOM DTM",
            "version": first["version"], "publication_date": None,
            "valid_from": first["reference_start"], "valid_until": first["reference_end"],
            "reference_period_start": first["reference_start"], "reference_period_end": first["reference_end"],
            "retrieved_at": first["retrieved_at"], "source_endpoint": first["source_url"],
            "geographic_scope": scope, "page": None, "section": _locator(rows),
            "record_id": first["id"], "release_id": first["release_id"], "locator": _locator(rows),
            "geographic_precision": "source labels; validated COD region/cercle where stated; commune unverified",
            "content": content + f" HDX resource creation date {metadata_date} is file metadata, not a verified original publication or collection date; those dates are unavailable in the ingested workbook."}


from evidence_cache import snapshot_cached

@snapshot_cached("source_wave2.json.gz")
def retrieve_operational_evidence(question, limit=10):
    folded = _fold(question)
    presence = bool(re.search(r"\b(who|actors?|organisations?|organizations?|acteurs?|presence|present|3w|5w|activities|activites|interventions?|operational|operationnel|coverage|couverture|respond|response|reponse|delivery|projets?|projects?)\b", folded))
    displacement = bool(re.search(r"\b(dtm|displace\w*|deplace\w*|retour\w*|return\w*|repatri\w*|rapatri\w*|mobility|mobilite|needs|besoins)\b", folded))
    if not (presence or displacement):
        return []
    evidence = []
    if presence:
        source_rows = [r for r in package()["records"] if r["source_type"] == "operational_presence"]
        selected, scope, level = _scope(question, source_rows)
        # Filter only explicit lexical sectors, keeping the curated term mapping inspectable.
        sectors = {"health": ("health", "sante"), "protection": ("protection",), "nutrition": ("nutrition",),
                   "food_security": ("food security", "securite alimentaire"), "wash": ("wash", "eha", "eau"),
                   "education": ("education",), "shelter": ("shelter", "abris")}
        requested = [s for s, terms in sectors.items() if any(re.search(r"\b" + t + r"\b", folded) for t in terms)]
        if requested:
            selected = [r for r in selected if r["payload"]["sector"] in requested]
        if selected:
            actors = sorted({r["payload"]["organization"] + " (" + r["payload"]["acronym"] + ")" for r in selected})
            issues = Counter(i["reason"] for r in selected for i in r["payload"]["geo_resolution"]["issues"])
            sector_counts = {s: {"source_rows": sum(r['payload']['sector'] == s for r in selected),
                                  "actor_labels": len({(r['payload']['organization'], r['payload']['acronym']) for r in selected if r['payload']['sector'] == s})}
                             for s in sorted({r['payload']['sector'] for r in selected})}
            content = (f"OCHA 3W Q1 2026, {scope}: {len(selected)} source rows; {len(actors)} distinct full-name/acronym labels (not globally resolved actor identities). "
                       f"Actor labels: {'; '.join(actors[:35])}. "
                       f"{'Actor list truncated to 35; counts use all selected rows. ' if len(actors) > 35 else ''}"
                       f"All recorded sectors (rows/actor-label counts, not beneficiaries or projects): {json.dumps(sector_counts)}. "
                       "These are PRESENCE ONLY. Every activity description, project title, start/end date, target and reached field is blank in this release; missing is not zero. "
                       "No active delivery, completed delivery, reach, coverage or ending intervention can be established from this workbook. "
                       f"Geography issues across selected rows: {dict(issues)}. Source commune labels remain unverified. "
                       "No records is not evidence of no activity. Different reference periods and geography vintages prevent a direct needs-coverage ratio.")
            evidence.append(_evidence(selected, scope, content, "Mali OCHA 3W — Q1 2026 presence summary"))
            for sector in sorted({r["payload"]["sector"] for r in selected}):
                subset = [r for r in selected if r["payload"]["sector"] == sector]
                labels = sorted({r["payload"]["organization"] + " (" + r["payload"]["acronym"] + ")" for r in subset})
                content = (f"{scope}; sector {sector}: {len(subset)} source rows, {len(labels)} distinct actor labels. "
                           f"Actors: {'; '.join(labels[:35])}. "
                           + ("Actor list truncated to 35. " if len(labels) > 35 else "")
                           + "Presence only, Q1 2026; no recorded activities or beneficiary reach. Commune geography remains source-label-only; exact sheet/row locators supplied.")
                evidence.append(_evidence(subset, scope, content, f"OCHA 3W Q1 2026 — {sector} presence"))
        else:
            # Cite the source scope honestly, rather than returning a silent empty list.
            evidence.append(_evidence(source_rows[:1], scope, "The selected source labels/sector filter have no matching rows in OCHA Q1 2026. This is absence of records in this release, not evidence of absence of actors, activities or services.", "OCHA 3W — retrieval limitation"))
    if displacement:
        rows = [r for r in package()["records"] if r["source_type"] == "displacement_stock"]
        selected, scope, level = _displacement_scope(question, rows)
        categories = ["internally_displaced", "returned_idps", "repatriated_persons"]
        if re.search(r"\b(return\w*|retour\w*)\b", folded) and not re.search(r"\b(displace\w*|deplace\w*)\b", folded):
            categories = ["returned_idps", "repatriated_persons"]
        for category in categories:
            subset = [r for r in selected if r["payload"]["category"] == category]
            # Return actual commune rows, never manufacture an administrative total.
            for record in sorted(subset, key=lambda r: (-r["payload"]["value"], r["row"]))[:3]:
                p = record["payload"]
                g = p["geography"]
                geo = " > ".join(g.get(l, "") for l in ("region", "cercle", "commune"))
                content = (f"DTM Round 83, September 2025: category {category}, STOCK (not flow), source-labelled commune {geo}. "
                           f"{p['value']:,} people; female {p['female'] if p['female'] is not None else 'not fully reported'}, male {p['male'] if p['male'] is not None else 'not fully reported'}; {p['households']:,} households. "
                           f"Geography validation: {json.dumps(p['geo_resolution'], ensure_ascii=False)}. "
                           f"Methodology: {p['methodology']}. These are selected commune records, not a region/cercle total, national prevalence or current 2026 observation. "
                           "Returned-IDP stocks do not prove durable return; repatriated persons are a separate category. "
                           f"Exact locator: {record['locator']}.")
                evidence.append(_evidence([record], geo, content, f"DTM Round 83 — {category} — {g['commune']}"))
    # Reserve evidence slots for both families on joined questions.
    if presence and displacement:
        p = [e for e in evidence if e["source_type"] == "operational_presence"]
        d = [e for e in evidence if e["source_type"] == "displacement_stock"]
        groups = [[e for e in d if f"category {c}," in e['content']] for c in ('internally_displaced', 'returned_idps', 'repatriated_persons')]
        d = [group[i] for i in range(3) for group in groups if i < len(group)]
        return (p[:max(1, limit // 2)] + d[:max(1, limit - limit // 2)])[:limit]
    return evidence[:limit]


def publish_operational_snapshot(data=None):
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        return {"status": "not_configured"}
    if url != "https://hofoubbmepacdljeablj.supabase.co":
        raise RuntimeError("Operational wave target is not the authorized GIZ project")
    data = package() if data is None else data
    session = requests.Session()
    session.headers.update({"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                            "Prefer": "resolution=ignore-duplicates,return=minimal"})
    for table, rows in data["tables"].items():
        for batch in _batches(rows):
            response = session.post(url + "/rest/v1/" + table, json=batch, timeout=45)
            if not response.ok:
                raise RuntimeError(f"Operational publication: {table} HTTP {response.status_code}")
    for dataset, release in data["releases"].items():
        expected = sum(r["release_id"] == release for r in data["records"])
        check = session.get(url + "/rest/v1/mkh_source_records", params={"select": "id", "release_id": "eq." + release, "limit": 1},
                            headers={"Prefer": "count=exact"}, timeout=20)
        check.raise_for_status()
        if int(check.headers.get("Content-Range", "0/0").split("/")[-1]) != expected:
            raise RuntimeError("Operational release row count failed; active pointer unchanged")
        response = session.patch(url + "/rest/v1/mkh_datasets", params={"id": "eq." + dataset}, json={"current_release_id": release}, timeout=20)
        response.raise_for_status()
    return {"status": "published", "records": len(data["records"])}


def publish_operational_logged():
    try:
        logging.getLogger("mkh.sources").info("operational_wave %s", json.dumps(publish_operational_snapshot()))
    except Exception as error:
        logging.getLogger("mkh.sources").warning("operational_wave publication_failed error_class=%s", type(error).__name__)
