"""Coverage signals for bounded follow-up retrieval, separate from claim support."""

import re

from synthesis_context import relevance, terms


DOCUMENT_FAMILIES = {
    "GOVERNMENT_DOCS": {"Government strategies"},
    "HNRP": {"Humanitarian Response Plan / HNRP", "Humanitarian reports and appeals"},
}


def topics_by_family(intents):
    """Group the planner's distinct topics without broadening source selection."""
    if len(intents) < 2:
        return {}
    grouped = {}
    for intent in intents[:8]:
        topic = str(intent.get("topic") or "").strip()[:350]
        if not topic:
            continue
        for family in intent.get("source_families", ()):
            topics = grouped.setdefault(family, [])
            if topic not in topics and len(topics) < 3:
                topics.append(topic)
    return grouped


def assess(intents, evidence):
    """Identify parts of the assignment that lack a plausible source match."""
    missing = []
    for intent in intents[:8]:
        topic = str(intent.get("topic") or "").strip()[:350]
        wanted = terms(topic) - {"retrieved", "reported", "source", "sources"}
        years = set(re.findall(r"\b(?:19|20)\d{2}\b", topic))
        wanted -= years
        families = tuple(dict.fromkeys(intent.get("source_families", ())))
        if not topic or not families:
            continue

        def candidate(item):
            source_type = item.get("source_type")
            return any(
                (source_type == "knowledge_base_document"
                 and item.get("source_family") in DOCUMENT_FAMILIES.get(family, ()))
                or (family == "HAPI" and source_type == "hdx_hapi")
                or (family == "FONGIM" and source_type == "fongim_structured")
                or family == item.get("registry_capability")
                for family in families
            )

        plausible = [item for item in evidence if candidate(item)
                     and relevance(item.get("content", ""), wanted) >= min(2, len(wanted))]
        if not years:
            covered = bool(plausible)
        else:
            covered_years = set()
            for item in plausible:
                start = str(item.get("reference_period_start") or "")[:4]
                end = str(item.get("reference_period_end") or "")[:4]
                if start and end:
                    covered_years.update(year for year in years if start <= year <= end)
                elif len(years) == 1:
                    # Many indexed passages do not carry a normalized period.
                    # Their precise date still needs to be checked at synthesis.
                    covered_years.update(years)
                else:
                    covered_years.update(years.intersection(re.findall(
                        r"\b(?:19|20)\d{2}\b", item.get("content") or ""
                    )))
            covered = years.issubset(covered_years)
        if not covered:
            missing.append({"topic": topic, "families": families})
    return missing


def retry_target(missing, trace, registered_evidence):
    registry_choices = {item.get("registry_capability") for item in registered_evidence}
    for gap in missing:
        for family, key in (("GOVERNMENT_DOCS", "government_docs"), ("HNRP", "hnrp_docs")):
            state = trace.get(key, {})
            if family in gap["families"] and state.get("requested") and state.get("status") in {
                "SUCCESS_ZERO_RESULTS", "SUCCESS_WITH_RESULTS",
            }:
                return gap["topic"], key
        for family in gap["families"]:
            if family in registry_choices:
                return gap["topic"], family
    return None
