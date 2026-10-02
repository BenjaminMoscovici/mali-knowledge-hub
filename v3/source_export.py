"""Export an inspected staging snapshot as a transactional PostgreSQL load.

Generating a load does not apply it. Run only against the audited GIZ MKH
project after the draft schema passes PostgreSQL and permission checks.
"""
import argparse
from pathlib import Path
import sqlite3

TABLES = ("mkh_sources", "mkh_datasets", "mkh_ingestion_runs", "mkh_source_releases",
          "mkh_geo_units", "mkh_geo_names", "mkh_geo_identifiers", "mkh_evidence_spans",
          "mkh_population_observations", "mkh_humanitarian_observations", "mkh_document_pages",
          "mkh_geo_crosswalks", "mkh_geo_unresolved")


def literal(value):
    if value is None: return "NULL"
    if isinstance(value, (int, float)): return str(value)
    if "\x00" in value: raise ValueError("NUL byte cannot be exported to PostgreSQL")
    return "'" + value.replace("'", "''") + "'"


def export(database, output):
    db = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True)
    # A pending or failed run is audit history, never a publishable release.
    active = dict(db.execute("select id,current_release_id from mkh_datasets"))
    if not active or any(not rid for rid in active.values()): raise ValueError("No complete active snapshot")
    if db.execute("pragma foreign_key_check").fetchall(): raise ValueError("Broken staging foreign key")
    with Path(output).open("w", encoding="utf-8") as f:
        f.write("-- NOT APPLIED. Target only GIZ MKH hofoubbmepacdljeablj after live schema review.\n")
        f.write("-- Transactional insert; old immutable releases survive. No production deletes.\n")
        f.write("begin;\nset local standard_conforming_strings=on;\nset local search_path=public,pg_catalog;\n")
        f.write("lock table public.mkh_datasets in share row exclusive mode;\n")
        for dataset, rid in active.items():
            # A replay may preserve the identical active release. Updating an
            # already populated dataset needs a separately reviewed predecessor.
            f.write("select 1 / case when exists (select 1 from public.mkh_datasets where id="
                + literal(dataset) + " and current_release_id is not null and current_release_id<>"
                + literal(rid) + ") then 0 else 1 end as publication_precondition;\n")
        counts = {}
        for table in TABLES:
            columns = [r[1] for r in db.execute(f"pragma table_info({table})")]
            counts[table] = 0
            for row in db.execute(f"select * from {table} order by rowid"):
                f.write(f"insert into public.{table} ({','.join(columns)}) values ({','.join(literal(v) for v in row)}) on conflict ("
                    + ("release_id,page" if table == "mkh_document_pages" else "id") + ") do nothing;\n")
                counts[table] += 1
        # Publication pointers move only after every row is inserted and checked.
        for dataset, rid in active.items():
            f.write(f"update public.mkh_datasets set current_release_id={literal(rid)} where id={literal(dataset)};\n")
        f.write("set constraints all immediate;\ncommit;\n")
    db.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(export(args.database, args.output))
