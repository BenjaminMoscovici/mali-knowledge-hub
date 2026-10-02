"""Classify old and newly ingested documents for source-aware retrieval."""

from document_targets import normal


def document_family(item):
    title = normal(item.get("document_title") or item.get("title") or "")
    kind = normal(item.get("document_type") or "")
    organization = normal(item.get("organization") or "")
    if (kind == "humanitarian needs and response plan"
            or "besoins humanitaires" in title
            or "plan de reponse" in title
            or "humanitarian needs and response" in title
            or ("humanitarian" in title and "ocha" in organization)):
        return "Humanitarian Response Plan / HNRP"
    if ("humanitarian" in title or "humanitarian" in kind
            or ("unicef" in organization and ("appeal" in title or "situation report" in title))):
        return "Humanitarian reports and appeals"
    return "Government strategies"
