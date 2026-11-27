"""Qualify all document manifests in a Canon wave against whole-work receipts and pinned assets."""
import argparse
import csv
import json
import re
from pathlib import Path
import subprocess

from build_document import build, publishable


def run(manifests, assets, receipts, canon, output):
    permissions = json.loads(receipts.read_text())
    if not isinstance(permissions, list):
        raise ValueError("Supply an array of whole-work receipts")
    grants = {(p["source_id"],p["upstream_sha256"]):p for p in permissions}
    if len(grants) != len(permissions):
        raise ValueError("Duplicate permission for the same source and original")
    # A separate output directory keeps prior runs intact and excludes stale manifests.
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Choose an empty output directory for this wave")
    with (output/"dispositions.csv").open("w",newline="") as report:
        log=csv.writer(report,lineterminator="\n")
        log.writerow(["source_id","edition","outcome","package_or_reason"])
        for path in sorted(manifests.glob("*.json")):
            doc=json.loads(path.read_text())
            if doc.get("type")!="document" or doc.get("review")!="published":
                continue
            key,edition=doc["id"],doc["release"]
            grant=grants.get((key,doc.get("upstream_checksum")))
            if not grant:
                log.writerow([key,edition,"retained","No whole-work receipt for this edition"])
                continue
            try:
                digests=[grant["upstream_sha256"],grant["reuse_sha256"]]
                if not all(re.fullmatch("[0-9a-f]{64}",h) for h in digests):
                    raise ValueError("Invalid asset digest")
                raw,terms=[(assets/h).read_bytes() for h in digests]
                package=build(doc,raw,grant,terms)
                manifest=publishable(doc,package,grant,canon)
            except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError) as exc:
                log.writerow([key,edition,"retained",str(exc)])
                continue
            (output/path.name).write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
            log.writerow([key,edition,"qualified",manifest["document_snapshot"]["sha256"]])


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("manifests","assets","receipts","canon","output"):
        parser.add_argument(name,type=Path)
    run(**vars(parser.parse_args()))
