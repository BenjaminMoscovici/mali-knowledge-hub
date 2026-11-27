"""Load complete documents strictly through immutable, active catalogue releases."""
import gzip
import hashlib
import json
import re

from document_vectors import MODEL


def load_document(directory, source):
    snapshot = source["document_snapshot"]
    digest = snapshot["sha256"]
    if source["type"] != "document" or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid document reference")
    rights = snapshot["rights"]
    if (rights["scope"] != "whole_work" or rights["source_id"] != source["id"] or
            rights["upstream_sha256"] != source["upstream_checksum"] or
            rights["reuse_sha256"] != source["reuse_evidence_sha256"]):
        raise ValueError("Document rights do not match the published edition")
    content = (directory / "documents" / (digest + ".json.gz")).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("Document package checksum mismatch")
    doc = json.loads(gzip.decompress(content))
    passages = doc["passages"]
    if (doc["schema"] != 1 or doc["model"] != MODEL or doc["upstream_sha256"] != source["upstream_checksum"]
            or not passages or len(passages) != snapshot["sections"]):
        raise ValueError("Document package does not match its release")
    for i, passage in enumerate(passages):
        if i: passage["previous_locator"] = passages[i-1]["locator"]
        if i+1 < len(passages): passage["next_locator"] = passages[i+1]["locator"]
    return passages
