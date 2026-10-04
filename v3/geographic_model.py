"""Versioned Mali hierarchy, queried locally without embeddings or model calls.

INSTAT's January-2026 locality directory is the preferred *enumerated hierarchy*
for its 2023 framework. COD remains a separate boundary/P-code reference; a
same-name candidate never becomes an approved cross-release identity.
"""
from collections import Counter, defaultdict
from functools import lru_cache
import json
import re
import sqlite3
from threading import Lock

from source_wave import _fold, snapshot_path

PREFERRED_DATASET = "mli-instat-localities-2023"
LEVELS = ("country", "region", "cercle", "commune", "arrondissement", "locality")


class GeographyModel:
    def __init__(self, path):
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            self.releases = {r["id"]: dict(r) for r in db.execute("""
                select r.*,d.title,s.provider from mkh_source_releases r
                join mkh_datasets d on d.id=r.dataset_id
                join mkh_sources s on s.id=d.source_id""")}
            current = dict(db.execute("select id,current_release_id from mkh_datasets"))
            self.preferred = current[PREFERRED_DATASET]
            self.units = {r["id"]: dict(r) for r in db.execute("""
                select id,release_id,parent_id,level,name,boundary_version,
                valid_on,valid_to,original_record_id from mkh_geo_units""")}
            self.children = defaultdict(list)
            self.names = defaultdict(set)
            self.aliases = defaultdict(list)
            self.identifiers = defaultdict(dict)
            self.spans = {}
            for r in db.execute("select * from mkh_geo_names"):
                self.names[_fold(r["name"])].add(r["unit_id"])
                self.aliases[r["unit_id"]].append({"name": r["name"], "kind": r["kind"], "language": r["language"]})
            for r in db.execute("select * from mkh_geo_identifiers"):
                self.identifiers[r["unit_id"]][r["namespace"]] = r["identifier"]
            for r in db.execute("""select p.unit_id,s.* from mkh_population_observations p
                join mkh_evidence_spans s on s.id=p.span_id where p.sex='total'"""):
                self.spans[r["unit_id"]] = dict(r)
            self.crosswalks = [dict(r) for r in db.execute("select * from mkh_geo_crosswalks")]
            self.unresolved = [dict(r) for r in db.execute("select * from mkh_geo_unresolved")]
            for u in self.units.values():
                # Bamako is not counted as a région just because its source level is admin1.
                u["unit_type"] = "district" if u["level"] == "region" and _fold(u["name"]) == "bamako" else u["level"]
                self.names[_fold(u["name"])].add(u["id"])
                self.children[u["parent_id"]].append(u["id"])
                if u["parent_id"]:
                    parent = self.units.get(u["parent_id"])
                    if not parent or parent["release_id"] != u["release_id"]:
                        raise ValueError("Broken or cross-release geographic parent")
                self.path(u["id"])  # Reject cycles rather than hang on an invalid hierarchy.
            self.max_name_words = max(len(n.split()) for n in self.names)
        finally:
            db.close()

    def path(self, uid):
        path, seen = [], set()
        while uid:
            if uid in seen:
                raise ValueError("Cyclic geographic hierarchy")
            seen.add(uid)
            u = self.units[uid]
            path.append({"id": uid, "name": u["name"], "level": u["level"], "unit_type": u.get("unit_type", u["level"])})
            uid = u["parent_id"]
        return list(reversed(path))

    def describe(self, uid):
        u = self.units[uid]
        r = self.releases[u["release_id"]]
        return {**u, "path": self.path(uid), "aliases": self.aliases[uid],
                "identifiers": self.identifiers[uid], "version": r["upstream_version"],
                "source_url": r["source_url"], "locator": self.spans.get(uid, {}).get("locator", u["original_record_id"])}

    def lookup(self, name, level=None, release=None):
        # No fuzzy match and no collapsing of homonyms.
        ids = self.names.get(_fold(name), set())
        return sorted((self.describe(uid) for uid in ids
                       if (not level or self.units[uid]["level"] == level)
                       and (not release or self.units[uid]["release_id"] == release)),
                      key=lambda u: (u["release_id"] != self.preferred, u["level"], [p["name"] for p in u["path"]], u["id"]))

    @lru_cache(maxsize=1)
    def summary(self):
        releases = []
        for rid, r in self.releases.items():
            counts = Counter(u["unit_type"] for u in self.units.values() if u["release_id"] == rid)
            if not counts or r["dataset_id"] not in {PREFERRED_DATASET, "mli-cod-ab"}:
                continue
            quality = json.loads(r["quality_json"])
            releases.append({"release_id": rid, "dataset_id": r["dataset_id"],
                "title": r["title"], "version": r["upstream_version"],
                "preferred_hierarchy": rid == self.preferred,
                "counts": dict(counts), "count_basis": "enumerated stored source records, distinct source identities",
                "publication_month": quality.get("publication_month"),
                "source_url": r["source_url"], "retrieved_at": r["retrieved_at"],
                "boundary_versions": sorted({u["boundary_version"] for u in self.units.values() if u["release_id"] == rid}),
                "quality": quality})
        return {"preferred_release_id": self.preferred, "releases": releases,
            "crosswalk_status_counts": dict(Counter(r["status"] for r in self.crosswalks)),
            "unresolved_count": len(self.unresolved),
            "unresolved_places": self.unresolved,
            "proposed_crosswalks": self.crosswalks,
            "limitations": ["The preferred hierarchy is the INSTAT 2023 framework published January 2026, not a claim that no later legal change exists.",
                "COD v03 has an extra Bamako admin2 representation; it is not an extra cercle in the INSTAT hierarchy.",
                "Only seven Bamako arrondissements are enumerated in the INSTAT directory; this is not a national arrondissement count.",
                "Historical releases and source identifiers are preserved. Proposed crosswalks are not approved identities.",
                "INSTAT reports 12,917 localities; 12,915 were parsed. Two missing/discrepant occurrences remain unresolved."]}

    def evidence(self, rid, ids=(), eid="E01"):
        r = self.releases[rid]
        pages = sorted({self.spans[uid]["page"] for uid in ids if uid in self.spans})
        if rid == self.preferred and not pages:
            pages = [6, 7, 9]
        locator = ("PDF pages " + ", ".join(map(str, pages))) if pages else "COD v03 admin0/admin1/admin2 source records"
        return {"evidence_id": eid, "source_type": "official_geography_registry",
            "source_family": "Mali geographic model", "document_title": r["title"],
            "organization": r["provider"], "version": r["upstream_version"],
            "release_id": rid, "record_id": rid if not ids else ids[0],
            "source_endpoint": r["source_url"], "retrieved_at": r["retrieved_at"],
            "page": pages[0] if pages else None, "section": locator, "locator": locator,
            "reference_period_start": r["reference_start"], "reference_period_end": r["reference_end"],
            "geographic_scope": "Mali — release-specific hierarchy",
            "content": json.dumps({"release": r["upstream_version"],
                "enumerated_counts": dict(Counter(u['unit_type'] for u in self.units.values() if u['release_id'] == rid)),
                "records": [self.describe(uid) for uid in ids],
                "unresolved_matches": self.unresolved if rid != self.preferred else [],
                "calculation": "Counts, child lists and unresolved cross-release matches are computed from the stored source records. INSTAT pages 6/7 describe the framework, not a printed national count table."}, ensure_ascii=False)}

    def answer(self, question, language="English"):
        q = _fold(question)
        fr = language == "French"
        summary = self.summary()
        preferred = next(r for r in summary["releases"] if r["release_id"] == self.preferred)
        counts = preferred["counts"]
        summary_text = (f"Dans le référentiel INSTAT **2023**, publié en **janvier 2026**, le Mali comprend **{counts['region']} régions et un district (Bamako), {counts['cercle']} cercles et {counts['commune']} communes**. [E01]"
            if fr else f"Under the INSTAT **2023 framework**, published in **January 2026**, Mali has **{counts['region']} regions plus one district (Bamako), {counts['cercle']} cercles and {counts['commune']} communes**. [E01]")
        caveat = ("La hiérarchie de référence est Pays → Région → Cercle → Commune → Localité. Bamako suit un parcours distinct : Pays → District → Arrondissement → Localité. Les sept arrondissements présents concernent Bamako seulement. "
                  "Ce sont les unités de cette édition, pas une validation de toute modification juridique ultérieure. COD v03 contient 20 unités admin1 et 160 unités admin2 : Bamako apparaît aussi à admin2; ce n'est pas un 160e cercle dans le référentiel INSTAT. "
                  "Les correspondances entre versions restent proposées; elles ne prouvent pas des limites identiques. [E01, E02]"
            if fr else "The reference hierarchy is Country → Region → Cercle → Commune → Locality. Bamako follows Country → District → Arrondissement → Locality. The seven arrondissement rows cover Bamako only. "
                  "These are the units in this edition, not verification of every later legal amendment. COD v03 has 20 admin1 and 160 admin2 records: Bamako is also represented at admin2; this does not add a 160th cercle to the INSTAT hierarchy. "
                  "Cross-version matches remain proposals and do not establish identical boundaries. [E01, E02]")
        cod = next(rid for rid, r in self.releases.items() if r["dataset_id"] == "mli-cod-ab")
        ev = [self.evidence(self.preferred), self.evidence(cod, eid="E02")]
        # Longest exact toponym, optionally disambiguated by a named parent and level.
        words = q.split()
        # Inspect phrases in the question, rather than compile 13,000 regexes
        # on every request. Exact normalized aliases still preserve homonyms.
        names = sorted({" ".join(words[i:i+size]) for i in range(len(words))
            for size in range(1, min(self.max_name_words, len(words)-i)+1)
            if " ".join(words[i:i+size]) in self.names and len(" ".join(words[i:i+size])) > 2})
        names = [n for n in names if n not in {"mali", "same", "what", "which", "there", "here", "are", "the", "and", "how", "full", "parent", "path", "name", "region", "cercle", "commune", "locality"}]
        names = [n for n in names if not any(n != other and (' ' + n + ' ') in (' ' + other + ' ') for other in names)]
        level = None
        children_level = None
        if re.search(r"\b(communes|municipalities)\b", q) and re.search(r"\b(cercle|circle)\b", q):
            level, children_level = "cercle", "commune"
        elif re.search(r"\bcercles\b", q) and re.search(r"\b(region|regions)\b", q):
            level, children_level = "region", "cercle"
        elif re.search(r"\b(localities|localites|villages)\b", q) and re.search(r"\bcommune\b", q):
            level, children_level = "commune", "locality"
        else:
            for label in ("commune", "cercle", "locality", "localite", "region", "arrondissement"):
                if re.search(r"\b" + label + r"s?\b", q):
                    level = "locality" if label == "localite" else label
                    break
        candidates = []
        if names:
            target = max(names, key=len)
            candidates = self.lookup(target, level=level, release=self.preferred)
            # Named ancestors narrow scope only within this same release.
            parents = [n for n in names if n != target]
            if parents:
                candidates = [u for u in candidates if all(any(_fold(p['name']) == n for p in u['path'][:-1]) for n in parents)]
        national_summary = bool(re.search(r"\b(how many|combien|structure|structured|structuree|versions?|referentiel|reference|unresolved|disputed|conflicts?|conflits?)\b", q))
        national_summary = national_summary and (not names or names == ["mali"])
        if national_summary:
            answer = summary_text + "\n\n" + caveat
            if re.search(r"\b(list|name|quelles|liste|lister)\b", q) and re.search(r"\bregions\b", q) and not names:
                regions = sorted(u["name"] for u in self.units.values() if u["release_id"] == self.preferred and u["unit_type"] == "region")
                answer += "\n\n" + ", ".join(regions) + ". [E01]"
        elif not candidates:
            answer = ("Aucune correspondance exacte à ce niveau dans le référentiel sélectionné. Précisez le nom, le niveau et le parent; je ne devine pas l'identité. " if fr else
                "No exact match at that level in the selected reference. Please specify the name, level and parent; I will not guess its identity. ") + "\n\n" + caveat
        else:
            ids = []
            lines = []
            for u in candidates[:12]:
                ids.append(u["id"])
                path = " → ".join(p["name"] + " (" + p["unit_type"] + ")" for p in u["path"])
                lines.append("- " + path + ". [E01]")
                if re.search(r"\b(aliases|alias|spellings?|alternative|historical|historique|anciens?)\b", q):
                    variants = [a['name'] + ' (' + a['kind'] + ')' for a in u['aliases'] if _fold(a['name']) != _fold(u['name'])]
                    lines.append("  " + (", ".join(variants) if variants else "No separately recorded alternative name; no historical renaming is inferred.") + " [E01]")
                if children_level:
                    children = [self.describe(uid) for uid in self.children[u["id"]] if self.units[uid]["level"] == children_level]
                    ids.extend(c["id"] for c in children[:200])
                    label = (f"{len(children)} {children_level}(s) enregistrés" if fr else f"{len(children)} recorded {children_level}(s)")
                    lines.append("  " + label + ": " + ", ".join(c["name"] for c in sorted(children, key=lambda c:c['name'])[:200]) + ". [E01]")
                    if len(children) > 200:
                        lines.append("  " + ("Liste limitée aux 200 premières entrées." if fr else "List limited to the first 200 entries."))
            ev[0] = self.evidence(self.preferred, ids)
            answer = "\n".join(lines)
            if len(candidates) > 1:
                answer = ("Ce nom correspond à plusieurs identités distinctes; le parent et le niveau sont indispensables.\n\n" if fr else "This name matches distinct identities; parent and level are required.\n\n") + answer
            if len(candidates) > 12:
                answer += f"\n\nShowing 12 of {len(candidates)} matches; specify a parent to narrow the list."
            answer += "\n\n" + ("Référence : " if fr else "Reference: ") + preferred["title"] + ", " + preferred["version"] + ". [E01]\n\n" + caveat
        if re.search(r"\b(conflicts?|unresolved|disputed|conflits?|non resolus|versions?|historical|historique|aliases|alternative)\b", q):
            answer += (f"\n\n{summary['crosswalk_status_counts'].get('proposed',0)} proposed crosswalks; {summary['unresolved_count']} unresolved matches in the foundation. "
                "Alternative spellings are stored separately from canonical names; they are not automatically historical renamings. Historical releases remain separate. [E01, E02]")
            if re.search(r"\b(conflicts?|unresolved|disputed|conflits?|non resolus)\b", q):
                answer += "\n\n" + "\n".join("- " + r['raw_name'] + " (" + r['level'] + "; source parent: " + str(r['parent_name']) + "): " + r['reason'] + ". [E02]" for r in self.unresolved)
        return {"answer": answer, "evidence": ev, "family_counts": {"geographic_model": len(ev)},
                "geography_summary": summary, "geography": {"assumption": "INSTAT 2023 framework; January 2026 edition"}}


@lru_cache(maxsize=1)
def _load_geographic_model():
    return GeographyModel(snapshot_path())


_model_lock = Lock()

def geographic_model():
    # lru_cache alone can execute its cold initializer concurrently. Share one
    # hierarchy load across chat and packaged-evidence workers on small hosts.
    with _model_lock:
        return _load_geographic_model()


def simple_geography_question(question):
    q = _fold(question)
    if re.search(r"\b(in there|over there|here|that place|this place|la bas|cette zone)\b", q) or re.match(r"^(and|et)\b", q) or q.endswith("belong there"):
        return False
    # Contextual analytics always use fresh research; presence is not geography.
    if re.search(r"\b(needs?|besoins?|population|people|habitants?|projects?|projets?|actors?|acteurs?|fund\w*|financ\w*|coverage|couverture|sectors?|secteurs?|displace\w*|deplace\w*|food|security|sante|health|priorit\w*|risk|risque|conflict|conflit|delivery|reach|livraison)\b", q):
        return False
    place_term = re.search(r"\b(regions?|cercles?|communes?|municipalities|municipality|administrativ\w*|hierarch\w*|parent|p codes?|pcode|localit\w*|geograph\w*|homonyms?|homonymes?)\b", q)
    lookup_intent = re.search(r"\b(how many|combien|which|what|quels?|quelles?|belong|appartien\w*|structure\w*|hierarch\w*|path|parent|same|identical\w*|homonym\w*|list|liste\w*|version\w*|reference|referentiel|unresolved|disputed|conflicts?|conflits?|aliases|alternative|historical|historique|pcode)\b", q)
    return bool(place_term and lookup_intent)


def canonical_geography_evidence(question):
    """Bounded reference context for joined analysis; never remap source geography."""
    model = geographic_model()
    evidence = model.evidence(model.preferred)
    evidence['content'] += " Source-reported places from operational datasets must retain their own framework. A matching name is not an approved identity crosswalk; do not allocate needs or delivery using this hierarchy alone."
    return [evidence]
