"""Check answer evidence identifiers and normalize citation ranges."""

import re


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
