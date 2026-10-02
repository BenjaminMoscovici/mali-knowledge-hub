"""An enumerated HAPI set gets a checked count without summing needs."""

import unittest

from hapi_cardinality import intersectoral_locality_note


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


if __name__ == "__main__":
    unittest.main()
