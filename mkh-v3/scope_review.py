"""Compare declared release scopes without inferring comparability from place names."""
from datetime import date
from itertools import combinations
import re


FACETS = ("geographic_frame", "grain", "measure", "units", "basis")


OUTCOMES = ("intended_outcomes", "measured_outcomes")


def validate_scope(scope):
    if not isinstance(scope, dict) or set(scope) - {*FACETS, *OUTCOMES, "windows"}:
        raise ValueError("Unknown source comparison metadata")
    if any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 240
           for k, v in scope.items() if k in FACETS):
        raise ValueError("Invalid source comparison label")
    for role in OUTCOMES:
        outcomes = scope.get(role, {})
        if not isinstance(outcomes, dict) or len(outcomes) > 20 or any(
            not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", key)
            or not isinstance(label, str) or not 1 <= len(label.strip()) <= 160 for key, label in outcomes.items()
        ):
            raise ValueError("Use a stable indicator code and short label for each declared outcome.")
    windows = scope.get("windows", [])
    if not isinstance(windows, list) or len(windows) > 12:
        raise ValueError("Invalid release coverage windows")
    for window in windows:
        if not isinstance(window, list) or len(window) != 2 or not all(isinstance(x, str) for x in window):
            raise ValueError("Supply date pairs for release coverage")
        dates = [date.fromisoformat(x) for x in window]
        if dates[0] > dates[1] or window != [d.isoformat() for d in dates]:
            raise ValueError("Invalid release coverage dates")


def evidence_sources(items):
    ids = {}
    for item in items:
        if item.get("origin") == "canon":
            ids[item["source_id"]] = None
            ids.update((r["source_id"], None) for r in item["data"].get("input_releases", []))
    return list(ids)


def period_relation(a, b):
    if not a or not b:
        return "unspecified"
    if sorted(a) == sorted(b):
        return "same coverage"
    if any(max(x, u) <= min(y, v) for x, y in a for u, v in b):
        return "overlapping coverage"
    return "disjoint coverage"


def returned_labels(source, evidence):
    fields = set(source.get("dimensions", [])) | set(source.get("place_fields", []))
    fields.update(source.get("comparison_fields", []))
    selections = []
    for item in evidence:
        if item.get("source_id") != source["id"] or item.get("origin") != "canon":
            continue
        data = item["data"]
        if len(data.get("input_releases", [])) > 1:
            continue
        rows = data.get("rows", [data])
        labels = {}
        for field in sorted(fields):
            values = list(dict.fromkeys(row[field] for row in rows
                          if isinstance(row.get(field), (str, int, float))))
            if values:
                labels[field] = values[:5]
        if labels:
            selections.append({"evidence_id": item["id"], "labels": labels})
    return selections[-3:]


def outcome_alignment(sources):
    measured = {}
    for source in sources:
        for key in source.get("comparison_scope", {}).get("measured_outcomes", {}):
            measured.setdefault(key, []).append(source["id"])
    if not measured:
        return []
    checks = []
    for source in sources:
        for key, label in source.get("comparison_scope", {}).get("intended_outcomes", {}).items():
            checks.append({"objective_source": source["id"], "outcome": label, "indicator": key,
                           "sources_declaring_measure": measured.get(key, [])})
    return checks


def compare(sources, evidence=()):
    profiles = []
    for s in sources:
        scope = s.get("comparison_scope", {})
        profiles.append({"source_id": s["id"], "title": s["title"], "geography": s["geography"],
                         "period": s["period"], **scope, "limitations": s.get("limitations", [])[:2],
                         "returned_labels": returned_labels(s, evidence)})
    pairs = []
    for a, b in combinations(sources, 2):
        x, y = (s.get("comparison_scope", {}) for s in (a, b))
        differences = [k for k in FACETS if x.get(k) and y.get(k) and x[k] != y[k]]
        unknown = [k for k in FACETS if not x.get(k) or not y.get(k)]
        pairs.append({"left": a["id"], "right": b["id"],
                      "period_relation": period_relation(x.get("windows"), y.get("windows")),
                      "distinct_declarations": differences, "unspecified": unknown,
                      "registered_record_keys": sorted(a.get("entity_keys", {}).keys() & b.get("entity_keys", {}).keys())})
    return {"sources": profiles, "pairs": pairs, "outcome_alignment": outcome_alignment(sources),
            "interpretation": "Release-level review. Check the selected records, reporting periods, units and definitions. "
                              "Overlapping coverage alone does not establish matching observations. A registered key identifies "
                              "an entity only. Returned labels are samples from evidence rows; totals can omit grouping fields. Inspect the cited calculation for its filters."}
