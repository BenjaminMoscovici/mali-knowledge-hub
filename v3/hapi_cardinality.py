"""Check HAPI locality cardinality in the evidence actually shown to synthesis."""


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
