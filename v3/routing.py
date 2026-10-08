"""Conservative source routing for questions naming an unambiguous source."""

import re
import unicodedata


def _normal(text):
    value = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in value if not unicodedata.combining(c))


def _bounded_fts(question):
    """A comparison of financial fields is not necessarily a source join."""
    q = _normal(question)
    if not re.search(r"\bfts\b", q) or not re.search(
        r"\b(?:fund\w*|financ\w*|requirements?|exigences?|percent\w*|"
        r"pourcent\w*|currency|currencies|devise\w*|snapshot|montants?)\b", q
    ):
        return False
    # Subnational attribution, causes, operational delivery, and other source
    # families remain ordinary research questions. This shortcut only selects
    # retrieval; the dated FTS records still supply every factual answer.
    wider = re.search(
        r"\b(?:needs?|besoins?|priorit\w*|strateg\w*|actors?|acteurs?|"
        r"donors?|bailleurs?|projects?|projets?|interventions?|"
        r"food|aliment\w*|hunger|faim|health|sante|nutrition|education|"
        r"protection|peace|paix|agricult\w*|water|eau|wash|"
        r"delivery|reach\w*|beneficiar\w*|beneficiair\w*|results?|resultats?|"
        r"women|femmes|children|enfants|sectors?|secteurs?|"
        r"regions?|regional\w*|cercles?|communes?|villages?|local\w*|subnational|"
        r"coverage|couverture|alignment|alignement|nexus|"
        r"why|pourquoi|explain\w*|expliqu\w*|causes?|"
        r"fongim|hnrp|hrp|hpc|hapi|hdx|dtm|iom|3w|iati|ieg|"
        r"world bank|banque mondiale|cadre harmonis\w*|ipc|"
        r"echo|eu|ue|europe\w*|unicef|government|gouvernement|"
        r"snedd|mali kura|vision mali)\b", q)
    if wider:
        return False
    # An unqualified place name can still request local allocation. Use only
    # exact names in the existing registry to decline the shortcut; a name
    # match here never resolves a place or joins geographical vintages.
    from geographic_model import geographic_model
    model = geographic_model()
    words = re.findall(r"\w+", q)
    for size in range(1, model.max_name_words + 1):
        for start in range(len(words) - size + 1):
            name = ' '.join(words[start:start + size])
            if name in {'mali', 'a', 'au', 'aux', 'de', 'du', 'des', 'en',
                        'et', 'la', 'le', 'les', 'and', 'for', 'in', 'of',
                        'on', 'the', 'to', 'with'}:
                continue
            if any(model.units[uid]['level'] != 'country'
                   for uid in model.names.get(name, ())):
                return False
    return True

def explicit_source_plan(question):
    q = _normal(question)
    if _bounded_fts(question) or _bounded_project_learning(question) or _bounded_project_dates(question):
        return {family: False for family in
                ("government_docs", "hnrp_docs", "hapi", "fongim")}
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


def bounded_fts_source_names(question, source_plan, planner_output):
    if ((planner_output or {}).get('method') == 'explicit_source_rules'
            and source_plan is not None and not any(source_plan.values())
            and _bounded_fts(question)):
        return {'analytical', 'geographic_model'}
    return None


def _bounded_project_learning(question):
    """Exact study lookups can use project-ID evidence without national context."""
    q = _normal(question)
    ids = set(re.findall(r'\bp\d{6}\b', q))
    if not (1 <= len(ids) <= 2) or not re.search(
        r'\b(?:evaluat\w*|lessons?|learning|worked|failed|enseign\w*|appris)\b', q
    ):
        return False
    if len(ids) < 2 and re.search(r'\b(?:compare|comparison|comparer|comparaison|contrast|versus|vs|relat\w*|relier)\b', q):
        return False
    # Wider decisions still need the ordinary joined research. A project ID
    # never establishes a link to another provider or a subnational place.
    if re.search(r'\b(?:needs?|besoins?|priorit\w*|strateg\w*|plans?|'
                 r'coverage|couverture|delivery|reach\w*|beneficiar\w*|beneficiair\w*|'
                 r'fund\w*|financ\w*|budgets?|donors?|bailleurs?|actors?|acteurs?|'
                 r'implement\w*|successor\w*|continuity|continuite|'
                 r'apply|adapt\w*|transfer\w*|replic\w*|current|actuel\w*|'
                 r'local\w*|subnational|regions?|regional\w*|cercles?|communes?|villages?|'
                 r'fongim|fts|hnrp|hrp|hapi|hpc|hdx|dtm|iom|3w|'
                 r'echo|eu|ue|europe\w*|unicef|government|gouvernement|'
                 r'usaid|afd|giz|wfp|pam|who|oms|undp|pnud|afdb|bad|'
                 r'other sources|autres sources|all sources|toutes les sources|'
                 r'snedd|mali kura|vision mali|cadre harmonis\w*|ipc)\b', q):
        return False
    from geographic_model import geographic_model
    model = geographic_model()
    words = re.findall(r'\w+', q)
    for size in range(1, model.max_name_words + 1):
        for start in range(len(words) - size + 1):
            name = ' '.join(words[start:start + size])
            if name in {'mali', 'a', 'au', 'aux', 'de', 'du', 'des', 'en',
                        'et', 'la', 'le', 'les', 'and', 'for', 'in', 'of',
                        'on', 'the', 'to', 'with'}:
                continue
            if any(model.units[uid]['level'] != 'country'
                   for uid in model.names.get(name, ())):
                return False
    return True


def bounded_project_learning_source_names(question, source_plan, planner_output):
    if ((planner_output or {}).get('method') == 'explicit_source_rules'
            and source_plan is not None and not any(source_plan.values())
            and _bounded_project_learning(question)):
        return {'project_learning', 'geographic_model'}
    return None


def _bounded_project_dates(question):
    """Single-provider country-level date screening, not continuity analysis."""
    q=_normal(question)
    from project_dates import calendar_end_year, reported_end_window
    if calendar_end_year(question) is None and reported_end_window(question) is None:
        return None
    providers=[name for name,pattern in [('project_learning',r'\b(world bank|banque mondiale)\b'),
        ('eu',r'\b(eu|ue|union europeenne|european union|intpa|echo)\b')] if re.search(pattern,q)]
    if len(providers)!=1:
        return None
    if re.search(r'\b(compare\w*|compar\w*|why|pourquoi|explain\w*|expliqu\w*|'
        r'needs?|besoins?|priorit\w*|strateg\w*|plans?|fund\w*|financ\w*|budget\w*|'
        r'donors?|bailleurs?|actors?|acteurs?|who|qui|implement\w*|agencies|agences|'
        r'reach\w*|delivery|livraison|coverage|couverture|results?|resultats?|impact|'
        r'evaluat\w*|learning|lessons?|enseign\w*|successor\w*|successeur\w*|'
        r'continuity|continuit\w*|handover|sequenc\w*|risks?|risques?|'
        r'sectors?|secteurs?|health|sante|nutrition|education|wash|water|eau|'
        r'food|aliment\w*|agricult\w*|protection|peace|paix|'
        r'regions?|regional\w*|cercles?|communes?|villages?|local\w*|subnational|'
        r'fongim|fts|hnrp|hrp|hapi|hdx|dtm|iom|3w|iati|ieg|'
        r'usaid|afd|giz|wfp|pam|who|oms|undp|pnud|afdb|bad|unicef|'
        r'other sources|autres sources|all sources|toutes les sources|'
        r'government|gouvernement|snedd|vision mali|cadre harmonis\w*|ipc)\b',q):
        return None
    from geographic_model import geographic_model
    if geographic_model().retrieval_place_names(question):
        return None
    return providers[0]


def bounded_project_date_source_names(question, source_plan, planner_output):
    if ((planner_output or {}).get('method')=='explicit_source_rules'
            and source_plan is not None and not any(source_plan.values())):
        source=_bounded_project_dates(question)
        if source:
            return {source,'geographic_model'}
    return None
