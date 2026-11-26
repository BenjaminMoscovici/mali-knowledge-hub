import unittest

import httpx

from companion import Companion
from knowledge import Evidence, Knowledge


class SourceAccess(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_pages_and_topic_matches_include_new_and_last_sources(self):
        template = next(s for s in Knowledge().sources.values() if s["type"] == "document")
        releases = [{**template, "id": f"public-{i:03}", "description": "shared subject"} for i in range(165)]
        k = Knowledge(releases=releases + [{**template, "id":"withdrawn", "review":"withdrawn"}])
        async with httpx.AsyncClient() as client:
            companion = Companion(k, client, "test")
            for query in ("", "shared subject"):
                ids = []
                offset = 0
                while offset is not None:
                    page = await companion.run_tool("discover_sources", {"query":query, "kind":None, "offset":offset}, Evidence(k, False))
                    self.assertEqual(page["matching_total"], len(releases))
                    ids.extend(s["id"] for s in page["sources"])
                    offset = page["next_offset"]
                self.assertCountEqual(ids, [s["id"] for s in releases])

    async def test_all_current_sources_support_a_native_operation(self):
        k = Knowledge()
        async with httpx.AsyncClient() as client:
            comp = Companion(k, client, "test")
            ledger = Evidence(k, False)
            for source in k.source_page(page_size=len(k.sources))["sources"]:
                key = source["id"]
                meta = await comp.run_tool("inspect_source", {"source_id":key}, ledger)
                self.assertTrue(meta["limitations"])
                if source["type"] == "document":
                    result = await comp.run_tool("read_passage", {"source_id":key,"locator":meta["pages"][0]["locator"],"offset":0},ledger)
                    self.assertTrue(result["data"]["text"])
                elif source["type"] == "live":
                    self.assertIn("fetch_live",source["operations"])
                    self.assertTrue(meta["series"])
                    continue
                else:
                    result = await comp.run_tool("query_data", {"source_ids":[key],"sql":"SELECT count(*) AS n FROM " + meta["table"]}, ledger)
                    self.assertEqual(result["data"]["rows"][0]["n"], meta["row_count"])
                self.assertTrue(ledger.allowed(result))
