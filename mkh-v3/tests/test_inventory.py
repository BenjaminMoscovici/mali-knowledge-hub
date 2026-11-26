import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from companion import unverified_numeric_quotes
from knowledge import Evidence, Knowledge
from scripts.publish_inventory import run


class InventoryTest(unittest.TestCase):
    def test_scoped_edition_replay_and_failed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canon = root / "canon"
            canon.mkdir()
            original = b"public source"
            urls = {"url": "https://example.org/report", "reuse_url": "https://example.org/terms"}
            record = {"work_id": "item-a", "v3_metadata": {"title": "Survey", "publisher": "Agency", "url": urls["url"]},
                      "work": {"content_url": urls["url"]}}
            byte_hash = lambda b: hashlib.sha256(b).hexdigest()
            (root / "original").write_bytes(original)
            (root / "terms").write_bytes(b"permission")
            component = json.dumps({"passages": [{"kind": "source_passage", "locator": "p. 3", "text": "Demand rose by 15.20 units in 2019."}]}).encode()
            (root / "component").write_bytes(component)
            receipt = {"asset": "original", "sha256": byte_hash(original), "original_url": urls["url"],
                       "rights_asset": "terms", "rights_sha256": byte_hash(b"permission"),
                       "component_asset": "component", "component_sha256": byte_hash(component),
                       "metadata": {"id": "example-a", "edition_family": "example", "release": "2021",
                                    "type": "document", "topics": ["industry"], "license": "Open",
                                    "title": "Survey", "description": "Industrial survey", "publisher": "Agency",
                                    "period": "2019", "geography": "National", "limitations": ["Demand only"], **urls}}
            def attempt(rows, receipts):
                return [i["status"] for i in run(rows, receipts, root, canon)]
            self.assertEqual(attempt([record, record], {"item-a": receipt}), ["flagged", "flagged"])
            self.assertEqual(attempt([record, {}], {}), ["flagged", "flagged"])
            self.assertEqual(list(canon.iterdir()), [])
            self.assertEqual(attempt([record], {"item-a": receipt}), ["integrated"])
            self.assertEqual(attempt([record], {"item-a": receipt}), ["matched"])
            self.assertEqual(attempt([record], {"item-a": {**receipt, "sha256": "f" * 64}}), ["flagged"])
            different = {**receipt, "metadata": {**receipt["metadata"], "id": "other-component"}}
            self.assertEqual(attempt([record], {"item-a": different}), ["flagged"])
            k = Knowledge(releases=list(Knowledge.read_releases(canon)))
            ledger = Evidence(k, False)
            ev = k.read_passage("example-a", "p. 3", 0, ledger)
            cite = "[[" + ev["id"] + "]]"
            for text in ("«15.20 units»", "«2019»"):
                self.assertEqual(unverified_numeric_quotes(text + cite, ledger), [])
            for text in ("«15.2 units»", "«15»", "«2021»"):
                self.assertTrue(unverified_numeric_quotes(text + cite, ledger))
