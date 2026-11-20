"""Read-only lookup of reviewed annual observations declared in the source registry."""
from functools import lru_cache
import json
from pathlib import Path
import re

from source_inventory import public_url
from source_wave import _fold

REGISTRY = Path(__file__).with_name("source_registry.json")

# A bounded lookup grammar. Extra clauses belong on the ordinary research path.
LOOKUP = re.compile(
    r"(?:(?:what (?:was|is)|how many|give me|combien (?:de|d)|quelle (?:etait|est)|quel (?:etait|est)|donnez) "
    r"(?:the |la |le |les |l )?|(?P<compare>compare|comparez) (?:the |la |le |les |l )?)?"
    r"(?P<subject>.+?) (?:in |for |en |pour |de |of )?"
    r"(?P<years>(?:19|20)\d{2}(?:(?: and | et | vs | versus | a | to )(?:19|20)\d{2})?)"
)


@lru_cache(maxsize=4)
def _read(path, revision):
    entries = json.loads(path.read_text())
    return tuple((source, capability) for source in entries
                 for capability in source.get("annual_observations", ())
                 if source.get("integration_status") in {"integrated_with_limitations", "integrated"}
                 and public_url(source.get("access_route")))



def _capabilities(path):
    for source, capability in _read(path, path.stat().st_mtime_ns):
        subjects = {_fold(alias.format(place=place))
                    for alias in capability["aliases"] for place in capability["place_aliases"]}
        yield source, capability, subjects


OBSERVATION_DIMENSIONS = (
    "measure", "definition", "geography_id", "unit",
    "denominator", "population", "methodology", "geographic_level", "period_type", "geography_framework", "series_id",
)


def observation_identity(record):
    """Match the required identity and every additional dimension declared."""
    dimensions = tuple(record.get(field) for field in OBSERVATION_DIMENSIONS)
    return dimensions if all(dimensions[:4]) else None


def _observation(source, capability, row):
    year = row["year"]
    return {
        "source_type": "registry_observation", "document_title": source["source_name"],
        "source_family": source["provider"], "organization": source["provider"],
        "version": capability["version"], "release_id": capability["release_id"], "record_id": row["id"],
        "source_endpoint": source["access_route"], "page": row.get("page"),
        "section": row["locator"], "locator": row["locator"],
        "reference_period_start": f"{year}-01-01", "reference_period_end": f"{year}-12-31",
        "retrieved_at": source.get("last_successful_retrieval"), "geographic_scope": capability["place"],
        "observation": {**{field: capability[field] for field in OBSERVATION_DIMENSIONS
                           if field in capability}, "year": year, "value": row["value"]},
        "content": row["excerpt"],
    }


def retrieve(question, registry=None):
    """Supply referenced observations to normal synthesis, including compound requests."""
    text = _fold(question)
    matches = []
    for source, capability, subjects in _capabilities(registry or REGISTRY):
        for subject in sorted(subjects, key=lambda value: (-len(value), value)):
            # Require the declared subject and year together. A date in another
            # clause must not be applied to this observation.
            match = re.search(
                rf"(?<!\w){re.escape(subject)} (?:in |for |en |pour |de |of )?"
                rf"((?:19|20)\d{{2}}(?:(?: and | et | vs | versus | a | to )(?:19|20)\d{{2}})?)(?!\d)", text)
            if match:
                years = set(map(int, re.findall(r"\d{4}", match[1])))
                matches.extend(_observation(source, capability, row)
                               for row in capability["records"] if row["year"] in years)
                break
    return matches


def resolve_year_followup(question, previous):
    """Carry forward an explicit registry subject when only the year changes."""
    year = re.fullmatch(r"(?:and in|what about|et en|et pour) ((?:19|20)\d{2})", _fold(question))
    match = LOOKUP.fullmatch(_fold(previous or ""))
    if not year or not match or match["compare"] or len(match["years"]) != 4:
        return None
    try:
        known_subject = any(match["subject"] in subjects for _, _, subjects in _capabilities(REGISTRY))
    except OSError:
        return None
    if not known_subject:
        return None
    return match["subject"] + " " + year[1]

def answer(question, language, registry=None):
    """Return a cited result for exact measure, geography and reference-year requests."""
    match = LOOKUP.fullmatch(_fold(question))
    if not match:
        return None
    path = registry or REGISTRY
    subject = match["subject"]
    years = tuple(dict.fromkeys(map(int, re.findall(r"\d{4}", match["years"]))))
    selections = []
    for source, capability, subjects in _capabilities(path):
        if subject in subjects:
            selections.append((source, capability))
    selected = [(source, capability, row) for source, capability in selections
                for row in capability["records"] if row["year"] in years]
    if not selected:
        return None
    # Identical wording can describe different measures or boundary vintages.
    identities = {observation_identity(c) for _, c, _ in selected}
    if len(identities) != 1 or None in identities:
        return None
    fr = language == "French"
    if language not in {"English", "French"}:
        return None
    lines, evidence = [], []
    for source, capability, row in sorted(selected, key=lambda item: (item[2]["year"], item[0]["source_name"])):
        eid = f"E{len(evidence) + 1:02d}"
        value = f'{row["value"]:,}'
        if fr:
            value = value.replace(",", "\u202f")
        label = capability["labels"]["fr" if fr else "en"]
        unit = capability["unit_labels"]["fr" if fr else "en"]
        note = capability["notes"]["fr" if fr else "en"]
        lines.append(f'- **{row["year"]} · {capability["place"]}** · {label} — **{value} {unit}** ({source["provider"]}). {note} [{eid}]')
        evidence.append({**_observation(source, capability, row), "evidence_id": eid})
    missing = set(years) - {row["year"] for _, _, row in selected}
    if missing:
        years_text = ", ".join(map(str, sorted(missing)))
        lines.append(f"Année sans observation dans ce registre : {years_text}." if fr else
                     f"No matching observation in this registry for {years_text}.")
    elif match["compare"] and len(years) == len(selected) == 2:
        earlier, later = sorted((row for _, _, row in selected), key=lambda row: row["year"])
        difference = f'{later["value"] - earlier["value"]:+,}'
        if fr:
            difference = difference.replace(",", "\u202f")
        unit = selected[0][1]["unit_labels"]["fr" if fr else "en"]
        period = f'{earlier["year"]}–{later["year"]}'
        lines.append(f"Écart {period} : **{difference} {unit}**. [E01, E02]" if fr else
                     f"Change {period}: **{difference} {unit}**. [E01, E02]")
    return {"answer": "\n".join(lines), "evidence": evidence}
