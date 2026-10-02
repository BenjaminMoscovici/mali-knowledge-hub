"""Safety guards shared by the existing HAPI and FONGIM paths."""
import hashlib
import json


def paginated_hapi(get_page, endpoint, params, *, max_records=10000, page_size=1000):
    if not 1 <= page_size <= 1000 or not 1 <= max_records <= 100000:
        raise ValueError("Invalid bounded HAPI pagination")
    rows, fingerprints = [], set()
    while len(rows) < max_records:
        size = min(page_size, max_records - len(rows))
        result = get_page(endpoint, params=params, limit=size, offset=len(rows))
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise ValueError("Malformed HAPI page")
        page = result["data"]
        if len(page) > size or any(not isinstance(row, dict) for row in page):
            raise ValueError("Invalid HAPI page size or row")
        if any(row.get("location_code") != "MLI" for row in page):
            raise ValueError("HAPI ignored country filter")
        fingerprint = hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()
        if page and fingerprint in fingerprints: raise ValueError("HAPI repeated a page; offset may be ignored")
        fingerprints.add(fingerprint)
        rows.extend(page)
        if len(page) < size: return rows
    probe = get_page(endpoint, params=params, limit=1, offset=len(rows))
    if not isinstance(probe, dict) or not isinstance(probe.get("data"), list):
        raise ValueError("Malformed HAPI completion probe")
    if probe["data"]: raise ValueError("HAPI result exceeds record cap; completeness not established")
    return rows


def validate_fongim_refresh(candidate, previous, *, reviewed_shrink_reason=None):
    for field in ("project_count", "organization_count", "location_count", "sector_count"):
        if not isinstance(candidate.get(field), int) or candidate[field] < 1:
            raise ValueError(f"FONGIM empty or malformed {field}; previous mirror retained")
    for field, count in candidate.items():
        if not isinstance(count, int) or count < 0: raise ValueError("Malformed FONGIM row count")
        old = previous.get(field)
        if old is not None and (not isinstance(old, int) or old < 0):
            raise ValueError("Previous FONGIM validation baseline is malformed")
        if old and count < .75 * old and not reviewed_shrink_reason:
            raise ValueError(f"FONGIM shrinking {field}; review required before mirror replacement")
