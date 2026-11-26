import asyncio
import unittest

import httpx

from companion import Companion
from knowledge import Evidence, Knowledge, KnowledgeError
from scope_review import compare, validate_scope


class ScopeReviewTest(unittest.TestCase):
    def test_unknown_and_distinct_scopes_do_not_register_a_join(self):
        published = {"id": "survey-a", "title": "Survey A", "geography": "Central district",
                     "period": "May", "type": "document", "publisher": "Fixture", "topics": [],
                     "description": "test survey", "review": "published", "release": "1",
                     "limitations": [], "url": "https://example.org/survey"}
        profile = {"windows": [["2021-01-01", "2021-12-31"]], "measure": "Annual count"}
        first = {**published, "comparison_scope": profile}
        other = {**published, "id": "survey-b", "comparison_scope": {
            "windows": [["2023-01-01", "2023-12-31"]], "measure": "Planned target"}}
        k = Knowledge(releases=[first, other])
        async def run():
            async with httpx.AsyncClient() as client:
                c = Companion(k, client, "fixture")
                ledger = Evidence(k, False)
                result = await c.run_tool("compare_sources", {"source_ids":["survey-a", "survey-b"]}, ledger)
                self.assertEqual(set(ledger.consulted), {"survey-a", "survey-b"})
                with self.assertRaises(KnowledgeError):
                    await c.run_tool("compare_sources", {"source_ids":["survey-a", "unpublished"]}, ledger)
                return result["pairs"][0]
        pair = asyncio.run(run())
        self.assertEqual(pair["period_relation"], "disjoint coverage")
        self.assertEqual(pair["distinct_declarations"], ["measure"])
        self.assertIn("units", pair["unspecified"])
        self.assertEqual(pair["registered_record_keys"], [])
        self.assertEqual(compare([first, published])["pairs"][0]["period_relation"], "unspecified")
        with self.assertRaises(ValueError):
            validate_scope({"windows": [["2024-01-01", "2022-01-01"]]})

    def test_overlapping_release_windows_keep_returned_observation_labels_separate(self):
        k = Knowledge()
        ledger = Evidence(k, False)
        a, b = "mli-ch-late2025", "mli-wfp-market-prices"
        result = k.query([b], "SELECT date, market, price FROM market_prices ORDER BY date DESC LIMIT 1", ledger)
        review = compare([k.source(a), k.source(b)], [result])
        self.assertEqual(review["pairs"][0]["period_relation"], "overlapping coverage")
        self.assertEqual(review["pairs"][0]["registered_record_keys"], [])
        self.assertEqual(review["sources"][0]["returned_labels"], [])
        self.assertEqual(review["sources"][1]["returned_labels"][0]["labels"]["date"],
                         [result["data"]["rows"][0]["date"]])

    def test_unfamiliar_programme_distinguishes_allocations_and_actual_delivery(self):
        plan = {"id": "rural-water-plan", "title": "Plan", "period": "2024", "geography": "District",
                "comparison_scope": {"intended_outcomes": {"water.coverage": "Households served", "budget.allocated": "Allocated funds"}}}
        report = {**plan, "id": "accounts", "comparison_scope": {"measured_outcomes": {"budget.allocated": "Budget allocation"}}}
        checks = {row["indicator"]:row["sources_declaring_measure"] for row in compare([plan, report])["outcome_alignment"]}
        self.assertEqual(checks, {"water.coverage": [], "budget.allocated": ["accounts"]})
        self.assertEqual(compare([plan, {**report, "comparison_scope": {}}])["outcome_alignment"], [])
