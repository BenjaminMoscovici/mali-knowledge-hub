"""Evidence-preserving thematic join layer.

These are candidate relationships among observations, stated priorities and
recorded activities. They do not claim programme causality or need coverage.
"""

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from normalization import classify_evidence, sector_matches
from registry_observations import OBSERVATION_DIMENSIONS, observation_identity


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

    by_entity = defaultdict(dict)
    for item in ledger:
        ref = item.get("entity_reference")
        if ref and item.get("source_family"):
            identity = (ref["namespace"], ref["id"])
            role = (item["source_family"], ref["role"])
            by_entity[identity].setdefault(role, item["evidence_id"])
    exact_entities = [
        {"namespace": namespace, "id": identifier,
         "sources": [{"family": family, "role": role, "evidence_id": eid}
                     for (family, role), eid in records.items()]}
        for (namespace, identifier), records in by_entity.items()
        if len({family for family, _ in records}) > 1
    ]

    local_plans = [d for d in document_registry
                   if any(term in str(d.get("document_type") or "").casefold()
                          for term in ("local development", "communal development",
                                       "regional development"))]
    return {
        "geography": geography,
        "relationships": links[:12],
        "exact_entities": exact_entities[:12],
        "local_plan_status": ("present" if local_plans else
                              "not represented in the current document registry"),
        "inventory_evidence_ids": [item["evidence_id"] for item in ledger
                                   if item.get("source_type") == "corpus_inventory"],
        "method": "Curated lexical sector matches across cited evidence; "
                  "document-level national priorities remain national; "
                  "FONGIM presence remains activity evidence.",
    }


def _comparison_observations(item):
    observation = item.get("observation")
    if observation:
        yield observation
    funding = item.get("funding_record")
    if not funding or not (
        funding.get("source_namespace") == "FTS" and funding.get("plan_id")
        and funding.get("scope") == "Mali; national plan/year only"
        and funding.get("comparable_within_record") and funding.get("amount_unit") == "currency_unit"
        and funding.get("funding_definition") and funding.get("retrieved_at")
        and re.fullmatch(r"[A-Z]{3}", funding.get("currency") or "")
    ):
        return
    year = funding.get("year")
    code = re.fullmatch(r"([A-Z]+)(\d{2})", funding.get("plan_code") or "")
    if type(year) is not int or not code or int(code[2]) != year % 100:
        return
    base = {
        "series_id": f"FTS:{code[1]}:{funding['currency']}",
        "geography_id": "MLI:country", "geographic_level": "country",
        "year": funding["year"], "period_type": "plan usage year at common snapshot",
        "methodology": funding["retrieved_at"],
    }
    for measure, field, definition in (
        ("Plan requirements", "requirements", "Declared requirements of the named plan"),
        ("Reported plan funding", "reported_funding", funding["funding_definition"]),
    ):
        value = _finite_number(funding.get(field))
        if value is not None and value >= 0:
            yield {**base, "measure": measure, "definition": definition,
                   "unit": funding["currency"], "value": value}
    requirements = _finite_number(funding.get("requirements"))
    reported = _finite_number(funding.get("reported_funding"))
    if requirements is not None and requirements > 0 and reported is not None and reported >= 0:
        yield {**base, "measure": "Share of declared plan requirements funded",
               "definition": funding["funding_definition"], "denominator": "declared plan requirements",
               "unit": "percent", "value": reported * 100 / requirements}


def _finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def observation_comparisons(ledger, question):
    """Compute annual or same-framework spatial differences with both source IDs."""
    if not re.search(r"\b(?:compar\w*|change\w*|difference\w*|variation|evolution|évolution|écart|versus)\b",
                     question, re.I):
        return []
    years = {int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", question)}
    annual = defaultdict(lambda: defaultdict(list))
    spatial = defaultdict(lambda: defaultdict(list))
    for item in ledger:
        for record in _comparison_observations(item):
            identity = observation_identity(record)
            year, value = record.get("year"), _finite_number(record.get("value"))
            if not identity or type(year) is not int or value is None:
                continue
            if str(record.get("series_id") or "").startswith("FTS:") and (len(years) != 2 or year not in years):
                continue
            row = (value, item["evidence_id"])
            annual[identity][year].append(row)
            if record.get("geography_framework") and record.get("geographic_level") and (not years or year in years):
                common = tuple(record.get(field) for field in OBSERVATION_DIMENSIONS if field != "geography_id")
                spatial[(common, year)][record["geography_id"]].append(row)

    def compare(groups, dimensions, axis):
        for identity, buckets in groups.items():
            if len(buckets) != 2 or any(len({value for value, _ in rows}) != 1 for rows in buckets.values()):
                continue
            first, second = sorted(buckets)
            left, left_id = buckets[first][0]
            right, right_id = buckets[second][0]
            if left_id == right_id:
                continue
            metadata = {field: value for field, value in zip(dimensions, identity) if value is not None}
            difference = right - left
            difference_unit = metadata["unit"]
            if difference_unit == "percent":
                difference = difference.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
                difference_unit = "percentage points"
            yield {**metadata, **dict(zip(axis, (first, str(left), second, str(right)))),
                   "difference": str(difference), "difference_unit": difference_unit,
                   "evidence_ids": [left_id, right_id]}

    calculations = []
    calculations.extend(compare(annual, OBSERVATION_DIMENSIONS,
                                ("earlier_year", "earlier_value", "later_year", "later_value")))
    if len(years) <= 1:
        spatial_fields = tuple(field for field in OBSERVATION_DIMENSIONS if field != "geography_id")
        for (identity, year), buckets in spatial.items():
            calculations.extend({"year": year, **result} for result in compare(
                {identity: buckets}, spatial_fields,
                ("first_geography_id", "first_value", "second_geography_id", "second_value")))
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
    for entity in joined.get("exact_entities", ()):
        sources = "; ".join(f"{row['family']} ({row['role']}): {row['evidence_id']}"
                            for row in entity["sources"])
        lines.append(
            f"- Exact identifier {entity['namespace']} {entity['id']}: {sources}. "
            "Identity only. Keep source-reported statuses and dates separate. "
            "An evaluation finding does not establish current delivery or apply beyond its study scope."
        )
    for link in joined["relationships"]:
        refs = "; ".join(f"{family}: {', '.join(ids)}" for family, ids
                         in link["source_evidence_ids"].items())
        lines.append(f"- {link['sector']} ({link['taxonomy_relation']}): {refs}. "
                     "THEME ONLY; cite underlying IDs. "
                     "No programme relationship, coverage or outcome is proven.")
        for scope in link["scopes"]:
            period = " to ".join(filter(None, (scope["period_start"], scope["period_end"])))
            roles = ", ".join(role["type"] for role in scope["evidence_types"] if role.get("type"))
            if scope["geography"] or period or roles:
                lines.append(
                    f"  {scope['evidence_id']}: {scope['geography'] or 'geography unreported'}; "
                    f"{period or 'period unreported'}; {roles or 'role unclassified'}."
                )
    return "\n".join(lines)
