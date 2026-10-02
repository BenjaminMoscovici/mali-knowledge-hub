"""Conservative, inspectable cross-source normalization for MKH V2.

No fuzzy proposal is silently promoted to an entity or geographic fact.
Decisions are immutable records in a versioned local registry; a later
decision can supersede an earlier one without erasing source values.
"""

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import re
import unicodedata


def fold(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value.casefold()).strip()


def key(value):
    return re.sub(r"[^\w]+", " ", fold(value)).strip()


@dataclass(frozen=True)
class GeoCandidate:
    raw: str
    canonical: str
    level: str
    parent_region: str | None
    method: str
    confidence: float
    parent_cercle: str | None = None
    country: str = "Mali"


class GeographyRegistry:
    def __init__(self, locations, aliases=None):
        self.by_name = {}
        self.aliases = aliases or {}
        for row in locations:
            region = str(row.get("region") or "").strip()
            cercle = str(row.get("cercle") or "").strip()
            if region:
                self._add(region, region, "region", None)
            if cercle:
                self._add(cercle, cercle, "cercle", region or None)
            commune = str(row.get("commune_raw") or "").strip()
            # A single source label is a provisional node, never a verified
            # administrative commune. Multi-place strings stay raw only.
            if (commune and cercle and len(commune) <= 80 and
                    not re.search(r"[,;/|]|\s+(?:et|and)\s+", commune, re.I)):
                self._add(commune, commune, "commune", region or None,
                          parent_cercle=cercle, method="source_raw_unverified",
                          confidence=0.55)

    def _add(self, raw, canonical, level, parent, *, parent_cercle=None,
             method="source_exact", confidence=1.0):
        candidate = GeoCandidate(raw, canonical, level, parent, method,
                                 confidence, parent_cercle)
        bucket = self.by_name.setdefault(key(raw), [])
        if candidate not in bucket:
            bucket.append(candidate)

    def match(self, raw, *, level=None, parent_region=None, parent_cercle=None):
        normalized = key(raw)
        target = self.aliases.get(normalized, normalized)
        found = list(self.by_name.get(target, []))
        if level:
            found = [c for c in found if c.level == level]
        if parent_region:
            found = [c for c in found if c.parent_region is None or
                     key(c.parent_region) == key(parent_region)]
        if parent_cercle:
            found = [c for c in found if c.parent_cercle is None or
                     key(c.parent_cercle) == key(parent_cercle)]
        if target != normalized:
            found = [GeoCandidate(raw, c.canonical, c.level, c.parent_region,
                                  "curated_alias", min(c.confidence, 0.98),
                                  c.parent_cercle) for c in found]
        return found

    def resolve(self, raw, *, level=None, parent_region=None, parent_cercle=None):
        found = self.match(raw, level=level, parent_region=parent_region,
                           parent_cercle=parent_cercle)
        if len(found) == 1:
            return {"status": ("provisional" if found[0].level == "commune"
                               else "resolved"), "candidate": asdict(found[0])}
        return {"status": "ambiguous" if found else "unresolved",
                "raw": raw, "candidates": [asdict(c) for c in found]}


@dataclass(frozen=True)
class EntityDecision:
    source: str
    raw: str
    canonical: str | None
    method: str
    confidence: float
    status: str
    decision_id: str | None = None
    supersedes: str | None = None
    reviewer: str | None = None
    rationale: str | None = None
    recorded_at: str | None = None


class OrganizationResolver:
    def __init__(self, canonical_names, decisions=()):
        self.names = sorted(set(str(v).strip() for v in canonical_names if v))
        self.decisions = list(decisions)

    def resolve(self, raw, source):
        raw = str(raw or "").strip()
        relevant = [d for d in self.decisions if d.source == source and d.raw == raw]
        superseded = {d.supersedes for d in relevant if d.supersedes}
        active = [d for d in relevant if d.decision_id not in superseded]
        if len(active) == 1:
            return asdict(active[0])
        if len(active) > 1:
            return {**asdict(EntityDecision(source, raw, None, "review_conflict",
                                            0.0, "uncertain")),
                    "conflicting_decision_ids": [d.decision_id for d in active]}
        # Exact source spelling is safe; folded spelling is a proposal only.
        exact = [name for name in self.names if name == raw]
        distinctive = len(key(raw).split()) >= 2 and len(key(raw)) >= 8
        if len(exact) == 1 and (fold(source) == "fongim" or distinctive):
            return asdict(EntityDecision(source, raw, exact[0], "exact", 1.0, "resolved"))
        normalized_exact = [name for name in self.names if key(name) == key(raw)]
        if len(normalized_exact) == 1 and distinctive:
            return asdict(EntityDecision(source, raw, normalized_exact[0],
                                         "normalized_exact", .94, "resolved"))
        # An acronym visibly attached to a full source name is a stronger
        # signal than a fuzzy string score. Require uniqueness across names;
        # never shorten a country-qualified branch such as MSF-Espagne to MSF.
        explicit = []
        for name in self.names:
            suffix = re.search(r"(?:\(\s*|\s[-–]\s)([A-Z]{2,8})\s*\)?\s*$", name)
            if suffix and key(suffix.group(1)) == key(raw):
                explicit.append(name)
        if len(explicit) == 1:
            return asdict(EntityDecision(source, raw, explicit[0],
                                         "source_explicit_acronym", .97, "resolved"))
        possible = sorted(((SequenceMatcher(None, key(raw), key(name)).ratio(), name)
                           for name in self.names if name != raw), reverse=True)[:3]
        return {**asdict(EntityDecision(source, raw, None, "proposal", 0.0,
                                        "uncertain")),
                "candidates": [{"name": name, "similarity": round(score, 3)}
                               for score, name in possible if score >= 0.7]}


# Equivalent terms are mapped; broad development concepts intentionally remain
# unmapped. A separate 'related' relationship can be added after source review.
SECTOR_ALIASES = {
    "wash": "WASH", "eha": "WASH", "eau hygiene assainissement": "WASH",
    "eau hygiene et assainissement": "WASH", "water sanitation hygiene": "WASH",
    "nutrition": "nutrition", "securite alimentaire": "food_security",
    "food security": "food_security", "sante": "health", "health": "health",
    "protection": "protection", "education": "education",
    "abris": "shelter", "shelter": "shelter",
    "moyens d existence": "livelihoods", "livelihoods": "livelihoods",
}


def sector_matches(text, source_type=None):
    cleaned = key(text)
    matches = {}
    for alias, canonical in SECTOR_ALIASES.items():
        if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", cleaned):
            matches.setdefault(canonical, []).append(alias)
    result = {canonical: {"canonical": canonical, "matched_terms": terms,
                          "method": "curated_term", "relation": "equivalent_term",
                          "confidence": 0.95}
              for canonical, terms in matches.items()}
    if source_type == "fongim_structured" and re.search(r"\bSAME\b", text):
        result["food_security"] = {
            "canonical": "food_security", "matched_terms": ["FONGIM SAME"],
            "method": "curated_taxonomy", "relation": "related_broad",
            "confidence": 0.72,
        }
    return result


EVIDENCE_TYPES = {
    "need": (r"\bbesoin(?:s)?\b", r"\bpeople in need\b", r"\bpin\b"),
    "priority": (r"\bpriorit(?:e|es|y|ies)\b",),
    "objective": (r"\bobjectif(?:s)?\b", r"\bobjective(?:s)?\b"),
    "target": (r"\bcible(?:s)?\b", r"\btarget(?:s)?\b"),
    "recommendation": (r"\brecommandation(?:s)?\b", r"\brecommendation(?:s)?\b"),
    "activity": (r"\bactivit(?:e|es|y|ies)\b", r"\bintervention(?:s)?\b"),
    "output": (r"\bextrants?\b", r"\boutputs?\b", r"\blivrables?\b"),
    "result": (r"\br(?:e|é)sultats?\b", r"\boutcomes?\b"),
    "evaluation_finding": (r"\b(?:e|é)valuation\b", r"\bevaluation\b"),
    "diagnosis": (r"\bdiagnostic\b", r"\banalyse de la situation\b"),
}


def classify_evidence(item):
    source_type = item.get("source_type", "")
    if source_type == "hdx_hapi":
        return [{"type": "need", "method": "source_semantics", "confidence": 0.98}]
    if source_type == "fongim_structured":
        return [{"type": "activity", "method": "source_semantics", "confidence": 0.90}]
    text = fold(item.get("content", ""))
    labels = [name for name, patterns in EVIDENCE_TYPES.items()
              if any(re.search(p, text) for p in patterns)]
    return [{"type": name, "method": "chunk_cue", "confidence": 0.65}
            for name in labels]


def filter_hapi_rows(rows, *, region=None, cercle=None):
    """Defend against ignored API filters and homonymous admin labels."""
    return [row for row in rows
            if (not region or key(row.get("admin1_name")) == key(region))
            and (not cercle or key(row.get("admin2_name")) == key(cercle))]
