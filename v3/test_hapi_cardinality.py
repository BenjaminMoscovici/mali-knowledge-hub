"""An enumerated HAPI set gets a checked count without summing needs."""

import unittest

from hapi_cardinality import intersectoral_locality_note, sector_citation_index


class HapiCardinalityRegression(unittest.TestCase):
    def test_eight_localities_with_other_sector_rows(self):
        rows = [{"source_family": "OCHA humanitarian data", "admin_level": 2,
                 "sector_name": "Intersectoral", "population_category": "total",
                 "admin1_name": "Mopti", "admin2_name": f"Place {n}",
                 "evidence_id": f"E{n:02d}"} for n in range(1, 9)]
        rows.append({**rows[0], "sector_name": "Health", "evidence_id": "E09"})
        note = intersectoral_locality_note(rows)
        self.assertIn("8 distinct Admin2 locality", note)
        self.assertIn("Place 8 [E08]", note)
        self.assertIn("not people in need or a regional aggregate", note)

    def test_sector_navigation_keeps_each_original_id_and_source_locality(self):
        base = {"source_family": "OCHA humanitarian data", "admin_level": 2,
                "admin1_name": "Mopti", "admin2_name": "Konna"}
        rows = [{**base, "evidence_id": "E29", "sector_name": "Water Sanitation Hygiene"},
                {**base, "evidence_id": "E31", "sector_name": "Nutrition"},
                {**base, "evidence_id": "E18", "sector_name": "Intersectoral"},
                {**base, "evidence_id": "E99", "sector_name": "Health", "admin_level": 1},
                {**base, "evidence_id": "E98", "sector_name": "Protection",
                 "source_family": "EU / Team Europe — priorities"}]
        note = sector_citation_index(rows)
        self.assertIn('"id": "E29", "sector": "Water Sanitation Hygiene"', note)
        self.assertIn('"id": "E31", "sector": "Nutrition"', note)
        self.assertIn('"source_locality": "Konna"', note)
        for excluded in ('E18', 'E99', 'E98'):
            self.assertNotIn(excluded, note)
        self.assertIn("not regional sector totals", note)
        self.assertIn("original reference period", note)

    def test_missing_local_evidence_creates_no_sector_claim(self):
        self.assertEqual(sector_citation_index([]), "")
        self.assertEqual(sector_citation_index([{"source_family": "OCHA humanitarian data",
                         "admin_level": 2, "evidence_id": "E01", "sector_name": "Health"}]), "")


if __name__ == "__main__":
    unittest.main()
