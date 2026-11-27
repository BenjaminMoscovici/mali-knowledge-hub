import base64
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from knowledge import Evidence, Knowledge
from document_vectors import MODEL, encode


class VersionedDocuments(unittest.TestCase):
    def test_search_context_and_withdrawal(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory/"documents").mkdir()
            pages = []
            for i,text in enumerate(["Introduction", "Groundwater observation protocol", "Final methodological caveat."],1):
                pages.append(dict(page=i,locator=f"PDF p. {i} · §{i}",path=["Methods", f"Section {i}"],
                                  method="embedded text",kind="original_passage",topics=[],text=text,
                                  embedding=base64.b64encode(encode(text).astype("<f2").tobytes()).decode()))
            raw = gzip.compress(json.dumps(dict(schema=1,model=MODEL,upstream_sha256="a"*64,passages=pages)).encode())
            digest = hashlib.sha256(raw).hexdigest()
            (directory/"documents"/(digest+".json.gz")).write_bytes(raw)
            rights=dict(scope="whole_work",source_id="study",upstream_sha256="a"*64,reuse_sha256="b"*64)
            manifest=dict(id="study",title="Technical study",type="document",review="published",url="https://example.org/study.pdf",
                          description="Survey",geography="National",topics=[],publisher="Institute",release="2020",period="2020",
                          upstream_checksum="a"*64,reuse_evidence_sha256="b"*64,document_snapshot=dict(sha256=digest,rights=rights,sections=3))
            k=Knowledge(directory,releases=[manifest]);ledger=Evidence(k,False)
            hit=k.search_documents("groundwater observation","study",ledger,limit=1)[0]
            self.assertEqual(hit["url"], manifest["url"]+"#page=2")
            next_page=k.read_passage("study",hit["data"]["next_locator"],0,ledger)
            self.assertEqual(next_page["data"]["path"],["Methods","Section 3"])
            self.assertFalse(Evidence(Knowledge(directory,releases=[]),False).allowed(hit))
            with self.assertRaises(ValueError):
                Knowledge(directory,releases=[{**manifest,"upstream_checksum":"c"*64}])
            (directory/"documents"/(digest+".json.gz")).write_bytes(b"changed")
            with self.assertRaises(ValueError):
                Knowledge(directory,releases=[manifest])
