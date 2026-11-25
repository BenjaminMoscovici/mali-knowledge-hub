"""Convert pinned, previously published MKH releases to V3 manifests (offline)."""

import argparse
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

from import_public_releases import CANON, write

PACKAGES = {
    "country_indicators.json.gz": "4bfe2d12473971f75658682d16d92d349979de83015b51889e69a519dbb3ae00",
    "source_wave3.json.gz": "00747de8be87456017e7ba73736e1376ed3e7972ee1b5a964cb73726d0fde116",
    "source_wave4.json.gz": "7aec60127058227f61e448bb582632bedb2683d6510bfc9117efd07a902fbfc1",
    "source_wave5.json.gz": "2a4075078bf3b9dc98de7fc143f260aa88d5db136c1292e922f835305cde62ef",
    "source_wave1.sqlite.gz": "5a03538be3e1997f6d988fc41290df56e43c836352677ea81fc89bda7e1b0ea4",
    "country_foundation.sqlite.gz": "4879972b64658d616d453f3cc02e32cfd1fe1c93df0a0a4ce8add1f00d6bf953",
}
# Each projection preserves the native record grain. Unverified financial fields are excluded.
TABLES = {
    "mli-fts-requirements-funding": (
        "fts_plans", "country name plan_code plan_id year requirements funding percent_funded_reported currency funding_definition provider_updated_at",
        ["financement humanitaire", "besoins financiers", "appeal", "requirements", "reported funding"],
        ["name", "plan_code", "year"]),
    "mli-world-bank-v3": (
        "bank_projects", "project_id title country status board_date_reported closing_date_reported borrower implementing_agency",
        ["projet", "Banque mondiale", "emprunteur", "portefeuille", "development projects"],
        ["project_id", "title", "implementing_agency"]),
    "mli-iati-worldbank": (
        "iati_activities", "activity_id project_id publisher title status start_date_reported end_date_reported country",
        ["activité", "coopération", "projets", "intervention", "aid transparency"],
        ["activity_id", "project_id", "title"]),
}
EVALUATIONS = {"mli-ieg-p144442", "mli-ieg-p160641"}
PROGRAMMING = {"mli-eu-original-programming", "mli-eu-current-overview"}


def package(directory, name):
    raw = (directory / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PACKAGES[name]:
        raise ValueError("Input differs from the reviewed MKH release: " + name)
    return gzip.decompress(raw)


def append_wave(data, selected):
    for release in data["tables"]["mkh_source_releases"]:
        key = release["dataset_id"]
        if key not in selected:
            continue
        assert release["access"] == "public_aggregate" and release["status"] in {"validated", "validated_with_limitations"}
        registry = next(r for r in data["registry"] if r["checksum"] == release["checksum"])
        assert registry["integration_status"] == "public_access_confirmed"
        records = [r for r in data["records"] if r["release_id"] == release["id"]]
        source = {
            "id": key, "review": "published", "release": release["upstream_version"], "release_id": release["id"],
            "title": registry["source_name"], "publisher": registry["provider"], "url": release["source_url"],
            "period": registry["historical_coverage"], "geography": registry["geographic_granularity"],
            "license": release["license"], "attribution": release["attribution"], "retrieved_at": release["retrieved_at"],
            "upstream_checksum": release["checksum"], "update_policy": registry["update_frequency"],
            "limitations": registry["limitations"], "description": registry["source_name"] + ". " + registry["limitations"][0],
            "topics": [registry["analytical_use"].replace("_", " ")],
        }
        if key in TABLES:
            table, projection, topics, search = TABLES[key]
            columns = {k: "TEXT" for k in ["id", *projection.split(), "locator"]}
            if key == "mli-fts-requirements-funding":
                columns.update(year="INTEGER", requirements="REAL", funding="REAL", percent_funded_reported="REAL")
                source["definitions"] = {"grain": "One plan, unspecified plan or other funding category per year as reported. Inspect plan identity before aggregation.",
                                         "amounts": "Reported USD. Requirements and funding are distinct. Missing amounts are unknown."}
            else:
                source["entity_keys"] = {"World Bank project ID": "project_id"}
            rows = [{"id": r["id"], "locator": r["locator"], **{k: r["payload"].get(k) for k in projection.split()}}
                    for r in records]
            source.update(type="dataset", table=table, columns=columns, records=rows, search_fields=search)
            source["topics"].extend(topics)
        else:
            source.update(type="document", passages=[])
            for r in records:
                p = r["payload"]
                if key in EVALUATIONS:
                    text = f"{p['finding']} {p['methodology']}. {p['transferability']}"
                    tags = [p["project_id"], p["finding_kind"], p["document_title"], "évaluation indépendante", "lessons"]
                else:
                    facts = json.dumps(p["facts"], ensure_ascii=False)
                    text = f"{p['title']}. {facts}. {p['limitations']}"
                    tags = [p["evidence_stage"], *p["sectors"], "Union européenne", "programmation"]
                source["passages"].append({"kind": "factual_extract", "page": r.get("page"),
                    "locator": r["locator"], "text": text, "topics": tags,
                    "period": r["reference_start"] + " to " + r["reference_end"]})
                source["topics"].extend(tags)
            source["topics"] = list(dict.fromkeys(source["topics"]))
        write(source)


def indicators(directory):
    data = json.loads(package(directory, "country_indicators.json.gz"))
    connection = json.loads((CANON / "world-bank-wdi-mli.json").read_text())
    rows = []
    for series in data["series"]:
        key, label = series["indicator_id"], series["metadata"]["name"]
        connection["series"][key] = {"label": label, "unit": series["unit"]}
        for obs in series["observations"]:
            rows.append({"id": f"{key}/{obs['year']}", "indicator": key, "label": label, "unit": series["unit"],
                         "year": obs["year"], "value": obs["value"], "domain": series["domain"],
                         "locator": f"World Development Indicators / MLI / {key} / {obs['year']}"})
    topics = list(dict.fromkeys(s["domain"] for s in data["series"]))
    connection["topics"] = list(dict.fromkeys(connection["topics"] + topics))
    connection["description"] = "National World Development Indicators available through the approved live API."
    connection["limitations"] = data["limitations"]
    write(connection)
    write({"id": data["dataset_id"], "review": "published", "type": "dataset", "title": "World Development Indicators · national observation snapshot",
           "publisher": "World Bank and attributed indicator providers", "license": data["license"],
           "release": data["retrieved_at"], "period": "2015–2026 retrieval window, missing years vary by series",
           "geography": data["geographic_framework"], "url": "https://data.worldbank.org/country/mali",
           "topics": topics + ["indicateurs", "électricité", "scolarisation", "PIB", "eau", "emploi", "sanitation"],
           "description": "Annual comparable national observations with indicator definitions, original units and reference years.",
           "definitions": {s["indicator_id"]: {"label": s["metadata"]["name"], "unit": s["unit"],
               "definition": s["metadata"]["sourceNote"], "attribution": s["metadata"]["sourceOrganization"],
               "original": s["data_url"], "checksum": s["response_sha256"]} for s in data["series"]},
           "limitations": data["limitations"], "table": "national_indicators",
           "columns": {"id": "TEXT", "indicator": "TEXT", "label": "TEXT", "unit": "TEXT", "year": "INTEGER",
                       "value": "REAL", "domain": "TEXT", "locator": "TEXT"}, "records": rows})


def boundaries(directory):
    # Shapely is required for this offline import only. Never use display geometry for measurement.
    from shapely import from_geojson, to_geojson
    db = sqlite3.connect(":memory:")
    db.deserialize(package(directory, "source_wave1.sqlite.gz"))
    metrics = sqlite3.connect(":memory:")
    metrics.deserialize(package(directory, "country_foundation.sqlite.gz"))
    db.row_factory = metrics.row_factory = sqlite3.Row
    release = db.execute("select * from mkh_source_releases where dataset_id='mli-cod-ab'").fetchone()
    measures = {r["unit_id"]:r for r in metrics.execute("select * from foundation_boundary_metrics")}
    rows, geometry = [], {}
    units = db.execute("select * from mkh_geo_units where release_id=? and level='region' order by name", (release["id"],))
    for unit in units:
        code = unit["original_record_id"]
        m = measures[unit["id"]]
        geometry[code] = json.loads(to_geojson(from_geojson(unit["geometry_json"]).simplify(.025, preserve_topology=True)))
        rows.append({"id": unit["id"], "place": unit["name"], "pcode": code, "area_km2": m["area_km2"],
                     "level": "region", "locator": "COD v03 / ADM1 / " + code})
    write({"id": release["dataset_id"], "type":"dataset", "review":"published", "title":"Mali administrative region boundaries · COD v03",
           "publisher":"OCHA FISS / HDX", "period":"Boundary release v03, valid from 2025-09-04",
           "release":release["upstream_version"], "release_id":release["id"], "url":release["source_url"],
           "license":release["license"], "upstream_checksum":release["checksum"], "geography":"Mali ADM1, COD v03",
           "description":"Official humanitarian common operational dataset, region polygons, identifiers and geodesic areas.",
           "topics":["administrative boundaries","limites régionales","carte","superficie","map","area","P-code"],
           "limitations":["Display polygons are simplified by 0.025 degrees. Area uses the original geometry.",
                          "COD region identifiers establish no equivalence with older CH areas or INSTAT census units."],
           "table":"cod_regions","columns":{"id":"TEXT","pcode":"TEXT","place":"TEXT","area_km2":"REAL","level":"TEXT","locator":"TEXT"},
           "definitions":{"area_km2":measures[rows[0]["id"]]["method"]}, "map_key":"pcode",
           "geometries":geometry,"records":rows,"search_fields":["pcode","place"]})
    db.close()
    metrics.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy_dir", type=Path)
    parser.add_argument("--include-programming", action="store_true")
    args = parser.parse_args()
    selected = set(TABLES) | EVALUATIONS
    if args.include_programming:
        selected |= PROGRAMMING
    for file in PACKAGES:
        if file.startswith("source_wave") and file.endswith(".json.gz"):
            append_wave(json.loads(package(args.legacy_dir, file)), selected)
    boundaries(args.legacy_dir)
    indicators(args.legacy_dir)
