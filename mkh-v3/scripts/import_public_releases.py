"""Extract approved public evidence from the pinned V2.1 release packages."""

import argparse
import gzip
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

CANON = Path(__file__).resolve().parents[1] / "canon"
CH_ID = "mli-ch-late2025"
CILSS_ID = "mli-ch-june2026-bulletin"
GEOGRAPHY_ID = "mli-instat-localities-2023"
CENSUS_ID = "mli-instat-rgph5-global-2022"


def write(source):
    (CANON / (source["id"] + ".json")).write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def release_record(records, dataset_id):
    return next(record for record in records if record["dataset_id"] == dataset_id)


def source_metadata(record):
    return {
        "id": record["dataset_id"],
        "title": record["title"],
        "publisher": record["provider"],
        "release": record["version"],
        "release_id": record["release_id"],
        "url": record["source_url"],
        "review": "published",
    }


def import_food_security(legacy):
    with gzip.open(legacy / "source_wave3.json.gz", "rt", encoding="utf-8") as f:
        package = json.load(f)
    records = package["records"]
    first = release_record(records, CH_ID)
    limitations = package["registry"][0]["limitations"]
    columns = {
        "id": "TEXT", "source_region": "TEXT", "source_area": "TEXT", "source_code": "TEXT",
        "period_type": "TEXT", "period_start": "TEXT", "period_end": "TEXT",
        "analysed_population": "REAL", "area_phase": "INTEGER",
        "people_phase_3": "REAL", "people_phase_4": "REAL", "people_phase_5": "REAL",
        "people_phase_3_plus": "REAL", "area_mapping_status": "TEXT", "locator": "TEXT",
    }
    rows = []
    for record in records:
        if record["dataset_id"] != CH_ID:
            continue
        values = record["payload"]
        geo = values["geography"]
        area_match = values["geo_resolution"]["matches"].get("cercle")
        rows.append({
            "id": record["id"], "source_region": geo.get("region"),
            "source_area": geo.get("cercle"), "source_code": geo.get("cercle_pcode"),
            "period_type": values["period_type"], "period_start": record["reference_start"],
            "period_end": record["reference_end"], "analysed_population": values["population"],
            "area_phase": values["phase_class"], "people_phase_3": values["phase_populations"]["3"],
            "people_phase_4": values["phase_populations"]["4"],
            "people_phase_5": values["phase_populations"]["5"], "people_phase_3_plus": values["phase35"],
            "area_mapping_status": area_match["method"] if area_match else "unresolved",
            "locator": record["locator"],
        })
    write({
        **source_metadata(first), "type": "dataset", "license": package["registry"][0]["licence"],
        "topics": ["food security", "sécurité alimentaire", "faim", "hunger", "CH", "Cadre Harmonisé",
                   "crisis", "population phase", "projection", "Mopti", "cercle", "Mali"],
        "geography": "Mali analysis areas and parent labels in the workbooks' historical geography",
        "period": "September–December 2025 (current to the exercise), June–August 2026 (projection)",
        "description": "Area phases and estimated people by phase from the published CH exercise.",
        "limitations": [
            *limitations,
            "Treat June–August 2026 as a projection from the late-2025 exercise.",
            "For percentages use people_phase_3_plus and analysed_population from the same row or "
            "compatible, non-overlapping rows. Retain the historical source-area labels.",
        ],
        "table": "ch_mali",
        "columns": columns,
        "records": rows,
    })
    bulletin = release_record(records, CILSS_ID)
    values = bulletin["payload"]
    write({
        **source_metadata(bulletin), "type": "document", "license": package["registry"][1]["licence"],
        "topics": ["Cadre Harmonisé", "food security", "sécurité alimentaire", "projection", "Mali",
                   "chronologie", "methodology", "méthodologie", "juin août 2026"],
        "geography": "Mali, national only", "period": bulletin["reference_start"] + " to " + bulletin["reference_end"],
        "description": "National Cadre Harmonisé communication and timing of the Mali projection.",
        "limitations": package["registry"][1]["limitations"],
        "passages": [
            {"page": 3, "locator": "PDF page 3 · Table 2, Mali", "kind": "factual_extract",
             "text": f"The national June–August 2026 projection lists {values['population']:,} people "
                     f"analysed and {values['phase35']:,} estimated in phases 3–5. The phase 5 entry is a dash.",
             "topics": ["population analysée", "phase 3 et plus", "national figures"]},
            {"page": 4, "locator": "PDF page 4 · Mali methodology note", "kind": "factual_extract",
             "text": values["limitations"],
             "topics": ["projection carried forward", "reprise de la projection", "limites", "reference period"]},
        ],
    })


def import_reference(db):
    def metadata(dataset_id):
        row = db.execute("""
            select r.id as release_id, r.upstream_version as release, r.source_url as url, r.license,
                   s.title, s.provider as publisher
            from mkh_source_releases r join mkh_datasets d on r.dataset_id = d.id
            join mkh_sources s on d.source_id = s.id where r.dataset_id = ?
        """, (dataset_id,)).fetchone()
        return {"id": dataset_id, "review": "published", **dict(row)}

    directory = metadata(GEOGRAPHY_ID)
    rows = [dict(row) for row in db.execute("""
        select g.id, g.name as place, g.level, g.parent_id, parent.name as parent_place,
               p.value as projected_population, e.locator,
               p.reference_start as period_start, p.reference_end as period_end
        from mkh_geo_units g
        left join mkh_geo_units parent on g.parent_id = parent.id
        join mkh_population_observations p on p.unit_id = g.id and p.sex = 'total'
        join mkh_evidence_spans e on e.id = p.span_id
        where g.release_id = ? and g.level != 'locality'
        order by g.level, parent.name, g.name, g.id
    """, (directory["release_id"],))]
    write({
        **directory, "title": "INSTAT/BCR locality directory · 2023 projections",
        "type": "reference", "geography": "Mali, 2023 administrative framework, through commune/arrondissement",
        "period": "2023 projection, edition published January 2026",
        "topics": ["administrative geography", "géographie", "population", "Mopti", "ambiguïté",
                   "région", "cercle", "commune", "district", "arrondissement"],
        "description": "Official administrative hierarchy and 2023 population projections. Includes published totals.",
        "limitations": ["Projection based on RGPH5 and DNP, distinct from the census and CH denominators.",
                        "Cross-source boundary mappings require review. Homonymous levels stay distinct."],
        "table": "instat_geography",
        "columns": {
            "id": "TEXT", "place": "TEXT", "level": "TEXT", "parent_id": "TEXT", "parent_place": "TEXT",
            "projected_population": "INTEGER", "locator": "TEXT", "period_start": "TEXT", "period_end": "TEXT",
        },
        "records": rows,
    })
    census = metadata(CENSUS_ID)
    topics = {
        11: ["methodology", "méthodologie", "enumeration", "dénombrement", "fieldwork"],
        12: ["population", "résultats globaux", "indicateurs", "population totale"],
        17: ["estimation", "insécurité", "coverage", "zones non couvertes"],
        21: ["methodology", "méthodologie", "collection", "collecte"],
    }
    passages = [
        {"page": page, "locator": f"PDF page {page}", "kind": "original_passage",
         "text": " ".join(content.split()), "topics": topics[page]}
        for page, content in db.execute("""
            select page, content from mkh_document_pages
            where release_id = ? and page in (11, 12, 17, 21) order by page
        """, (census["release_id"],))
    ]
    write({
        **census, "title": "INSTAT/BCR RGPH5 · preliminary census report",
        "type": "document", "period": "2022 census; preliminary publication November 2023",
        "geography": "Mali, national methodology and census results",
        "topics": ["population", "census", "recensement", "méthodologie", "estimation", "couverture", "RGPH5"],
        "description": "Official passages from the 2022 census preliminary report, including enumeration methodology.",
        "limitations": ["Preliminary census figures use census definitions, distinct from projection series."],
        "passages": passages,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("legacy_dir", type=Path, help="v3 directory of the pinned V2.1 checkout")
    legacy = parser.parse_args().legacy_dir
    import_food_security(legacy)
    with tempfile.TemporaryDirectory() as scratch:
        database = Path(scratch) / "reference.sqlite"
        with gzip.open(legacy / "source_wave1.sqlite.gz") as source, database.open("wb") as dest:
            shutil.copyfileobj(source, dest)
        with sqlite3.connect(database) as db:
            db.row_factory = sqlite3.Row
            import_reference(db)


if __name__ == "__main__":
    main()
