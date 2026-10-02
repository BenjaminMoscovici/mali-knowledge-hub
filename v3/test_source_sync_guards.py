import unittest
from source_sync_guards import paginated_hapi, validate_fongim_refresh


class SyncGuardTests(unittest.TestCase):
    def test_hapi_all_pages_are_retrieved(self):
        source = [{"location_code": "MLI", "id": i} for i in range(5)]
        offsets = []
        def get(*args, **kw):
            offsets.append(kw["offset"])
            return {"data": source[kw["offset"]:kw["offset"] + kw["limit"]]}
        self.assertEqual(source, paginated_hapi(get, "test", {}, page_size=2))
        self.assertEqual([0, 2, 4], offsets)

    def test_hapi_ignored_offset_is_rejected(self):
        def get(*args, **kw): return {"data": [{"location_code": "MLI"}]}
        with self.assertRaises(ValueError): paginated_hapi(get, "test", {}, page_size=1)

    def test_hapi_truncated_results_are_not_reported_complete(self):
        def get(*args, **kw): return {"data": [{"location_code": "MLI", "id": kw["offset"]}]}
        with self.assertRaises(ValueError): paginated_hapi(get, "test", {}, page_size=1, max_records=2)

    def test_hapi_malformed_or_other_country_is_rejected(self):
        for response in ({}, {"data": "bad"}, {"data": [{"location_code": "NER"}]}):
            with self.assertRaises(ValueError): paginated_hapi(lambda *a, **kw: response, "test", {})

    def test_empty_fongim_does_not_wipe_previous_mirror(self):
        with self.assertRaises(ValueError): validate_fongim_refresh(dict(project_count=0), {})

    def test_shrinking_fongim_is_quarantined(self):
        c = dict(project_count=100, organization_count=10, location_count=100, sector_count=100)
        with self.assertRaises(ValueError): validate_fongim_refresh(c, dict(project_count=200))
        validate_fongim_refresh(c, dict(project_count=200), reviewed_shrink_reason="Reviewed source scope change")


if __name__ == "__main__": unittest.main()
