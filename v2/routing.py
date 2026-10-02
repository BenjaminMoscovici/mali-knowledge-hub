"""Conservative source routing for questions naming an unambiguous source."""

import re
import unicodedata


def _normal(text):
    value = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in value if not unicodedata.combining(c))


def explicit_source_plan(question):
    q = _normal(question)
    national = re.search(r"\b(?:national strateg\w*|government priorit\w*|"
                         r"national priorit\w*|strategie nationale|"
                         r"priorites nationales)\b", q)
    operational = re.search(r"\b(?:projects?|projets?|interventions?|"
                            r"ngos?|ongs?|actors?|acteurs?)\b", q)
    if national and operational:
        needs = bool(re.search(r"\b(?:needs?|besoins?|coverage|couverture)\b", q))
        return {"government_docs": True, "hnrp_docs": needs,
                "hapi": needs, "fongim": True}
    markers = {
        "government_docs": [r"\bsnedd\b", r"\bmali kura\b", r"\bvision mali 2063\b",
                            r"\bprojets structurants prioritaires\b", r"\bpriority.project portfolio\b"],
        "hnrp_docs": [r"\bhnrp\b", r"\bhumanitarian (?:response )?plan\b",
                      r"\bresponse plan\b",
                      r"\bplan de reponse\b", r"\bplan humanitaire\b"],
        "hapi": [r"\bhapi\b", r"\bhdx\b"],
        "fongim": [r"\bfongim\b"],
    }
    selected = {family: any(re.search(pattern, q) for pattern in patterns)
                for family, patterns in markers.items()}
    if not any(selected.values()):
        return None
    # A needs × intervention question requires actual needs evidence, even if
    # the user names only FONGIM. It is not answerable from project presence.
    if selected["fongim"] and re.search(
        r"\b(?:besoins?|needs?|covered|coverage|couverts?|couvrir)\b", q
    ):
        selected["hnrp_docs"] = True
        selected["hapi"] = True
        if re.search(r"\b(?:national priorit\w*|national strateg\w*|"
                     r"government priorit\w*|priorites nationales|"
                     r"strategie nationale|snedd|mali kura)\b", q):
            selected["government_docs"] = True
        return selected
    # Generic relationship/comparison terms may imply additional unnamed sources.
    broad = (r"\b(?:align|alignment|responding|response to|compare|comparison|"
             r"connect|relation|link|lien|rapport|comparer|alignement|"
             r"articul|coherence|coherence|situation|who is responding)\b")
    if re.search(broad, q) and sum(selected.values()) < 2:
        return None
    # A named family plus generic needs, actors or priorities can still be a join.
    if selected["government_docs"] and re.search(r"\b(?:humanitarian needs|besoins humanitaires|ngo|ong)\b", q):
        return None
    if selected["fongim"] and re.search(r"\b(?:humanitarian needs|besoins humanitaires|national priorit|priorites nationales)\b", q):
        return None
    return selected
