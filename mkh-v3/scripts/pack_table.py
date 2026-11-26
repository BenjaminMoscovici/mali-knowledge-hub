"""Build a published table from a pinned upstream CSV and its reviewed JSON manifest."""

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile


def convert(raw, kind):
    if raw == "":
        return None
    if kind == "TEXT":
        return raw
    if kind == "INTEGER":
        return int(raw)
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("Non-finite source observation")
    return value


def build_snapshot(source, rows, out):
    """Package typed rows, retaining their original record identifiers and locators."""
    cols = source["columns"]
    table = source["table"]
    if (not all(re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in [table, *cols])
            or not set(cols.values()) <= {"REAL", "TEXT", "INTEGER"}):
        raise ValueError("Invalid schema")
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "release.sqlite"
        with sqlite3.connect(database) as db:
            fields = ", ".join(f'"{name}" {kind}' for name, kind in cols.items())
            db.execute(f'CREATE TABLE "{table}" ({fields}, PRIMARY KEY (id))')
            slots = ",".join("?" for _ in cols)
            def checked_rows():
                allowed = {"TEXT": (str,), "INTEGER": (int,), "REAL": (int, float)}
                for row in rows:
                    row = tuple(row)
                    for (name, kind), value in zip(cols.items(), row, strict=True):
                        if name in {"id", "locator"} and not value:
                            raise ValueError(f"Missing {name} in analytical table")
                        if value is not None and type(value) not in allowed[kind]:
                            raise ValueError(f"Invalid {kind} value for {name}")
                        if isinstance(value, float) and not math.isfinite(value):
                            raise ValueError(f"Non-finite value for {name}")
                    yield row

            db.executemany(f'INSERT INTO "{table}" VALUES ({slots})', checked_rows())
            db.row_factory = sqlite3.Row
            count = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            samples = [dict(row) for row in db.execute(f'SELECT * FROM "{table}" LIMIT 3')]
            profiles = {}
            for field in source["dimensions"]:
                if field not in cols:
                    raise ValueError("Unknown dimension")
                values = db.execute(f'SELECT "{field}", COUNT(*) AS n FROM "{table}" WHERE "{field}" IS NOT NULL '
                                    f'GROUP BY "{field}" ORDER BY n DESC, "{field}"').fetchall()
                profiles[field] = {"distinct_count": len(values), "examples": [v[0] for v in values[:20]]}
        db.close()
        out.parent.mkdir(exist_ok=True)
        with out.open("wb") as target, gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as gz, database.open("rb") as raw:
            shutil.copyfileobj(raw, gz)
        return {"sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                "row_count": count, "samples": samples, "dimension_values": profiles}


def pack(manifest, csv_path):
    source = json.loads(manifest.read_text())
    with csv_path.open("rb") as raw:
        if hashlib.file_digest(raw, "sha256").hexdigest() != source["upstream_checksum"]:
            raise ValueError("CSV differs from the reviewed upstream release")
    cols = source["columns"]
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        headers = [name.lower() for name in next(reader)]
        if headers != list(cols)[2:]:
            raise ValueError("Upstream columns changed")
        rows = ((f"r{number}", f"CSV row {number}",
                 *(convert(value, cols[key]) for key, value in zip(headers, values, strict=True)))
                for number, values in enumerate(reader, start=2))
        out = manifest.parent / "tables" / (source["id"] + ".sqlite.gz")
        source["table_snapshot"] = build_snapshot(source, rows, out)
    manifest.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    pack(args.manifest, args.csv)
