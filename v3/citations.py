"""Check answer evidence identifiers and normalize citation ranges."""

import re

from answer_structure import review_units


def verify(answer, evidence):
    valid_ids = {item["evidence_id"] for item in evidence}

    def expand(match):
        first, last = map(int, match.groups())
        if last < first or last - first > 30:
            return match.group(0)
        return ", ".join(f"E{i:02d}" for i in range(first, last + 1))

    normalized = re.sub(r"\bE(\d+)\s*[–—-]\s*E(\d+)\b", expand, answer or "")
    cited = set(re.findall(r"\bE\d{2,}\b", normalized))
    invalid = sorted(cited - valid_ids)
    return normalized, {
        "cited_ids": sorted(cited),
        "invalid_ids": invalid,
        "valid": not invalid and (not evidence or bool(cited)),
        "evidence_count": len(valid_ids),
    }


# A conservative witness check for numbers in claims citing only registry sources.
# Mixed legacy evidence stays on its existing verification path.
_QUANTITY = re.compile(
    r"(?<![\w])(?P<sign>[-−])?(?P<number>\d{1,3}(?:[ ,\u00a0\u202f]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(?P<scale>millions?|billions?|milliards?))?(?![\w])", re.I
)
_CITATION = re.compile(r"\[(E\d{2,}(?:\s*[,;]\s*E\d{2,})*)\]")


def _quantities(text):
    from decimal import Decimal

    values = set()
    for match in _QUANTITY.finditer(text):
        raw = re.sub(r"[ \u00a0\u202f]", "", match["number"])
        if "," in raw:
            raw = raw.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw) else raw.replace(",", ".")
        scale = (match["scale"] or "").lower()
        factor = 10**9 if scale.startswith(("billion", "milliard")) else 10**6 if scale else 1
        values.add(Decimal(raw) * factor * (-1 if match["sign"] else 1))
    return values


def unsupported_registry_quantities(answer, evidence, *, check_all_cited=False, calculations=()):
    by_id = {item["evidence_id"]: item for item in evidence}
    problems = []
    for line in review_units(answer.splitlines())[0].values():
        cursor = 0
        for match in _CITATION.finditer(line):
            claim = line[cursor:match.start()]
            cursor = match.end()
            ids = re.findall(r"E\d{2,}", match[1])
            cited = [by_id.get(eid, {}) for eid in ids]
            if not check_all_cited and not all(item.get("source_type") in {"registry_record", "registry_document", "registry_observation"}
                       for item in cited):
                continue
            available = set()
            for item in cited:
                available |= _quantities(" ".join(str(item.get(key) or "") for key in (
                    "content", "reference_period_start", "reference_period_end",
                )))
            for calculation in calculations:
                if set(calculation["evidence_ids"]).issubset(ids):
                    available |= _quantities(calculation["difference"])
            unsupported = _quantities(claim) - available
            if unsupported:
                problems.append({"cited_ids": ids, "unsupported_quantity_count": len(unsupported)})
    return problems
