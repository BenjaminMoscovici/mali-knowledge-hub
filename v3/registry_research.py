"""Discover reviewed public releases and retrieve bounded, source-local evidence."""
from collections import Counter
from contextlib import closing
from decimal import Decimal
from functools import lru_cache
import gzip
import json
import logging
from pathlib import Path
import re
import sqlite3

from source_inventory import public_url
from source_wave import _fold, snapshot_path
from synthesis_context import extract_spans, terms

REGISTRY = Path(__file__).with_name("source_registry.json")
LOG = logging.getLogger(__name__)
EVIDENCE_REQUEST = re.compile(
    r"^(?:show (?:me )?(?:the )?(?:source )?evidence|"
    r"montrez (?:les )?(?:preuves|sources))\b"
)


@lru_cache(maxsize=4)
def _catalogue(path, revision):
    rows = json.loads(path.read_text())
    return tuple((row, row["research"]) for row in rows
                 if row.get("research")
                 and row.get("integration_status") in {"integrated", "integrated_with_limitations"}
                 and public_url(row.get("access_route")))


def _phrase(text, phrase):
    return f" {_fold(phrase)} " in f" {text} "


def _sqlite_rows(spec):
    query = {
        "document_pages": """
            SELECT page, content FROM mkh_document_pages
            WHERE release_id = ? ORDER BY page LIMIT 1001
        """,
        "humanitarian_observations": """
            SELECT o.id, o.reference_start, o.reference_end, o.population_status,
                   o.sector, o.category, o.value, o.unit, o.methodology,
                   s.locator, s.original_record_id
            FROM mkh_humanitarian_observations o
            JOIN mkh_evidence_spans s ON s.id = o.span_id AND s.release_id = o.release_id
            WHERE o.release_id = ? AND o.geographic_precision = 'country'
            ORDER BY s.locator, o.id LIMIT 1001
        """,
    }[spec["adapter"]]
    with closing(sqlite3.connect(f"file:{snapshot_path()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        release = db.execute("""
            SELECT upstream_version, retrieved_at, reference_start, reference_end
            FROM mkh_source_releases WHERE id = ? AND dataset_id = ?
        """, (spec["release_id"], spec["dataset_id"])).fetchone()
        if release is None:
            return []
        result = []
        for row in db.execute(query, (spec["release_id"],)):
            record = dict(release)
            record["payload"] = dict(row)
            record.update(row)
            record["version"] = release["upstream_version"]
            if "page" in record:
                record["id"] = f'{spec["release_id"]}:page:{row["page"]}'
                record["locator"] = f'PDF page {row["page"]}'
            result.append(record)
        return result


@lru_cache(maxsize=8)
def _package(path, revision):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)["records"]


def _records(spec, root):
    if spec["adapter"] != "packaged_records":
        return _sqlite_rows(spec)
    path = (root / spec["package"]).resolve()
    if path.parent != root.resolve() or not path.name.endswith(".json.gz"):
        raise ValueError("Expected a versioned local evidence package")
    return [row for row in _package(path, path.stat().st_mtime_ns)
            if row.get("release_id") == spec["release_id"] and row.get("dataset_id") == spec["dataset_id"]]


def _record_text(record, spec):
    payload = record["payload"]
    values = spec.get("value_labels", {})
    pairs = []
    for key, label in spec["fields"].items():
        value = payload.get(key)
        if value is not None and value != "":
            value = values.get(key, {}).get(str(value), value)
            pairs.append(f"{label}: {value}")
    for calculation in spec.get("differences", ()):
        left = payload.get(calculation["left"])
        right = payload.get(calculation["right"])
        unit = payload.get(calculation["unit_field"])
        if type(left) in {int, float} and type(right) in {int, float} and unit:
            # Both inputs must come from the same source row; retain the formula and unit.
            difference = Decimal(str(left)) - Decimal(str(right))
            if difference.is_finite():
                amount = f"{difference:,f}"
                if "." in amount:
                    amount = amount.rstrip("0").rstrip(".")
                pairs.append(f'{calculation["label"]}: {unit} {amount} '
                             f'({spec["fields"][calculation["left"]]} minus '
                             f'{spec["fields"][calculation["right"]]}; calculated within this row).')
    return "\n".join(pairs)


def _period_matches(row, years):
    start, end = row.get("reference_start"), row.get("reference_end")
    return not years or bool(start and end and
                             any(start[:4] <= year <= end[:4] for year in years))


def _evidence(source, spec, row, content):
    limitations = " ".join(source.get("limitations") or [])
    if limitations:
        content += f"\n\nSource limitations: {limitations}"
    return {
        "source_type": "registry_document" if "page" in row else "registry_record",
        "source_family": source["provider"], "document_title": source["source_name"],
        "organization": source["provider"], "source_endpoint": source["access_route"],
        "release_id": spec["release_id"], "record_id": row["id"], "version": row["version"],
        "reference_period_start": row.get("reference_start"), "reference_period_end": row.get("reference_end"),
        "retrieved_at": row.get("retrieved_at"), "geographic_scope": spec["scope"],
        "page": row.get("page"), "locator": row["locator"], "section": row["locator"],
        "content": content,
    }


def retrieve(question, registry=None, limit=8):
    """Return evidence and source-specific gaps for explicitly named capabilities."""
    path = registry or REGISTRY
    folded = _fold(question)
    if not folded:
        return [], []
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", folded))
    selected = []
    try:
        catalogue = _catalogue(path, path.stat().st_mtime_ns)
    except (OSError, TypeError, ValueError, KeyError):
        LOG.warning("Registry discovery unavailable")
        return [], []
    for source, spec in catalogue:
        cues = [alias for alias in spec["aliases"] if _phrase(folded, alias)]
        if not cues and years:
            cues = [topic for topic in spec.get("topics", ()) if _phrase(folded, topic)]
        if cues:
            selected.append((source, spec, cues))
    if not selected:
        return [], []
    if len(selected) > limit:
        return [], [(source["source_name"], "too_many_sources") for source, _, _ in selected]

    # Do not let source names outrank the substantive query terms inside a source.
    query = folded
    for _, _, cues in selected:
        for alias in sorted(cues, key=len, reverse=True):
            query = re.sub(r"(?<!\w)" + re.escape(_fold(alias)) + r"(?!\w)", " ", query)
    keywords = terms(query) - years - {"show", "montrez", "source", "sources", "preuves", "dans", "pour"}
    per_source = max(1, limit // len(selected))
    results, gaps = [], []
    for source, spec, _ in selected:
        name = source["source_name"]
        if spec.get("geographic_level") == "country" and re.search(
            r"\b(?:regions?|cercles?|communes?|districts?|villages?|localit\w*)\b", query
        ):
            gaps.append((name, "unsupported_geography"))
            continue
        try:
            rows = _records(spec, path.parent)
            wanted = keywords | {term for key, aliases in spec.get("term_aliases", {}).items()
                                 if key in keywords for term in aliases}
            identifiers = set(re.findall(spec["identifier_pattern"], folded)) if spec.get("identifier_pattern") else set()
            candidates = []
            for row in rows:
                if not _period_matches(row, years):
                    continue
                if identifiers and _fold(row["payload"].get(spec["identifier_field"])) not in identifiers:
                    continue
                content = row["content"] if "page" in row else _record_text(row, spec)
                if content:
                    words = tuple(set(_fold(content).split()))
                    matching = {term for term in wanted if any(word.startswith(term) for word in words)}
                    candidates.append((row, content, matching))
            counts = Counter(term for _, _, matches in candidates for term in matches)
            ranked = [(sum(1 / counts[term] for term in sorted(matches)), row, content)
                      for row, content, matches in candidates
                      if "page" not in row or not keywords or matches]
            ranked.sort(key=lambda item: -item[0])
            budget = min(per_source, 3) if spec["adapter"] == "document_pages" else per_source
            chosen = ranked[:budget]
            for _, row, content in chosen:
                if "page" in row and len(content) > 1300:
                    content, _ = extract_spans(content, wanted, budget=1300)
                    content = "Selected exact spans from this page:\n" + content
                results.append(_evidence(source, spec, row, content))
            if not chosen:
                gaps.append((name, "no_matching_evidence"))
            elif len(ranked) > budget:
                gaps.append((name, "excerpted_selection"))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            LOG.warning("Reviewed registry source could not be retrieved")
            gaps.append((name, "source_unavailable"))
    return results, gaps



def resolve_year_followup(question, previous):
    """Change only a single explicit year slot in the previous evidence brief."""
    new_year = re.fullmatch(r"(?:and (?:in|for)|et (?:en|pour)) ((?:19|20)\d{2})", _fold(question))
    if not new_year or not EVIDENCE_REQUEST.match(_fold(previous)):
        return None
    text = previous.strip()
    years = list(re.finditer(r"\b(?:in|for|en|pour) ((?:19|20)\d{2})\b", text, re.IGNORECASE))
    if len(years) != 1:
        return None
    start, end = years[0].span(1)
    # A comparison with a bare second year does not have a single year slot.
    if re.match(r"\s*(?:and|et|vs|versus|to|à)\s+(?:19|20)\d{2}\b", text[end:], re.IGNORECASE):
        return None
    return text[:start] + new_year[1] + text[end:]

def answer(question, language):
    """Expose a local, citable evidence brief for explicit evidence requests."""
    if not EVIDENCE_REQUEST.match(_fold(question)) or language not in {"English", "French"}:
        return None
    evidence, gaps = retrieve(question)
    if not (evidence or gaps):
        return None
    fr = language == "French"
    heading = ("Extraits et observations des sources demandées" if fr else
               "Excerpts and observations from the requested sources")
    lines = [heading]
    for index, item in enumerate(evidence, 1):
        eid = f"E{index:02d}"
        item["evidence_id"] = eid
        period = " – ".join(filter(None, (item["reference_period_start"], item["reference_period_end"])))
        scope = ", ".join(filter(None, (item["geographic_scope"], period)))
        lines.append(f'**{item["document_title"]} · {scope}** [{eid}]\n\n{item["content"]}')
    messages = {
        "too_many_sources": ("Précisez moins de sources.", "Narrow the requested set of sources."),
        "no_matching_evidence": ("Aucun élément correspondant dans la publication.", "No matching evidence in the release."),
        "excerpted_selection": ("Sélection partielle.", "Selected evidence only."),
        "source_unavailable": ("Publication indisponible.", "Release unavailable."),
        "unsupported_geography": ("Cette publication fournit uniquement des observations nationales.",
                                  "This release supplies national observations only."),
    }
    lines.extend(f'- **{source}** — {messages[reason][0 if fr else 1]}' for source, reason in gaps)
    if len({item["release_id"] for item in evidence}) > 1:
        lines.append("Chaque constat conserve sa période, sa définition et son périmètre. Aucun total combiné n’est calculé."
                     if fr else "Each finding retains its own period, definition and scope. No combined total is calculated.")
    return {"answer": "\n\n".join(lines), "evidence": evidence}
