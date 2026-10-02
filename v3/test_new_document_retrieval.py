"""New humanitarian documents must enter the humanitarian retrieval route."""

import unittest

from document_families import document_family
from document_targets import explicit_title_targets
from routing import explicit_source_plan


class NewDocumentRetrieval(unittest.TestCase):
    def test_unicef_appeal_is_named_and_routed(self):
        document = {"id": "appeal-1", "title": "UNICEF Humanitarian Action for Children 2026: Mali",
                    "organization": "UNICEF", "document_type": "humanitarian appeal"}
        question = ("According to UNICEF Humanitarian Action for Children 2026 for Mali, "
                    "how many children with severe wasting are planned for treatment?")
        self.assertEqual(document_family(document), "Humanitarian reports and appeals")
        self.assertEqual(explicit_title_targets(question, [document]),
                         [("appeal-1", document["title"])])
        self.assertEqual(explicit_source_plan(question),
                         {"government_docs": False, "hnrp_docs": True,
                          "hapi": False, "fongim": False})

    def test_scanned_report_and_existing_hnrp(self):
        report = {"id": "report-1", "title": "UNICEF Mali Humanitarian Situation Report No. 2, January–June 2026",
                  "organization": "UNICEF", "document_type": "report"}
        self.assertEqual(document_family(report), "Humanitarian reports and appeals")
        self.assertEqual(explicit_title_targets("UNICEF Mali Humanitarian Situation Report No. 2", [report]),
                         [("report-1", report["title"])])
        self.assertEqual(document_family({"title": "Plan des besoins humanitaires et de réponse 2026",
                                          "organization": "OCHA",
                                          "document_type": "Humanitarian Needs and Response Plan"}),
                         "Humanitarian Response Plan / HNRP")


if __name__ == "__main__":
    unittest.main()
