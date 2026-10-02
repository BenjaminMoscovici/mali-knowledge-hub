"""Reproducible ingestion of public aggregate 3W and DTM spreadsheets.

Only selected worksheets/columns are read. Village/site information is omitted.
Source row numbers, blank values, reference periods and matching conflicts survive.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile

from source_foundation import stable_id
from source_wave import _fold, snapshot_path, _parent_path

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SECTORS = {"sante": "health", "protection": "protection", "nutrition": "nutrition",
           "secal": "food_security", "eha": "wash", "education": "education",
           "abris nfi": "shelter", "coordination": "coordination"}


def worksheet(path, number):
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(item.itertext()) for item in ET.fromstring(
                archive.read("xl/sharedStrings.xml")).findall("x:si", NS)]
        for row in ET.fromstring(archive.read(f"xl/worksheets/sheet{number}.xml")).findall(".//x:row", NS):
            values = {}
            for cell in row.findall("x:c", NS):
                column = re.sub(r"\d", "", cell.attrib["r"])
                value = cell.findtext("x:v", "", NS)
                if cell.get("t") == "s" and value:
                    value = strings[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = "".join(cell.find("x:is", NS).itertext())
                values[column] = value.strip()
            yield int(row.attrib["r"]), values


class GeoMatcher:
    def __init__(self):
        self.db = sqlite3.connect(f"file:{snapshot_path()}?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.codes = {}
        for row in self.db.execute("select i.identifier,u.* from mkh_geo_identifiers i join mkh_geo_units u on u.id=i.unit_id"):
            self.codes.setdefault(row["identifier"].upper(), []).append(dict(row))

    def match(self, geography):
        matched, issues, parent = {}, [], None
        for level in ("region", "cercle"):
            label, code = geography.get(level, ""), geography.get(level + "_pcode", "").upper()
            candidates = [u for u in self.codes.get(code, []) if u["level"] == level]
            candidates = [u for u in candidates if _fold(u["name"]) == _fold(label)
                          and (level == "region" or (parent and u["parent_id"] == parent))]
            if len(candidates) == 1:
                u = candidates[0]
                matched[level] = {"unit_id": u["id"], "release_id": u["release_id"],
                                  "name": u["name"], "method": "pcode_name_parent_exact"}
                parent = u["id"]
            else:
                issues.append({"level": level, "label": label, "pcode": code,
                               "reason": "code_name_or_parent_conflict" if code in self.codes else "code_unavailable"})
                parent = None
        # INSTAT commune labels are a different geography vintage; no automatic crosswalk.
        if geography.get("commune"):
            issues.append({"level": "commune", "label": geography["commune"],
                           "reason": "source_label_only_no_approved_commune_crosswalk"})
        return {"matches": matched, "issues": issues}


def release_tables(meta, resource, path, dataset_id, source_id, start, end, version, count, limitations):
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    release_id = stable_id(dataset_id, checksum, "operational-wave/1")
    run_id = stable_id(release_id, "validated-import")
    retrieved = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    published = resource["created"][:10]
    tables = {
        "mkh_sources": [{"id": source_id, "provider": meta["organization"]["title"],
                         "title": meta["title"], "url": "https://data.humdata.org/dataset/" + meta["id"]}],
        "mkh_datasets": [{"id": dataset_id, "source_id": source_id, "title": resource["name"],
                           "refresh_policy": "check quarterly; immutable releases", "current_release_id": None}],
        "mkh_ingestion_runs": [{"id": run_id, "dataset_id": dataset_id, "started_at": retrieved,
                                "finished_at": retrieved, "status": "succeeded", "release_id": release_id, "error_class": None}],
        "mkh_source_releases": [{"id": release_id, "dataset_id": dataset_id, "checksum": checksum,
            "upstream_version": version, "retrieved_at": retrieved, "publication_date": published,
            "reference_start": start, "reference_end": end, "source_url": resource["url"],
            "original_file": path.name, "license": meta["license_title"],
            "license_url": "https://creativecommons.org/licenses/by/3.0/igo/" if source_id == "ocha-mali-3w" else "https://creativecommons.org/licenses/by/4.0/",
            "attribution": meta["organization"]["title"], "access": "public_aggregate",
            "transformation": "operational-wave/1; selected worksheets; village/site fields excluded",
            "quality_json": {"records": count, "limitations": limitations}, "run_id": run_id,
            "status": "validated_with_limitations"}],
        "mkh_evidence_spans": [], "mkh_source_records": [],
    }
    return tables, release_id


def ingest(directory, output):
    matcher = GeoMatcher()
    combined = {"tables": {}, "records": [], "releases": {}, "registry": []}
    jobs = [("ocha_3w_metadata.json", "mali_3w_q1_2026.xlsx", "mli-ocha-3w-2026-q1", "ocha-mali-3w", "2026-01-01", "2026-03-31", "Q1 2026"),
            ("dtm_baseline_metadata.json", "dtm_round83.xlsx", "mli-dtm-round83", "iom-dtm-mali", "2025-09-01", "2025-09-30", "Round 83 September 2025")]
    for metadata, filename, dataset, source, start, end, version in jobs:
        meta = json.loads((directory / metadata).read_text())
        resource = next(r for r in meta["resources"] if ("Q1_2026" in r["name"] if source == "ocha-mali-3w" else "83" in r["name"]))
        records = []
        if source == "ocha-mali-3w":
            limitations = ["Presence records only: activity, project title, start/end dates, targets and reached fields are empty in this release.",
                           "Rows may repeat an actor/sector/location; row counts are not unique projects or beneficiaries.",
                           "Commune labels/P-codes remain unverified; village fields are excluded."]
            for row, v in worksheet(directory / filename, 2):
                if row == 1 or not all(v.get(c) for c in ("A", "G", "O")):
                    continue
                if any(v.get(c) for c in ("Q", "R", "S", "T", "V", "AF")):
                    raise ValueError("3W release changed: delivery fields require a reviewed mapping")
                geo = {"region": v["G"], "region_pcode": v.get("F", ""), "cercle": v.get("I", ""),
                       "cercle_pcode": v.get("H", ""), "commune": v.get("M", ""), "commune_pcode": v.get("L", "")}
                payload = {"organization": v["B"], "acronym": v["A"], "organization_type": v["C"],
                           "sector_raw": v["O"], "sector": SECTORS.get(_fold(v["O"]), "unmapped"),
                           "activity_status": "presence_only", "activity": None, "project_title": None,
                           "start_date": None, "end_date": None, "targeted": None, "reached": None,
                           "geography": geo, "geo_resolution": matcher.match(geo)}
                records.append({"source_type": "operational_presence", "sheet": "ML_3W", "row": row, "payload": payload})
        else:
            limitations = ["September 2025 stock assessment, not a current 2026 count or movement flow.",
                           "Commune aggregates only; no microdata/sites. Commune joins require approved crosswalks.",
                           "Sheet RAPATRIES is repatriated persons, distinct from returned IDPs. No return flow or durable-return outcome is established.",
                           "Metadata caveat still refers to Round 81; the ingested file/resource explicitly identifies Round 83."]
            for number, sheet, category in [(1, "PDIs", "internally_displaced"), (2, "RETOURNEES_PDIs", "returned_idps"), (3, "RAPATRIES", "repatriated_persons")]:
                for row, v in worksheet(directory / filename, number):
                    if row == 1 or not v.get("E"):
                        continue
                    geo = {"region": v["A"], "region_pcode": v["B"], "cercle": v["C"], "cercle_pcode": v["D"], "commune": v["E"]}
                    value = int(v["R"] if number < 3 else v["P"])
                    female = int(v["P"]) if number < 3 else (sum(int(v[c]) for c in ("G", "J", "M")) if all(v.get(c) for c in ("G", "J", "M")) else None)
                    male = int(v["Q"]) if number < 3 else (sum(int(v[c]) for c in ("H", "K", "N")) if all(v.get(c) for c in ("H", "K", "N")) else None)
                    if female is not None and male is not None and female + male != value:
                        raise ValueError(f"DTM sex totals conflict: {sheet}:{row}")
                    payload = {"category": category, "measure": "stock", "value": value, "unit": "people",
                               "female": female, "male": male, "households": int(v["F"]), "round": 83,
                               "methodology": "DTM Baseline Assessment; public commune aggregates; collection dates/sampling detail absent in workbook",
                               "geography": geo, "geo_resolution": matcher.match(geo)}
                    records.append({"source_type": "displacement_stock", "sheet": sheet, "row": row, "payload": payload})
        tables, release_id = release_tables(meta, resource, directory / filename, dataset, source, start, end, version, len(records), limitations)
        for record in records:
            locator = f"{filename} / {record['sheet']} / row {record['row']}"
            record_id = stable_id(release_id, locator)
            record.update({"id": record_id, "release_id": release_id, "dataset_id": dataset, "locator": locator,
                           "reference_start": start, "reference_end": end, "version": version,
                           "retrieved_at": tables["mkh_source_releases"][0]["retrieved_at"], "source_url": resource["url"]})
            tables["mkh_evidence_spans"].append({"id": record_id, "release_id": release_id,
                "original_record_id": str(record["row"]), "page": None, "printed_page": None,
                "section": record["sheet"], "passage": json.dumps(record["payload"], ensure_ascii=False), "locator": locator})
            tables["mkh_source_records"].append({"id": record_id, "release_id": release_id, "span_id": record_id,
                "source_type": record["source_type"], "reference_start": start, "reference_end": end,
                "payload": record["payload"]})
        for table, rows in tables.items():
            combined["tables"].setdefault(table, []).extend(rows)
        combined["records"].extend(records)
        combined["releases"][dataset] = release_id
        combined["registry"].append({"provider": meta["organization"]["title"], "source_name": resource["name"],
            "analytical_use": "actors and sectors present" if source == "ocha-mali-3w" else "displaced/returned/repatriated population stocks",
            "authoritative_status": "provider publication on HDX", "access_route": resource["url"], "format": "XLSX",
            "authentication": "none", "licence": meta["license_title"], "sensitivity": "public aggregates; site/village fields excluded",
            "geographic_granularity": "source region/cercle/commune labels; COD validation region/cercle only",
            "temporal_granularity": version, "update_frequency": "quarterly/assessment round", "historical_coverage": f"{start} to {end} in this release",
            "last_successful_retrieval": tables["mkh_source_releases"][0]["retrieved_at"], "integration_status": "public_access_confirmed",
            "limitations": limitations, "fallback_source": "provider report/next public HDX release", "next_action": "deploy and verify user answers",
            "responsible_party": "MKH source maintainer", "records": len(records), "checksum": tables["mkh_source_releases"][0]["checksum"]})
    matcher.db.close()
    with gzip.GzipFile(filename=str(output), mode="wb", mtime=0) as target:
        target.write(json.dumps(combined, ensure_ascii=False, separators=(",", ":")).encode())
    print(json.dumps({"records": Counter(r["source_type"] for r in combined["records"]),
                      "dtm_population": {c: sum(r["payload"]["value"] for r in combined["records"] if r["payload"].get("category") == c)
                                         for c in ("internally_displaced", "returned_idps", "repatriated_persons")},
                      "matching_issues": Counter(i["reason"] for r in combined["records"] for i in r["payload"]["geo_resolution"]["issues"])}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    ingest(args.directory, args.output)
