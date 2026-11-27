"""Check a reviewed V3.1 research publication against the pinned catalogue and original assets."""

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knowledge import Evidence, Knowledge, https_url


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(wave, catalogue, packet, assets):
    """Asset filenames are SHA-256 digests. The wave fixes the approved component scope."""
    if file_sha256(catalogue) != wave["catalogue_sha256"]:
        raise ValueError("The research catalogue differs from the reviewed round.")
    knowledge = Knowledge(packet)
    selected = {item["native_id"]: item for item in wave["components"]}
    if len(selected) != len(wave["components"]) or selected.keys() != knowledge.sources.keys():
        raise ValueError("Published component IDs differ from the reviewed wave.")
    ledger = Evidence(knowledge, False)
    with closing(sqlite3.connect(catalogue.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        recommendations = {row[0] for row in db.execute("select id from r3_foundational union select id from r3_systems")}
        for native_id, receipt in selected.items():
            source = knowledge.source(native_id)
            research = source["research"]
            candidate = research["candidate_id"]
            if candidate != receipt["candidate_id"] or candidate not in recommendations:
                raise ValueError(f"Unreconciled candidate for {native_id}.")
            if knowledge.stamps[native_id] != receipt["manifest_sha256"]:
                raise ValueError(f"Reviewed component changed: {native_id}")
            owner = research["logical_source_id"]
            anchor = research["anchor_release_id"]
            if not db.execute(
                "select 1 from release r join location l on l.release=r.id where r.source=? and r.id=? and l.url=?",
                (owner, anchor, source["url"]),
            ).fetchone():
                raise ValueError(f"Unverified edition or original reference: {native_id}")
            if owner != candidate and not db.execute(
                "select 1 from source_relation where source=? and related=?", (owner, candidate)
            ).fetchone():
                raise ValueError(f"Missing source-system association: {native_id}")
            if not https_url(source["reuse_url"]) or not source["license"].strip():
                raise ValueError(f"Missing release-specific reuse basis: {native_id}")
            for field in ("upstream_checksum", "reuse_evidence_sha256"):
                digest = source[field]
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError(f"Invalid asset digest: {native_id}")
                if file_sha256(assets / digest) != digest:
                    raise ValueError(f"Changed original or reuse evidence: {native_id}")
            matches = knowledge.discover(source["title"], limit=len(knowledge.sources))
            if native_id not in {match["id"] for match in matches}:
                raise ValueError(f"Source cannot be discovered: {native_id}")
            operations = knowledge.operations(source)
            if "query_data" in operations:
                result = knowledge.query([native_id], "SELECT count(*) AS n FROM " + source["table"], ledger)
                if result["data"]["rows"] != [{"n": receipt["rows"]}] or not ledger.allowed(result):
                    raise ValueError(f"Native row or evidence check failed: {native_id}")
            for passage in source.get("passages", []):
                result = knowledge.read_passage(native_id, passage["locator"], 0, ledger)
                if not result["data"]["text"] or not ledger.allowed(result):
                    raise ValueError(f"Passage cannot be reopened: {native_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wave", "catalogue", "packet", "assets"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    check(json.loads(args.wave.read_text()), args.catalogue, args.packet, args.assets)
    print("Checked the selected research components, original bytes, reuse evidence and native operations.")
