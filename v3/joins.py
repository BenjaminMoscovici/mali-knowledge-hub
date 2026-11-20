"""Evidence-preserving thematic join layer.

These are candidate relationships among observations, stated priorities and
recorded activities. They do not claim programme causality or need coverage.
"""

from collections import defaultdict
from decimal import Decimal
import re

from normalization import classify_evidence, sector_matches


def enrich(ledger):
    for item in ledger:
        item["evidence_types"] = classify_evidence(item)
        item["normalized_sectors"] = sector_matches(
            " ".join(str(item.get(k) or "") for k in ("section", "content")),
            source_type=item.get("source_type")
        )
    return ledger


def build_join_context(ledger, geography, document_registry=()):
    """Construct only transparent, cited links; never create evidence IDs."""
    by_id = {item["evidence_id"]: item for item in ledger}
    by_sector = defaultdict(lambda: defaultdict(list))
    for item in ledger:
        source = item.get("source_family")
        for sector in item.get("normalized_sectors", {}):
            by_sector[sector][source].append(item["evidence_id"])

    links = []
    for sector, families in sorted(by_sector.items()):
        if len(families) < 2:
            continue
        ids = {family: values[:3] for family, values in families.items()}
        selected = [by_id[eid] for family_ids in ids.values() for eid in family_ids]
        broad = any(item["normalized_sectors"].get(sector, {}).get("relation")
                    == "related_broad" for item in selected)
        scopes = [{
            "evidence_id": item["evidence_id"],
            "geography": item.get("geographic_scope"),
            "period_start": item.get("reference_period_start"),
            "period_end": item.get("reference_period_end"),
            "evidence_types": item.get("evidence_types", ()),
        } for item in selected]
        links.append({
            "sector": sector,
            "relation": "candidate_thematic_alignment",
            "source_evidence_ids": ids,
            "scopes": scopes,
            "confidence": "theme_only",
            "taxonomy_relation": "related_broad" if broad else "equivalent_term",
            "caution": "Same sector terms across source families do not establish "
                       "that a project addresses a measured need, implements "
                       "a plan, covers an area, or achieves a result.",
        })

    local_plans = [d for d in document_registry
                   if any(term in str(d.get("document_type") or "").casefold()
                          for term in ("local development", "communal development",
                                       "regional development"))]
    return {
        "geography": geography,
        "relationships": links[:12],
        "local_plan_status": ("present" if local_plans else
                              "not represented in the current document registry"),
        "inventory_evidence_ids": [item["evidence_id"] for item in ledger
                                   if item.get("source_type") == "corpus_inventory"],
        "method": "Curated lexical sector matches across cited evidence; "
                  "document-level national priorities remain national; "
                  "FONGIM presence remains activity evidence.",
    }


def observation_comparisons(ledger, question):
    """Calculate only changes between verified matching annual observations."""
    if not re.search(r"\b(?:compar\w*|change|difference|variation|evolution|évolution|écart)\b",
                     question, re.I):
        return []
    groups = defaultdict(lambda: defaultdict(list))
    for item in ledger:
        value = item.get("observation")
        if not value:
            continue
        identity = tuple(value.get(key) for key in ("measure", "definition", "geography_id", "unit"))
        if all(identity):
            groups[identity][value["year"]].append((Decimal(str(value["value"])), item["evidence_id"]))
    calculations = []
    for identity, periods in groups.items():
        if len(periods) != 2 or any(len({value for value, _ in rows}) != 1 for rows in periods.values()):
            continue
        earlier, later = sorted(periods)
        old, old_id = periods[earlier][0]
        new, new_id = periods[later][0]
        if old.is_finite() and new.is_finite():
            calculations.append({
                "measure": identity[0], "definition": identity[1], "geography_id": identity[2],
                "unit": identity[3], "earlier_year": earlier, "earlier_value": str(old),
                "later_year": later, "later_value": str(new), "difference": str(new - old),
                "evidence_ids": [old_id, new_id],
            })
    return calculations


def prompt_context(joined):
    if not joined:
        return "No cross-source sector link established from the retrieved evidence."
    lines = ["CANDIDATE JOIN AUDIT (not independent evidence):"]
    if joined.get("inventory_evidence_ids"):
        lines.append("Local plans: " + joined["local_plan_status"] +
                     "; cite corpus inventory " +
                     ", ".join(joined["inventory_evidence_ids"]) +
                     ". Do not cite this audit as a source.")
    orgs = joined.get("organization_resolution", [])
    if orgs and not any(o["status"] == "resolved" for o in orgs):
        lines.append("No cross-source organisation identity was verified. "
                     "Similar names remain uncertain; do not attribute a "
                     "FONGIM activity to a document author.")
    for link in joined["relationships"]:
        refs = "; ".join(f"{family}: {', '.join(ids)}" for family, ids
                         in link["source_evidence_ids"].items())
        lines.append(f"- {link['sector']} ({link['taxonomy_relation']}): {refs}. "
                     "THEME ONLY; cite underlying IDs. "
                     "No programme relationship, coverage or outcome is proven.")
    return "\n".join(lines)
