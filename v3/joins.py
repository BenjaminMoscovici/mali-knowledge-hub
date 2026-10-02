"""Evidence-preserving thematic join layer.

These are candidate relationships among observations, stated priorities and
recorded activities. They do not claim programme causality or need coverage.
"""

from collections import defaultdict

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
        broad = any(item["normalized_sectors"].get(sector, {}).get("relation")
                    == "related_broad" for item in ledger
                    if item["evidence_id"] in {v for vv in ids.values() for v in vv})
        links.append({
            "sector": sector,
            "relation": "candidate_thematic_alignment",
            "source_evidence_ids": ids,
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
