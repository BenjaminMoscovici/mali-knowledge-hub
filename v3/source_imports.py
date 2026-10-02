"""Repeatable imports of official Mali COD and INSTAT publications.

Only public aggregate files are accepted. Network discovery and fetching are
separate from parsing so replay never requires a live external service.
"""
import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile

from normalization import key
from source_foundation import SourceStore, release_identity, stable_id, validate_package

INSTAT_INDEX = "https://www.instat-mali.org/fr/publications/recensement-general-de-la-population-et-de-lhabitat-rgph"
INSTAT_LOCALITIES = "https://www.instat-mali.org/laravel-filemanager/files/shares/rgph/repvila-rgph5_rgph.pdf"
INSTAT_TERMS = "https://www.instat-mali.org/laravel-filemanager/files/shares/doc/conditions-utilisation-donnees-ouvertes_doc.pdf"
INSTAT_ATTRIBUTION = ("Ce produit a été adapté à partir des informations de l’Institut national de la "
    "statistique du Mali, qui sont sous licence conformément à l’Accord de licence de données ouvertes de l’INSTAT.")


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def base_package(path, *, source, dataset, version, url, license, license_url,
                 attribution, publication_date=None, reference_start=None, reference_end=None):
    digest = checksum(path)
    return {"source": source, "dataset": dataset, "release": {
        "id": release_identity(dataset["id"], digest, version), "checksum": digest,
        "upstream_version": version, "retrieved_at": datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(),
        "source_url": url, "original_file": Path(path).name, "license": license,
        "license_url": license_url, "attribution": attribution, "access": "public_aggregate",
        "publication_date": publication_date, "reference_start": reference_start,
        "reference_end": reference_end, "quality": {}},
        "units": [], "spans": [], "population": [], "pages": []}


def import_cod(path, metadata_path):
    metadata = json.loads(Path(metadata_path).read_text())["result"]
    resource = next((r for r in metadata["resources"] if r["format"].casefold() == "geojson"), None)
    if not resource or metadata.get("license_id") != "cc-by-igo":
        raise ValueError("Review changed COD resource or licence before importing")
    with zipfile.ZipFile(path) as archive:
        features = []
        for level in range(3):
            name = f"mli_admin{level}.geojson"
            if archive.getinfo(name).file_size > 40_000_000: raise ValueError("Oversized GIS resource")
            data = json.loads(archive.read(name))
            if data.get("type") != "FeatureCollection": raise ValueError("Invalid GIS collection")
            features.extend((level, f) for f in data["features"])
    versions = {f["properties"]["version"] for _, f in features}
    if len(versions) != 1: raise ValueError("Mixed COD boundary versions")
    p = base_package(path, source={"id": "ocha-cod", "provider": "OCHA FISS / HDX",
        "title": metadata["title"], "url": "https://data.humdata.org/dataset/cod-ab-mli"},
        dataset={"id": "mli-cod-ab", "title": metadata["title"],
                 "refresh_policy": "Monthly metadata check; import changed official resource checksum"},
        version=next(iter(versions)), url=resource["url"], license=metadata["license_title"],
        license_url="https://creativecommons.org/licenses/by/3.0/igo/", attribution="OCHA FISS / HDX, Mali COD-AB")
    release = p["release"]["id"]
    seen = set()
    for level, f in features:
        props = f["properties"]
        code = str(props[f"adm{level}_pcode"]).strip()
        if not re.fullmatch(r"ML(?:\d{2}){0,2}", code) or code in seen:
            raise ValueError("Invalid or duplicate Mali P-code")
        seen.add(code)
        geometry = f.get("geometry")
        if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"} or not geometry.get("coordinates"):
            raise ValueError("Missing boundary geometry")
        p["units"].append({"id": stable_id(release, code), "original_record_id": code,
            "parent_id": stable_id(release, str(props[f"adm{level-1}_pcode"]).strip()) if level else None,
            "name": props.get(f"adm{level}_name1") or props[f"adm{level}_name"],
            "aliases": [props[f"adm{level}_name"]], "level": ("country", "region", "cercle")[level],
            "name_languages": {props[f"adm{level}_name"]: props.get("lang"),
                               props.get(f"adm{level}_name1"): props.get("lang1")},
            "identifiers": {"ocha_pcode": code}, "boundary_version": props["version"],
            "valid_on": props.get("valid_on"), "valid_to": props.get("valid_to"), "geometry": geometry})
    counts = Counter(u["level"] for u in p["units"])
    expected = {}
    for level, label in ((1, "region"), (2, "cercle")):
        match = re.search(rf"Admin\s*{level}:\s*(\d+)", metadata.get("notes", ""), re.I)
        if not match: raise ValueError("Missing advertised COD record count")
        expected[label] = int(match.group(1))
    if counts["country"] != 1 or any(counts[level] != n for level, n in expected.items()):
        raise ValueError("COD completeness check failed")
    p["release"]["quality"] = {"unit_counts": dict(counts), "advertised_counts": expected,
        "metadata_modified": metadata.get("metadata_modified"),
        "limitations": ["COD provides levels 0–2 only; no commune or locality boundaries.",
                         "Government and HAPI identifiers require release-specific reconciliation."]}
    return validate_package(p)


def _numeric(value):
    if not re.fullmatch(r"\d[\d ]*", value): raise ValueError("Invalid integer cell")
    return int(value.replace(" ", ""))


def _table_rows(pages):
    """Parse publisher table columns, retaining every consumed line and locator."""
    for page in pages:
        pending = None
        if page["page"] < 9: continue
        table = "Population en 2023" in page["content"]
        if not table: continue
        for line_no, line in enumerate(page["layout"].splitlines(), 1):
            cells = re.split(r"\s{2,}", line.strip())
            if len(cells) == 1 and re.search(r"[A-ZÉÈ]", cells[0]) and line.startswith("   "):
                pending = (cells[0], line, line_no)
                continue
            raw = line
            locator_line = line_no
            if (len(cells) == 6 and all(re.fullmatch(r"\d[\d ]*", s) for s in cells[:3])
                    and re.fullmatch(r"\d+,\d|-", cells[3])):
                if not pending: raise ValueError(f"Missing row label on PDF page {page['page']}")
                cells.insert(0, pending[0]); raw = pending[1] + "\n" + line; locator_line = pending[2]
            if (len(cells) in {6, 7} and all(re.fullmatch(r"\d[\d ]*", s) for s in cells[1:4])
                    and re.fullmatch(r"\d+,\d|-", cells[4])):
                pending = None
                yield {"page": page["page"], "line": locator_line, "label": cells[0],
                    "male": _numeric(cells[1]), "female": _numeric(cells[2]), "total": _numeric(cells[3]),
                    "locality_count": _numeric(cells[5]), "residence": cells[6] if len(cells) == 7 else None,
                    "passage": raw.strip(), "printed_page": str(page["page"] - 5)}
            elif re.search(r"\s[RU]\s*$", line):
                raise ValueError(f"Unparsed population row on page {page['page']}")


def import_instat_localities(path):
    import pymupdf
    with pymupdf.open(path) as doc:
        if len(doc) != 538: raise ValueError("Changed INSTAT edition; review parser and version metadata")
        pages = [{"page": i + 1, "content": page.get_text(), "layout": page.get_text(sort=True)}
                 for i, page in enumerate(doc)]
    if not all(term in pages[5]["content"] for term in ("2023", "projections", "DNP")):
        raise ValueError("Projection methodology absent")
    p = base_package(path, source={"id": "instat-mali", "provider": "INSTAT Mali / BCR",
        "title": "INSTAT official census publications", "url": INSTAT_INDEX},
        dataset={"id": "mli-instat-localities-2023", "title": "RGPH5 — Répertoire des localités du Mali en 2023",
                 "refresh_policy": "Quarterly official publication index check; reviewed edition-specific import"},
        version="edition-2023-published-2026-01", url=INSTAT_LOCALITIES,
        license="INSTAT Accord de licence de données ouvertes", license_url=INSTAT_TERMS,
        attribution=INSTAT_ATTRIBUTION, reference_start="2023-01-01", reference_end="2023-12-31")
    # The cover specifies a publication month, not a publication day.
    p["release"]["quality"]["publication_month"] = "2026-01"
    p["pages"] = [{"page": page["page"], "content": page["content"]} for page in pages]
    rows = list(_table_rows(pages))
    summaries = {row["label"]: row for row in rows if row["page"] == 9}
    if "MALI" not in summaries or len(summaries) != 21: raise ValueError("Missing national summary")
    release = p["release"]["id"]
    parents, expected_localities, parsed_localities = {}, {}, Counter()
    locality_by_parent = Counter()
    rounding, duplicates = [], []
    source_paths = set()
    for row in [summaries["MALI"]] + [r for r in rows if r["page"] >= 11]:
        label = row["label"]
        if label == "MALI": level, name, parent = "country", "Mali", None
        elif re.match(r"R[ÉE]GION DE |DISTRICT DE ", label):
            level, name, parent = "region", re.sub(r"^(?:R[ÉE]GION DE |DISTRICT DE )", "", label), parents["country"]
            parents.pop("cercle", None); parents.pop("commune", None); parents.pop("arrondissement", None)
            expected_localities[name] = row["locality_count"]
        elif label.startswith("CERC."):
            level, name, parent = "cercle", label[5:].strip(), parents["region"]
            parents.pop("commune", None); parents.pop("arrondissement", None)
        elif label.startswith("COM."):
            level, name, parent = "commune", label[4:].strip(), parents["cercle"]
        elif label.startswith("ARRONDISSEMENT"):
            level, name, parent = "arrondissement", label, parents["region"]
        else:
            level, name, parent = "locality", label, parents.get("commune") or parents.get("arrondissement")
            if parent is None: raise ValueError("Locality without parent")
        path = (parent, level, key(name))
        if path in source_paths:
            duplicates.append({"page": row["page"], "name": name, "level": level})
        source_paths.add(path)
        # Source locator disambiguates repeated labels; never invent a government code.
        record = f"pdf:{row['page']}:line:{row['line']}"
        uid = stable_id(release, record)
        p["units"].append({"id": uid, "parent_id": parent, "level": level,
            "name": name, "name_languages": {name: "fr"},
            "unit_type": "district" if label.startswith("DISTRICT DE") else level,
            "boundary_version": "INSTAT-reorganisation-territoriale-2023",
            "valid_on": None, "valid_to": None, "original_record_id": record, "identifiers": {}})
        if level != "locality": parents[level] = uid
        if level == "region": current_region = name
        if level == "locality":
            parsed_localities[current_region] += 1; locality_by_parent[parent] += 1
        span = stable_id(release, record, "span")
        p["spans"].append({"id": span, "original_record_id": record, "page": row["page"],
            "printed_page": row["printed_page"], "section": label, "passage": row["passage"],
            "locator": f"PDF page {row['page']}, extracted layout line {row['line']}"})
        for sex in ("male", "female", "total"):
            p["population"].append({"id": stable_id(uid, sex), "unit_id": uid, "span_id": span,
                "sex": sex, "value": row[sex], "unit": "people", "reference_start": "2023-01-01",
                "reference_end": "2023-12-31", "methodology": "DNP 2023 projection based on RGPH5 2022; publisher rounding retained",
                "geographic_precision": level})
        if abs(row["male"] + row["female"] - row["total"]) > 1:
            rounding.append({"page": row["page"], "name": name, "difference": row["male"] + row["female"] - row["total"]})
    if rounding: raise ValueError("Population sex subtotals differ beyond stated rounding tolerance")
    differences = [{"region": name, "reported_localities": count, "parsed_localities": parsed_localities[name]}
                   for name, count in expected_localities.items() if count != parsed_localities[name]]
    counts = Counter(u["level"] for u in p["units"])
    if counts["country"] != 1 or counts["region"] != 20 or counts["locality"] < 12_000:
        raise ValueError("Incomplete INSTAT geographic extraction")
    p["release"]["quality"].update({"unit_counts": dict(counts), "population_observations": len(p["population"]),
        "reported_national_localities": summaries["MALI"]["locality_count"],
        "locality_count_discrepancies": differences, "duplicate_name_paths": duplicates,
        "limitations": ["2023 projected populations, not enumerated 2022 counts or current population.",
            "No government geographic identifiers are printed in the extracted tables.",
            "Two regional locality count discrepancies remain under review; no missing rows manufactured.",
            "Publisher rounds totals; sex subtotals may differ by one person.",
            "Bamako arrondissements retain their source level; not silently renamed cercles or communes."]})
    return validate_package(p)


def import_instat_census_document(path):
    import pymupdf
    url = "https://www.instat-mali.org/laravel-filemanager/files/shares/rgph/rapport-resultats-globaux-rgph5_rgph.pdf"
    p = base_package(path, source={"id": "instat-mali", "provider": "INSTAT Mali / BCR",
        "title": "INSTAT official census publications", "url": INSTAT_INDEX},
        dataset={"id": "mli-instat-rgph5-global-2022", "title": "RGPH5 — Rapport préliminaire, résultats globaux",
                 "refresh_policy": "Quarterly official publication index check; changed-file import"},
        version="RGPH5-2022-preliminaire-2023-11", url=url, license="INSTAT Accord de licence de données ouvertes",
        license_url=INSTAT_TERMS, attribution=INSTAT_ATTRIBUTION,
        reference_start="2022-01-01", reference_end="2022-12-31")
    with pymupdf.open(path) as doc:
        p["pages"] = [{"page": i + 1, "content": page.get_text()} for i, page in enumerate(doc)]
    if not p["pages"] or not any("2022" in page["content"] for page in p["pages"][:8]):
        raise ValueError("Invalid RGPH5 census document")
    if "RAPPORT PRELIMINAIRE" not in p["pages"][0]["content"]:
        raise ValueError("Changed census report edition; review publication status")
    p["release"]["quality"] = {"pages": len(p["pages"]), "publication_month": "2023-11",
        "limitations": ["Document only; no structured census denominators extracted in this stage.",
            "Reference year recorded, exact enumeration dates not inferred.",
            "Historical geography is not merged with later boundary releases."]}
    return validate_package(p)


def import_hpc_needs(path, metadata_path):
    metadata = json.loads(Path(metadata_path).read_text())["result"]
    resource = next(r for r in metadata["resources"] if r["name"] == "Global HPC HNO 2026")
    if metadata.get("license_id") != "cc-by-igo": raise ValueError("Review changed HPC licence")
    p = base_package(path, source={"id": "ocha-hpc", "provider": "OCHA HPC / HDX",
        "title": "Global Humanitarian Programme Cycle, Humanitarian Needs", "url": "https://data.humdata.org/dataset/global-hpc-hno"},
        dataset={"id": "mli-hpc-hno-2026", "title": "Mali — Global HPC HNO 2026 national snapshot",
                 "refresh_policy": "Monthly resource metadata/hash check; retain historical releases"},
        version="HPC-HNO-2026", url=resource["url"], license=metadata["license_title"],
        license_url="https://creativecommons.org/licenses/by/3.0/igo/", attribution="OCHA HPC / HDX, Global HPC HNO 2026",
        reference_start="2026-01-01", reference_end="2026-12-31")
    rid = p["release"]["id"]
    uid = stable_id(rid, "MLI")
    p["units"] = [{"id": uid, "parent_id": None, "name": "Mali", "level": "country",
        "boundary_version": "HPC-ISO3-national-2026", "original_record_id": "MLI",
        "identifiers": {"iso3": "MLI"}}]
    p["humanitarian"] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"Country ISO3", "Description", "Cluster", "Category", "Population", "In Need", "Targeted", "Affected", "Reached"}
        if not required.issubset(set(reader.fieldnames or [])): raise ValueError("Changed HPC CSV schema")
        for line, row in enumerate(reader, 2):
            if row["Country ISO3"] != "MLI": continue
            record = f"{resource['id']}:csv-line:{line}"
            sid = stable_id(rid, record, "span")
            p["spans"].append({"id": sid, "original_record_id": record,
                "section": row["Description"], "passage": json.dumps(row, ensure_ascii=False, sort_keys=True),
                "locator": f"CSV line {line}, resource {resource['id']}"})
            for column, status in (("Population", "all"), ("In Need", "INN"), ("Targeted", "TGT"), ("Affected", "AFF"), ("Reached", "REA")):
                if not row[column].strip(): continue
                p["humanitarian"].append({"id": stable_id(rid, record, status), "unit_id": uid,
                    "span_id": sid, "sector": row["Cluster"], "category": row["Category"],
                    "population_status": status, "value": _numeric(row[column]), "unit": "people",
                    "reference_start": "2026-01-01", "reference_end": "2026-12-31",
                    "methodology": row["Description"], "geographic_precision": "country"})
    if not p["humanitarian"]: raise ValueError("No Mali observations in HPC file")
    p["release"]["quality"] = {"mali_source_rows": len(p["spans"]), "observations": len(p["humanitarian"]),
        "resource_hdx_id": resource["id"], "metadata_modified": metadata.get("metadata_modified"),
        "limitations": ["National GHO estimates only; no region, cercle or commune allocation.",
            "Official upstream source used by HAPI, not a replacement for subnational HAPI snapshots.",
            "Missing affected/reached cells are not zero; needs and targets remain separate.",
            "Reference year 2026 inferred from official resource title, with year precision."]}
    return validate_package(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    store = SourceStore(args.database)
    packages = [import_cod(args.source_dir / "mli_admin_boundaries.geojson.zip", args.source_dir / "hdx_cod_metadata.json"),
                import_instat_localities(args.source_dir / "instat_localities_2023.pdf"),
                import_instat_census_document(args.source_dir / "instat_rgph5_global_2022.pdf")]
    if (args.source_dir / "hpc_hno_2026.csv").exists():
        packages.append(import_hpc_needs(args.source_dir / "hpc_hno_2026.csv", args.source_dir / "hpc_metadata.json"))
    results = []
    for package in packages:
        result = store.publish(package)
        results.append({**result, "dataset": package["dataset"], "release": package["release"]})
    proposals = store.crosswalk_proposals("mli-cod-ab", "mli-instat-localities-2023")
    args.manifest.write_text(json.dumps({"deployment_status": "local_staging_only", "results": results,
        "proposed_crosswalks": proposals, "freshness": store.freshness()}, ensure_ascii=False, indent=2))
    print(json.dumps({"imports": [{"dataset": x["dataset"]["id"], "status": x["status"]} for x in results],
                      "proposed_crosswalks": proposals}, ensure_ascii=False))
    store.close()


if __name__ == "__main__": main()
