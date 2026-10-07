"""Check HAPI locality cardinality in the evidence actually shown to synthesis."""
import json
import re


def sector_citation_index(ledger):
    """Navigate exact local sector observations; never create a needs aggregate."""
    rows = []
    for item in ledger:
        eid, sector = item.get("evidence_id"), item.get("sector_name")
        if (item.get("source_family") != "OCHA humanitarian data"
                or str(item.get("admin_level")) != "2"
                or not re.fullmatch(r"E\d+", str(eid or ""))
                or not sector or str(sector).casefold() == "intersectoral"
                or not item.get("admin1_name") or not item.get("admin2_name")):
            continue
        rows.append({"id": eid, "sector": sector,
                     "source_region": item["admin1_name"],
                     "source_locality": item["admin2_name"]})
    if not rows:
        return ""
    return ("DIRECT LOCAL NEEDS CITATION INDEX (navigation only): "
            + json.dumps(rows, ensure_ascii=False)
            + ". Cite the original observation for each local need sector named. "
              "These are source Admin2 observations, not regional sector totals, "
              "severity rankings, approved crosswalks or current delivery. "
              "Keep the original reference period and scope; do not cite this index.")


def intersectoral_locality_note(ledger):
    places = {}
    for item in ledger:
        if (item.get("source_family") != "OCHA humanitarian data"
                or str(item.get("admin_level")) != "2"
                or str(item.get("sector_name") or "").casefold() != "intersectoral"
                or str(item.get("population_category") or "").casefold() != "total"):
            continue
        region, locality = item.get("admin1_name"), item.get("admin2_name")
        if not region or not locality:
            continue
        places.setdefault((str(region), str(locality)), item.get("evidence_id"))
    if not places:
        return ""
    names = "; ".join(f"{locality} [{places[region, locality]}]"
                      for region, locality in sorted(places))
    return (f"CHECKED HAPI LEDGER COUNT: {len(places)} distinct Admin2 locality "
            f"names have intersectoral total-population needs records in this "
            f"retrieved evidence subset: {names}. This counts source localities, "
            f"not people in need or a regional aggregate. If naming a number "
            f"of these localities, use {len(places)}; otherwise omit the count.")
