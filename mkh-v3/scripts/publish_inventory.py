"""Build immutable V3 releases from Work records and independent, byte-pinned reuse receipts.

Offline release tool. The Work ZIP is data. The separate qualified receipts describe
the specific material cleared by publisher terms and the verified extraction.
"""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge import CANON, SOURCE_ID, Evidence, Knowledge, https_url


def verified_asset(directory, name, digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest or "") or Path(name).name != name:
        raise ValueError("Invalid pinned asset reference")
    path = directory / name
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError(f"Changed upstream or extraction bytes: {name}")
    return path


def pdf_passages(original, pages):
    passages = []
    for page in pages:
        if type(page) is not int or page < 1:
            raise ValueError("Invalid PDF page")
        raw = subprocess.check_output(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(original), "-"],
            timeout=45, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        if len(raw) < 50:
            raise ValueError(f"PDF page {page} lacks usable text")
        passages.append({"kind": "source_passage", "page": page, "locator": f"PDF p. {page}", "text": raw})
    return passages


def verify_operations(source, directory=CANON):
    required = ("title", "publisher", "period", "geography", "release", "description", "license",
                "limitations", "topics", "url", "upstream_checksum", "edition_family", "reuse_url")
    if not all(source.get(key) for key in required) or not all(https_url(source[k]) for k in ("url", "reuse_url")):
        raise ValueError("Missing identity, provenance, coverage or reuse evidence")
    if not SOURCE_ID.fullmatch(source["id"]):
        raise ValueError("Invalid V3 ID")
    k = Knowledge(directory, releases=[source])
    key = source["id"]
    ledger = Evidence(k, False)
    if not k.discover(source["title"]):
        raise ValueError("Release could not be discovered")
    if source.get("passages"):
        for p in source["passages"]:
            if not p.get("kind") or not p.get("locator") or not p.get("text", "").strip():
                raise ValueError("Missing passage or original locator")
            if not ledger.allowed(k.read_passage(key, p["locator"], 0, ledger)):
                raise ValueError("Unresolved passage")
    if source["type"] in {"dataset", "reference"}:
        packed = source.get("table_snapshot")
        rows = packed["samples"] if packed else source["records"]
        count = packed["row_count"] if packed else len(rows)
        if packed:
            table = source["table"]
            with sqlite3.connect(k.table_files[key], uri=True) as db:
                cols = {r[1]: r[2] for r in db.execute(f'PRAGMA table_info("{table}")')}
                if cols != source["columns"] or db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("Packaged table definition or integrity check failed")
                bounds = db.execute(f'SELECT count(DISTINCT id), count(*) FROM "{table}" WHERE length(id)>0 AND length(locator)>0').fetchone()
                if bounds != (count, count):
                    raise ValueError("Packaged rows lack unique identity or location")
        if not rows or any(not r.get("locator") or set(r) != set(source["columns"]) for r in rows):
            raise ValueError("Missing cells or original row locator")
        for row in rows:
            for col, dtype in source["columns"].items():
                value = row[col]
                if value is None:
                    continue
                types = {"TEXT": (str,), "INTEGER": (int,), "REAL": (int, float)}
                if type(value) not in types[dtype]:
                    raise ValueError(f"Unexpected value type in {col}")
        result = k.query([key], f'SELECT count(*) AS n FROM "{source["table"]}"', ledger)
        if result["data"]["rows"] != [{"n": count}] or not ledger.allowed(result):
            raise ValueError("Native count failed")
    elif not source.get("passages"):
        raise ValueError("Missing usable components")


def integrate(record, receipt, assets, directory, catalogue):
    work_id = record["work_id"]
    if not receipt:
        return {"status": "flagged", "reason": "No independently established release and reuse scope"}
    if "reason" in receipt:
        return {"status": "flagged", "reason": receipt["reason"]}
    work = record["work"]
    digest = receipt["sha256"]
    if work.get("sha256", digest) != digest or work["content_url"] != receipt["original_url"]:
        raise ValueError("Identity conflicts with the Work record")
    original = verified_asset(assets, receipt["asset"], digest)
    twins = [s for s in catalogue.values() if s.get("upstream_checksum") == digest]
    component = receipt.get("archive_component")
    if twins:
        if any(s.get("review") != "published" for s in twins):
            raise ValueError("Original is associated with a non-published release")
        intended = receipt.get("match_id", receipt["metadata"]["id"])
        same_component = [s for s in twins if s["id"] == intended]
        if same_component:
            return {"status": "matched", "v3_ids": [intended], "sha256": digest}
        if not component or set(component["siblings"]) != {s["id"] for s in twins}:
            raise ValueError("Same original bytes under another identity; component equivalence is unresolved")
    src = dict(receipt["metadata"])
    key = src["id"]
    if key in catalogue or any(s.get("edition_family", s["id"]) == src["edition_family"]
                               and s["release"] == src["release"] for s in catalogue.values()):
        raise ValueError("Existing identity or edition has different bytes")
    verified_asset(assets, receipt["rights_asset"], receipt["rights_sha256"])
    for evidence in receipt.get("supporting_evidence", []):
        if not https_url(evidence["url"]):
            raise ValueError("Invalid supporting evidence URL")
        verified_asset(assets, evidence["asset"], evidence["sha256"])
    if "component_asset" in receipt:
        extracted = verified_asset(assets, receipt["component_asset"], receipt["component_sha256"])
        components = json.loads(extracted.read_text())
        allowed = {"table", "columns", "records", "passages", "geometries", "dimensions", "definitions",
                   "search_fields", "place_fields", "map_key", "table_snapshot"}
        if set(components) - allowed:
            raise ValueError("Unexpected extraction fields")
        src.update(components)
    if component:
        with ZipFile(original) as archive, archive.open(component["member"]) as member:
            if hashlib.file_digest(member, "sha256").hexdigest() != component["sha256"]:
                raise ValueError("Archive member checksum mismatch")
        column = component["identity_column"]
        identities = {row[column] for row in src["records"]}
        if not identities or len(identities) != len(src["records"]):
            raise ValueError("Archive component requires distinct record identities")
        for sibling in twins:
            previous = {row[column] for row in sibling["records"]}
            if not previous or identities & previous:
                raise ValueError("Archive component overlaps existing record identities")
        src["archive_component"] = component
    if receipt.get("pages"):
        src.setdefault("passages", []).extend(pdf_passages(original, receipt["pages"]))
    src.update(review="published", work_id=work_id, upstream_checksum=digest,
               url=receipt["original_url"], reuse_evidence_sha256=receipt["rights_sha256"])
    if "table_snapshot" in src:
        if not SOURCE_ID.fullmatch(key):
            raise ValueError("Invalid packaged release identity")
        archive = verified_asset(assets, receipt["table_asset"], src["table_snapshot"]["sha256"])
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            stage = Path(temporary)
            (stage / "tables").mkdir()
            package = stage / "tables" / (key + ".sqlite.gz")
            shutil.copyfile(archive, package)
            verify_operations(src, stage)
            target = directory / "tables" / package.name
            target.parent.mkdir(exist_ok=True)
            try:
                os.link(package, target)
            except FileExistsError:
                verified_asset(target.parent, target.name, src["table_snapshot"]["sha256"])
    else:
        verify_operations(src)
    data = (json.dumps(src, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    # Atomic create-only install. A concurrent writer may have installed the same release.
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp") as staged:
        staged.write(data)
        staged.flush()
        dest = directory / (key + ".json")
        try:
            os.link(staged.name, dest)
        except FileExistsError:
            if dest.read_bytes() != data:
                raise ValueError("Conflicting concurrent publication") from None
    catalogue[key] = src
    return {"status": "integrated", "v3_ids": [key], "sha256": digest,
            "passages": len(src.get("passages", [])), "rows": src.get("table_snapshot", {}).get("row_count", len(src.get("records", [])))}


def run(records, receipts, assets, directory=CANON):
    # Serialize concurrent imports across source IDs, including edition and duplicate checks.
    fd = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return process_records(records, receipts, assets, directory)
    finally:
        os.close(fd)


def process_records(records, receipts, assets, directory):
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[1] / "inventory/work.schema.json").read_text())
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    counts = Counter(row["work_id"] for row in records
                     if isinstance(row, dict) and isinstance(row.get("work_id"), str))
    catalogue = {s["id"]: s for s in Knowledge.read_releases(directory)}
    results = []
    for row in records:
        key = row.get("work_id") if isinstance(row, dict) else None
        try:
            problem = next(validator.iter_errors(row), None)
            if problem:
                raise ValueError(f"Invalid Work metadata at {problem.json_path}: {problem.validator}")
            if counts[key] > 1:
                raise ValueError("Duplicate Work ID within batch")
            outcome = integrate(row, receipts.get(key), assets, directory, catalogue)
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
            outcome = {"status": "flagged", "reason": str(exc)}
        results.append({"work_id": key, **outcome})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path, help="Work ZIP or array of Work records")
    parser.add_argument("receipts", type=Path, help="Independent eligibility receipts keyed by Work ID")
    parser.add_argument("assets", type=Path, help="Originals, rights evidence and verified extracts")
    parser.add_argument("--canon", type=Path, default=CANON)
    args = parser.parse_args()
    if args.batch.suffix.lower() == ".zip":
        with ZipFile(args.batch) as archive:
            rows = [json.loads(archive.read(f)) for f in sorted(archive.namelist())
                    if re.fullmatch(r"work/MKH-SRC-\d+\.json", f)]
    else:
        rows = json.loads(args.batch.read_text())
    if not rows:
        parser.error("No Work records in batch")
    print(json.dumps(run(rows, json.loads(args.receipts.read_text()), args.assets, args.canon), indent=2))
