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
    # Explicit joined evidence families have no ambiguous planning decision.
    # Keep the conservative legacy needs/operational sources as well as the
    # named packaged families; this shortcut never answers the factual question.
    needs = bool(re.search(r"\b(?:needs?|besoins?|people in need)\b", q))
    joined_families = bool(re.search(r"\b(?:3w|dtm|fts|world bank|banque mondiale|iati)\b", q))
    if needs and joined_families and re.search(r"\b(?:compare|align|alignment|with|avec|comparer|coverage|couverture)\b", q):
        return {"government_docs": bool(national), "hnrp_docs": True,
                "hapi": True, "fongim": bool(operational or re.search(r"\b(?:3w|actors|acteurs)\b",q))}
    markers = {
        "government_docs": [r"\bsnedd\b", r"\bmali kura\b", r"\bvision mali 2063\b",
                            r"\bprojets structurants prioritaires\b", r"\bpriority.project portfolio\b"],
        "hnrp_docs": [r"\bhnrp\b", r"\bunicef\b",
                      r"\bhumanitarian action for children\b",
                      r"\bhumanitarian situation report\b",
                      r"\bhumanitarian (?:response )?plan\b",
                      r"\bresponse plan\b",
                      r"\bplan de reponse\b", r"\bplan humanitaire\b"],
        "hapi": [r"\bhapi\b", r"\bhdx\b"],
        "fongim": [r"\bfongim\b"],
    }
    selected = {family: any(re.search(pattern, q) for pattern in patterns)
                for family, patterns in markers.items()}
    if not any(selected.values()):
        # These families are read independently by the packaged retrievers.
        # A bounded question about their own records needs neither a model
        # planner nor unrelated live HAPI/document searches. Broad joins still
        # fall through to the planner; this rule never supplies an answer.
        packaged = re.search(r"\b(?:dtm|echo hip)\b", q)
        wider = re.search(
            r"\b(?:needs?|besoins?|priorit\w*|strateg\w*|actors?|acteurs?|"
            r"projects?|projets?|fongim|hnrp|hapi|government|gouvernement|"
            r"national|coverage|couverture|alignment|alignement|nexus)\b", q)
        if packaged and not wider:
            return selected
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


def packaged_source_names(question, source_plan, planner_output=None):
    names = {'foundation', 'operational', 'analytical', 'project_learning',
             'eu', 'geographic_model'}
    government_only = source_plan == {
        'government_docs': True, 'hnrp_docs': False, 'hapi': False, 'fongim': False}
    explicit = (planner_output or {}).get('method') == 'explicit_source_rules'
    other_family = re.search(
        r'\b(?:3w|dtm|iom|ocha|fts|hpc|hdx|hapi|iati|ieg|world bank|banque mondiale|'
        r'cadre harmonis\w*|echo|eu|ue|european|europeenne?|unicef|fongim)\b',
        _normal(question))
    if government_only and explicit and not other_family:
        # Generic "projects" in a named government strategy do not request
        # World Bank country profiles or unrelated national FTS records.
        names -= {'operational', 'analytical', 'project_learning', 'eu'}
    return names
