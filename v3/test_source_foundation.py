"""Safety and analytical acceptance checks for the new isolated source stage."""
import unittest
from source_foundation import SourceStore, stable_id


def fixture(version="v1", names=("Same",)):
    rid = stable_id("fixture-release", version)
    country = stable_id(rid, "country")
    units = [{"id": country, "parent_id": None, "level": "country", "name": "Fixture Mali",
              "boundary_version": version, "original_record_id": "fixture:country"}]
    spans, population = [], []
    for i, name in enumerate(names):
        uid = stable_id(rid, i)
        sid = stable_id(uid, "span")
        units.append({"id": uid, "parent_id": country, "level": "region", "name": name,
                      "boundary_version": version, "original_record_id": f"fixture:{i}"})
        spans.append({"id": sid, "original_record_id": f"fixture:{i}", "page": 1,
                      "passage": f"Synthetic test only: {name} population 100", "locator": "fixture"})
        population.append({"id": stable_id(uid, "total"), "unit_id": uid, "span_id": sid,
            "sex": "total", "value": 100, "unit": "people", "reference_start": "2023-01-01",
            "reference_end": "2023-12-31", "methodology": "Synthetic test fixture, never source data",
            "geographic_precision": "region"})
    return {"source": {"id": "fixture", "provider": "TEST ONLY", "title": "Synthetic fixture", "url": "https://example.org"},
        "dataset": {"id": "fixture", "title": "Synthetic test only", "refresh_policy": "Never"},
        "release": {"id": rid, "checksum": "a" * 64, "upstream_version": version,
            "retrieved_at": "2026-10-02T00:00:00+00:00", "source_url": "https://example.org",
            "original_file": "fixture.json", "license": "test fixture", "license_url": "https://example.org",
            "attribution": "TEST ONLY", "access": "public_aggregate"},
        "units": units, "spans": spans, "population": population,
        "pages": [{"page": 1, "content": "Synthetic test only"}]}


class FoundationTests(unittest.TestCase):
    def setUp(self): self.store = SourceStore(":memory:")
    def tearDown(self): self.store.close()

    def test_idempotent_rerun_and_retained_history(self):
        first, second = fixture(), fixture("v2")
        self.store.publish(first); self.store.publish(second)
        self.assertEqual("no_op", self.store.publish(first)["status"])
        self.assertEqual(second["release"]["id"], self.store.db.execute("select current_release_id from mkh_datasets").fetchone()[0])
        self.assertEqual(2, self.store.db.execute("select count(*) from mkh_source_releases").fetchone()[0])

    def test_failure_retains_last_good_release(self):
        self.store.publish(fixture())
        bad = fixture("v2"); bad["population"][0]["value"] = -1
        with self.assertRaises(ValueError): self.store.publish(bad)
        self.assertEqual("v1", self.store.freshness()[0]["upstream_version"])
        self.assertEqual("failed", self.store.db.execute("select status from mkh_ingestion_runs order by rowid desc").fetchone()[0])
        self.assertEqual(1, self.store.db.execute("select count(*) from mkh_source_releases").fetchone()[0])

    def test_empty_release_cannot_erase_data(self):
        self.store.publish(fixture())
        bad = fixture("v2"); bad.update(units=[], pages=[], population=[], spans=[])
        with self.assertRaises(ValueError): self.store.publish(bad)
        self.assertEqual("v1", self.store.freshness()[0]["upstream_version"])

    def test_shrink_requires_recorded_review(self):
        self.store.publish(fixture(names=tuple(str(i) for i in range(10))))
        with self.assertRaises(ValueError): self.store.publish(fixture("v2"))
        self.store.publish(fixture("v2"), reviewed_shrink_reason="Synthetic edition changed scope; reviewed test")
        self.assertEqual("v2", self.store.freshness()[0]["upstream_version"])

    def test_wrong_parent_level_is_rejected(self):
        bad = fixture(); bad["units"][1]["level"] = "commune"
        with self.assertRaises(ValueError): self.store.publish(bad)

    def test_no_citation_no_observation(self):
        bad = fixture(); bad["spans"] = []
        with self.assertRaises(ValueError): self.store.publish(bad)

    def test_restricted_data_is_not_accepted(self):
        bad = fixture(); bad["release"]["access"] = "restricted_microdata"
        with self.assertRaises(ValueError): self.store.publish(bad)

    def test_homonyms_require_resolution(self):
        self.store.publish(fixture(names=("Same", "Same")))
        result = self.store.population("Same", dataset_id="fixture", level="region")
        self.assertEqual("ambiguous", result["status"])
        self.assertNotIn("evidence", result)

    def test_wrong_level_does_not_downscale(self):
        self.store.publish(fixture())
        self.assertEqual("unresolved", self.store.population("Same", dataset_id="fixture", level="commune")["status"])

    def test_district_type_survives_admin1_hierarchy(self):
        p = fixture(); p["units"][1]["unit_type"] = "district"
        self.store.publish(p)
        r = self.store.resolve("Same", dataset_id="fixture", level="region")
        self.assertEqual("district", r["candidates"][0]["unit_type"])

    def test_population_retains_period_page_and_limitations(self):
        self.store.publish(fixture())
        result = self.store.population("Same", dataset_id="fixture", level="region")
        self.assertEqual(1, result["evidence"][0]["page"])
        self.assertEqual("2023-01-01", result["evidence"][0]["reference_start"])
        self.assertIn("not current", " ".join(result["limitations"]))

    def test_proposal_cannot_be_used_as_approved_join(self):
        a, b = fixture(), fixture("v2")
        b["dataset"]["id"] = "fixture-other"
        self.store.publish(a); self.store.publish(b)
        self.assertEqual(2, self.store.crosswalk_proposals("fixture", "fixture-other"))
        self.assertEqual([], self.store.approved_targets(a["units"][1]["id"]))

    def test_transaction_rolls_back_after_database_error(self):
        bad = fixture()
        bad["pages"].append({"page": 0, "content": "test"})
        # Inject a real database constraint failure after geographic rows are inserted.
        self.store.db.executescript("create trigger reject_span before insert on mkh_evidence_spans begin select raise(abort,'test'); end;")
        with self.assertRaises(Exception): self.store.publish(bad)
        self.assertEqual(0, self.store.db.execute("select count(*) from mkh_geo_units").fetchone()[0])
        self.assertEqual(0, self.store.db.execute("select count(*) from mkh_source_releases").fetchone()[0])


if __name__ == "__main__": unittest.main()
