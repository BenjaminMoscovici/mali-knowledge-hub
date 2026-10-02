import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from entity_audit import append_reviewed, load
from joins import build_join_context, enrich
from normalization import (EntityDecision, GeographyRegistry,
                           OrganizationResolver, classify_evidence,
                           sector_matches, filter_hapi_rows)
from routing import explicit_source_plan


class NormalizationTests(unittest.TestCase):
    def test_region_and_cercle_same_name_remain_distinct(self):
        registry = GeographyRegistry([
            {"region": "Mopti", "cercle": "Mopti", "commune_raw": "Mopti"},
            {"region": "Mopti", "cercle": "Bandiagara"},
        ])
        self.assertEqual(registry.resolve("Mopti")["status"], "ambiguous")
        self.assertEqual(registry.resolve("Mopti", level="region")["candidate"]["level"], "region")
        self.assertEqual(registry.resolve("Bandiagara", level="cercle")["candidate"]["parent_region"], "Mopti")
        self.assertEqual(registry.resolve("Mopti", level="commune")["status"], "provisional")

    def test_raw_commune_is_provisional_and_requires_parent_for_homonyms(self):
        registry = GeographyRegistry([
            {"region": "Mopti", "cercle": "Bandiagara", "commune_raw": "Centre"},
            {"region": "Mopti", "cercle": "Douentza", "commune_raw": "Centre"},
            {"region": "Mopti", "cercle": "Mopti", "commune_raw": "A, B"},
        ])
        self.assertEqual(registry.resolve("Centre", level="commune")["status"], "ambiguous")
        selected = registry.resolve("Centre", level="commune", parent_cercle="Bandiagara")
        self.assertEqual(selected["status"], "provisional")
        self.assertEqual(selected["candidate"]["parent_region"], "Mopti")
        self.assertEqual(selected["candidate"]["country"], "Mali")
        self.assertEqual(registry.resolve("A", level="commune")["status"], "unresolved")

    def test_homonymous_cercle_requires_parent(self):
        registry = GeographyRegistry([
            {"region": "Alpha", "cercle": "Centre"},
            {"region": "Beta", "cercle": "Centre"},
        ])
        self.assertEqual(registry.resolve("Centre", level="cercle")["status"], "ambiguous")
        self.assertEqual(registry.resolve("Centre", level="cercle", parent_region="Beta")
                         ["candidate"]["parent_region"], "Beta")

    def test_similar_organizations_are_not_merged(self):
        resolver = OrganizationResolver([
            "Agronomes et veterinaires sans frontieres - AVSF",
            "Véterinaires Sans Frontières Belgique ( VSFB)",
            "MSF-Espagne",
        ])
        self.assertEqual(resolver.resolve("MSF-Espagne", "FONGIM")["status"], "resolved")
        proposed = resolver.resolve("Veterinaires Sans Frontieres Belgique", "report")
        self.assertEqual(proposed["status"], "uncertain")
        self.assertIsNone(proposed["canonical"])
        acronym = resolver.resolve("AVSF", "report")
        self.assertEqual(acronym["method"], "source_explicit_acronym")
        self.assertEqual(acronym["canonical"],
                         "Agronomes et veterinaires sans frontieres - AVSF")
        self.assertEqual(resolver.resolve("MSF", "report")["status"], "uncertain")
        self.assertEqual(OrganizationResolver(["Muso"]).resolve("Muso", "report")
                         ["status"], "uncertain")

    def test_decision_supersession_preserves_history(self):
        old = EntityDecision("report", "AVSF", "Wrong", "manual", .8,
                             "resolved", "d1")
        new = EntityDecision("report", "AVSF", None, "review", 1.0,
                             "uncertain", "d2", "d1")
        resolver = OrganizationResolver(["Wrong"], [old, new])
        self.assertEqual(resolver.resolve("AVSF", "report")["status"], "uncertain")
        self.assertEqual(len(resolver.decisions), 2)

    def test_audit_requires_explicit_supersession_and_keeps_review_context(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "decisions.json"
            path.write_text(json.dumps({"schema_version": 1, "decisions": []}))
            first = append_reviewed("report", "AVSF", "Wrong", reviewer="reviewer",
                                    rationale="Initial evidence", path=path)
            with self.assertRaises(ValueError):
                append_reviewed("report", "AVSF", "Correct", reviewer="reviewer",
                                rationale="New evidence", path=path)
            append_reviewed("report", "AVSF", None, supersedes=first.decision_id,
                            reviewer="reviewer", rationale="Reversed", path=path)
            _, decisions = load(path)
            result = OrganizationResolver(["Wrong"], decisions).resolve("AVSF", "report")
            self.assertEqual(result["status"], "uncertain")
            self.assertEqual(result["rationale"], "Reversed")
            self.assertEqual(len(decisions), 2)

    def test_sector_mapping_does_not_force_broad_development(self):
        self.assertIn("WASH", sector_matches("Eau, hygiène et assainissement"))
        self.assertIn("food_security", sector_matches("sécurité alimentaire"))
        self.assertEqual(sector_matches("développement durable"), {})
        self.assertEqual(sector_matches("SAME", source_type="fongim_structured")
                         ["food_security"]["relation"], "related_broad")
        self.assertEqual(sector_matches("the same project"), {})

    def test_source_semantics_do_not_turn_activity_into_result(self):
        self.assertEqual(classify_evidence({"source_type": "fongim_structured",
                                            "content": "project results"})[0]["type"], "activity")

    def test_hapi_filter_response_cannot_inject_wrong_cercle(self):
        rows = [{"admin1_name": "Mopti", "admin2_name": "Mopti"},
                {"admin1_name": "Mopti", "admin2_name": "Bandiagara"},
                {"admin1_name": "Gao", "admin2_name": "Bandiagara"}]
        self.assertEqual(filter_hapi_rows(rows, region="Mopti", cercle="Bandiagara"),
                         [rows[1]])


class JoinTests(unittest.TestCase):
    def test_needs_with_named_fongim_routes_to_needs_sources(self):
        plan = explicit_source_plan(
            "Les besoins en eau à Ségou sont-ils couverts par les projets FONGIM ?")
        self.assertTrue(plan["hapi"] and plan["hnrp_docs"] and plan["fongim"])
        plan = explicit_source_plan(
            "Relate humanitarian needs, national priorities and FONGIM projects in Mopti")
        self.assertTrue(all(plan.values()))
        plan = explicit_source_plan(
            "Does a national strategy objective prove that a commune received an intervention?")
        self.assertTrue(plan["government_docs"] and plan["fongim"])
        self.assertFalse(plan["hapi"])

    def test_join_is_thematic_and_cites_original_evidence(self):
        items = enrich([
            {"evidence_id":"E01", "source_family":"OCHA humanitarian data",
             "source_type":"hdx_hapi", "content":"food security needs"},
            {"evidence_id":"E02", "source_family":"Government strategies",
             "source_type":"knowledge_base_document", "content":"sécurité alimentaire priority"},
            {"evidence_id":"E03", "source_family":"FONGIM intervention data",
             "source_type":"fongim_structured", "content":"sécurité alimentaire projects"},
        ])
        joined = build_join_context(items, {"region":"Mopti"},
                                    [{"document_type":"national strategy"}])
        self.assertEqual(joined["relationships"][0]["relation"], "candidate_thematic_alignment")
        self.assertEqual({ref for ids in joined["relationships"][0]
                          ["source_evidence_ids"].values() for ref in ids},
                         {"E01", "E02", "E03"})
        self.assertIn("not represented", joined["local_plan_status"])


if __name__ == "__main__":
    unittest.main()
