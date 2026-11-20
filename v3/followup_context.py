"""Bounded query-slot carry-over. History is context, never factual evidence."""
import re
from query_router import classify
from source_wave import _fold


def previous_question(messages):
    previous = None
    for message in messages[-10:]:
        value = message.get('standalone_question') or (
            message.get('content') if message.get('role') == 'user' else None)
        if isinstance(value, str) and value.strip():
            if classify(value)['path'] in {'conversational', 'conversation_only'}:
                continue
            # Any new substantive question replaces the preceding topic.
            previous = value[:5000]
    return previous


def cited_assignment_in_history(assignment, messages):
    """Find citation-bearing replies to the active assignment in guest or saved history."""
    for user, assistant in zip(messages, messages[1:]):
        if user["role"] != "user" or assistant["role"] != "assistant":
            continue
        resolved = assistant.get("standalone_question") or user.get("standalone_question") or user["content"]
        if resolved == assignment and re.search(r"\[E\d{2,}", assistant["content"]):
            return True
    return False


_COMPARISON = re.compile(r"\b(?:compar\w*|versus|vergleich\w*)\b")
_YEAR = re.compile(r"(?<!\w)(?:19|20)\d{2}(?!\w)")
_COMPARISON_YEAR_EDIT = re.compile(
    r"(?:same comparison (?:in|for)|(?:la )?même comparaison (?:en|pour)|and in|et en) "
    r"((?:19|20)\d{2})[.!? ]*", re.I
)


def ambiguous_comparison_year(question, previous):
    """A bare year may replace either operand or add a third one."""
    return bool(previous and _COMPARISON.search(_fold(previous))
                and _COMPARISON_YEAR_EDIT.fullmatch(question.strip())
                and len(set(_YEAR.findall(previous))) > 1)


def edit_comparison(question, previous):
    """Apply an unambiguous operand edit without changing the other criteria."""
    if not previous or not _COMPARISON.search(_fold(previous)):
        return None
    request = question.strip().rstrip(".?!").strip()
    replacement = re.fullmatch(
        r"(?:now )?(?:replace|change|remplacez?|remplacer) (?:only |uniquement )?"
        r"(?P<old>[\wÀ-ÿ’' -]{1,60}?) (?:with|to|par) (?P<new>[\wÀ-ÿ’' -]{1,60})", request, re.I
    )
    if replacement:
        old, new = replacement["old"].strip(), replacement["new"].strip()
    else:
        substitute = re.fullmatch(
            r"(?:now )?(?:use|utilisez|utilise) (?P<new>[\wÀ-ÿ’' -]{1,60}?) "
            r"(?:instead of|au lieu de) (?P<old>[\wÀ-ÿ’' -]{1,60})", request, re.I
        )
        if substitute:
            old, new = substitute["old"].strip(), substitute["new"].strip()
        else:
            year = _COMPARISON_YEAR_EDIT.fullmatch(request)
            old_years = _YEAR.findall(previous)
            if not year or len(old_years) != 1:
                return None
            old, new = old_years[0], year[1]

    if _fold(old) == _fold(new):
        return None
    if re.fullmatch(r"(?:19|20)\d{2}", old):
        if (not re.fullmatch(r"(?:19|20)\d{2}", new)
                or re.search(r"\bHMLI\d{2}\b", previous, re.I)):
            return None
        operand = rf"(?<![\w/–—-]){old}(?![\w/–—-])"
        # A bare instruction to change one endpoint must not edit a date range.
        if re.search(rf"\b{old}\s*[-–—/]\s*\d|\d\s*[-–—/]\s*{old}\b", previous):
            return None
    else:
        from geographic_model import geographic_model

        model = geographic_model()
        if not (model.retrieval_place_names(old) == [_fold(old)]
                and model.retrieval_place_names(new) == [_fold(new)]):
            return None
        operand = rf"(?<!\w){re.escape(old)}(?!\w)"
    matches = list(re.finditer(operand, previous, re.I))
    if len(matches) != 1 or re.search(rf"(?<!\w){re.escape(new)}(?!\w)", previous, re.I):
        return None
    start, end = matches[0].span()
    return previous[:start] + new + previous[end:]


def resolve_exact_followup(question, previous, messages, *, assignment_edit=False):
    """Return a complete, executable assignment for a bounded edit."""
    revised = edit_comparison(question, previous)
    if revised:
        return {"standalone_question": revised, "method": "comparison_operand_edit"}
    if assignment_edit:
        return None

    from country_foundation import resolve_country_followup
    from geography_context import resolve_count_followup, resolve_hierarchy_followup
    from registry_observations import resolve_year_followup
    from registry_research import resolve_year_followup as resolve_evidence_year

    for method, resolver, arguments in (
        ("registry_evidence_reference_year", resolve_evidence_year, (question, previous)),
        ("registry_reference_year", resolve_year_followup, (question, previous)),
        ("structured_country_fact", resolve_country_followup, (question, messages)),
        ("structured_geographic_count", resolve_count_followup, (question, messages)),
        ("structured_geographic_hierarchy", resolve_hierarchy_followup, (question, messages)),
    ):
        revised = resolver(*arguments)
        if revised:
            return {"standalone_question": revised, "method": method}
    slots = resolve_slots(question, messages)
    if slots:
        return slots
    revised = resolve_evidence_year(question, previous, evidence_only=False)
    if revised:
        return {"standalone_question": revised, "method": "registry_research_reference_year"}
    return None


def metric(question):
    q = _fold(question)
    # Joined questions and multiple indicators need the semantic resolver.
    if re.search(r'\b(compare|versus|vs|beneficiar\w*|staff|personnel|fund\w*|fts|finance\w*|'
                 r'requirements?|target\w*|cible\w*|projects?|projets?|actors?|acteurs?|'
                 r'organisations?|organizations?|livraison|delivery|interventions?)\b', q):
        return None
    if re.search(r'\bpopulation\b', q):
        if re.search(r'\b(dtm|idps?|pdi|displac\w*|deplac\w*|needs?|besoins?)\b', q):
            return None
        return 'population'
    if re.search(r'\b(dtm|idps?|pdi)\b', q):
        return 'displacement'
    if re.search(r'\b(hapi|people in need|personnes dans le besoin)\b', q):
        return 'needs'
    return None


def resolve_slots(question, messages):
    """Exact slot operations only; ambiguous requests keep semantic resolution."""
    projects = resolve_project_end_dates(question, messages)
    if projects:
        return projects
    q = _fold(question)
    sex = re.fullmatch(r'(?:what about|and|et|et les|qu en est il des) '
                       r'(women|female|men|male|femmes|hommes)', q)
    year = re.fullmatch(r'(?:and in|what about|et en|et pour) ((?:19|20)\d{2})', q)
    level = re.fullmatch(r'(?:and at|what about at|et au) (region|cercle|commune) '
                        r'(?:level|niveau)', q)
    if not any((sex, year, level)):
        return None
    base = previous_question(messages)
    kind = metric(base or '')
    if not base or not kind:
        return None
    if sex:
        target = 'female' if sex[1] in {'women', 'female', 'femmes'} else 'male'
        # Remove a previous resolver suffix before changing the same slot.
        base = re.sub(r'; report the (?:female|male) sex-disaggregated observations '
                      r'if supplied, otherwise state the missing breakdown\.?$', '', base)
        if kind == 'population':
            if re.search(r'\b(?:female|women|feminine|femmes)\b', _fold(base)) and re.search(
                    r'\b(?:male|men|masculine|hommes)\b', _fold(base)):
                return None
            base = re.sub(r'\b(?:female|male|women|men)\s+(?=population\b)', '', base,
                          flags=re.I)
            base = re.sub(r'\bpopulation\s+(?:féminine|masculine)\b', 'population', base,
                          flags=re.I)
            if re.search(r'\b(?:female|male|women|men|feminine|masculine|femmes|hommes)\b', _fold(base)):
                return None
            rewritten = re.sub(r'\bpopulation\b', target + ' population', base,
                               count=1, flags=re.I)
        else:
            if re.search(r'\b(?:female|male|women|men|femmes|hommes)\b', _fold(base)):
                return None
            rewritten = base.rstrip(' ?') + '; report the ' + target + (
                ' sex-disaggregated observations if supplied, otherwise state the missing breakdown.')
    elif year:
        # Replacing a year in a round, snapshot date, or interval would drift its scope.
        years = set(re.findall(r'\b(?:19|20)\d{2}\b', base))
        if kind != 'population' or len(years) != 1 or re.search(
                r'\b(?:19|20)\d{2}[-/–]|\bround\b', base, re.I):
            return None
        rewritten = re.sub(r'\b' + next(iter(years)) + r'\b', year[1], base)
    else:
        if kind != 'population':
            return None
        old = re.findall(r'\b(region|région|cercle|commune)\b', base, re.I)
        if len(old) != 1:
            return None
        # Only an existing, uniquely resolved place can change administrative level.
        from geographic_model import geographic_model
        model = geographic_model()
        words = _fold(base).split()
        places = {name for name in model.names if name != 'mali' and
                  (' ' + name + ' ') in (' ' + ' '.join(words) + ' ')}
        places = {name for name in places if not any(name != other and
                  (' ' + name + ' ') in (' ' + other + ' ') for other in places)}
        if len(places) != 1 or len(model.lookup(next(iter(places)), level[1], model.preferred)) != 1:
            return None
        rewritten = re.sub(r'\b(region|région|cercle|commune)\b', level[1], base,
                           count=1, flags=re.I)
    return {'standalone_question': rewritten, 'method': 'structured_query_slots',
            'state': {'context_only': True, 'metric': kind,
                      'time_period': re.findall(r'\b(?:19|20)\d{2}\b', rewritten),
                      'last_question': rewritten}}


def resolve_project_end_dates(question, messages):
    """Carry source-qualified roster IDs for a narrowly recognised date filter.

    Dates/status from prior answers never enter the standalone query. Only
    identity context survives; the engine freshly retrieves every record.
    """
    q = _fold(question)
    # ``q`` is folded for language matching, so ISO punctuation appears as spaces.
    # The original question remains authoritative for date validation below.
    iso_date = r'(?:19|20)\d{2} \d{2} \d{2}'
    english_window = rf'(?:between {iso_date} and {iso_date}|from {iso_date} to {iso_date})'
    french_window = rf'(?:entre {iso_date} et {iso_date}|du {iso_date} au {iso_date})'
    english = re.fullmatch(r'which of (?:those|these) '
                          r'(?:(?P<english_source>fongim|world bank|eu) )?projects '
                          r'(?:have (?:a )?(?:reported )?(?:end|closing) dates?|end|ended|are ending|were ending|close|closed|are closing|were closing) '
                          rf'(?:(?:in )?(?P<english_period>(?:19|20)\d{{2}}|this year|next year|last year|this week|next week|last week|this month|next month|last month|(?:the )?next \d{{1,2}} (?:days?|weeks?|months?))|'
                          rf'(?P<english_window>{english_window}))', q)
    english_them = re.fullmatch(r'which of them '
                               r'(?:have (?:a )?(?:reported )?(?:end|closing) dates?|end|ended|are ending|were ending|close|closed|are closing|were closing) '
                               rf'(?:(?:in )?(?P<english_period>(?:19|20)\d{{2}}|this year|next year|last year|this week|next week|last week|this month|next month|last month|(?:the )?next \d{{1,2}} (?:days?|weeks?|months?))|'
                               rf'(?P<english_window>{english_window}))', q)
    french = re.fullmatch(r'(?:lesquels de ces projets'
                         r'(?: (?P<french_source>fongim|de la banque mondiale|de l ue|ue))?'
                         r'|lesquels d entre eux|lesquels parmi eux) '
                         r'ont une date de (?:fin|cloture) '
                         rf'(?:en (?P<french_period>(?:19|20)\d{{2}})|(?P<french_this_year>cette annee)|(?P<french_next_year>l annee prochaine|l an prochain)|(?P<french_last_year>l annee derniere|l an dernier)|(?P<french_this_week>cette semaine)|(?P<french_next_week>(?:la )?semaine prochaine)|(?P<french_last_week>(?:la )?semaine derniere)|(?P<french_this_month>ce mois ci)|(?P<french_next_month>le mois prochain)|(?P<french_last_month>le mois dernier)|dans les \d{{1,2}} prochains? (?:jours?|semaines?|mois)|'
                         rf'(?P<french_window>{french_window}))', q)
    matched = english or english_them or french
    if not matched:
        return None
    source_labels = {
        'fongim': 'FONGIM', 'world bank': 'World Bank',
        'de la banque mondiale': 'World Bank', 'eu': 'EU IATI',
        'ue': 'EU IATI', 'de l ue': 'EU IATI',
    }
    requested_source = source_labels.get(
        (matched.groupdict().get('english_source') or
         matched.groupdict().get('french_source') or ''))
    from project_dates import calendar_end_year, reported_end_window
    window = reported_end_window(question)
    year = calendar_end_year(question)
    matched_window = (matched.groupdict().get('english_window') or
                      matched.groupdict().get('french_window'))
    if matched_window and not window:
        return None
    if not window and year is None:
        return None
    latest = next((m.get('content','') for m in reversed(messages)
                   if m.get('role') == 'assistant' and m.get('content')), '')
    # A truncated long roster cannot establish its complete lookup set.
    if not latest or len(latest) >= 5900:
        return None
    empty_markers = {
        'Selected source identifiers for this filter: none.': (
            'The current project subset is empty, so there are no projects to filter by another '
            'reported end date. Start a new filter from the original project list if you want to '
            'change the period.\n\nSelected source identifiers for this filter: none.'),
        'Identifiants source sélectionnés par ce filtre : aucun.': (
            'Le sous-ensemble actuel de projets est vide ; aucun projet ne peut donc être filtré '
            'selon une autre date de fin déclarée. Lancez un nouveau filtre à partir de la liste '
            'initiale des projets si vous souhaitez changer la période.\n\n'
            'Identifiants source sélectionnés par ce filtre : aucun.'),
    }
    marker = next((marker for marker in empty_markers if marker in latest.splitlines()), None)
    if marker:
        return {'standalone_question': question, 'method': 'structured_empty_project_subset',
                'direct_answer': empty_markers[marker],
                'state': {'context_only': True, 'metric': 'project_reported_end_date',
                          'lookup_ids': [], 'last_question': question}}
    from project_references import fongim_roster_ids
    fongim = fongim_roster_ids(latest)
    bank = tuple(sorted(set(re.findall(r'\bP\d{6}\b', latest.upper()))))
    eu = tuple(sorted(set(x.rstrip('.:') for x in re.findall(
        r'\bXI-IATI-EC_(?:INTPA|ECHO)-[^\s*;,\]\)]+', latest))))
    families = [(source, ids) for source, ids in
                [('FONGIM',fongim),('World Bank',bank),('EU IATI',eu)] if ids]
    if requested_source:
        families = [(source, ids) for source, ids in families
                    if source == requested_source]
    if len(families) != 1 or len(families[0][1]) > 12:
        return None
    source, ids = families[0]
    active_only = False
    # A verified date table defines the narrowed set. Identifiers in the
    # excluded-record note remain attribution, not members of that set.
    if source in ('FONGIM', 'World Bank', 'EU IATI'):
        lines = latest.splitlines()
        headers = [i for i,line in enumerate(lines) if line.lstrip().startswith('|')
                   and _fold(line.split('|')[1]) in ('source identifier', 'identifiant source')
                   and re.search(r'\b(reported end closing|date declaree)\b', _fold(line))]
        if headers:
            if len(headers) != 1:
                return None
            selected = []
            for line in lines[headers[0]+1:]:
                if not line.lstrip().startswith('|'):
                    break
                identifier = line.split('|')[1].strip()
                if source == 'FONGIM':
                    match = re.fullmatch(r'FONGIM project ID ([1-9]\d*)', identifier)
                    if match:
                        selected.append(int(match[1]))
                    continue
                pattern = r'P\d{6}' if source == 'World Bank' else r'XI-IATI-EC_(?:INTPA|ECHO)-[^\s*;,\]\)]+'
                if re.fullmatch(pattern, identifier):
                    selected.append(identifier)
            ids = tuple(sorted(set(selected)))
            if not ids or not set(ids).issubset(families[0][1]):
                return None
            # The deterministic filter note describes the selection operation,
            # not a project's status. Carry that query constraint only from a
            # recognised date table; every status must still be retrieved afresh.
            active_notes = (
                'Reported dates and status do not establish actual completion or current delivery. '
                'Filter uses reported active labels; missing or other statuses are not classified as active.',
                'Dates et statuts déclarés, sans preuve d’achèvement réel ou de livraison actuelle. '
                'Filtre sur les statuts actifs déclarés ; les statuts absents ou différents ne sont pas classés actifs.',
            )
            active_only = any(line.startswith(active_notes) for line in lines[headers[0]+1:]
                              if not line.lstrip().startswith('|'))
    labels = ', '.join(map(str,ids))
    if window:
        start, end = window
        date_filter = f'entre {start} et {end}' if french else f'between {start} and {end}'
        time_period = list(window)
    else:
        date_filter = f'en {year}' if french else f'in {year}'
        time_period = [str(year)]
    records_fr = 'dossiers actifs' if active_only else 'dossiers'
    records_en = 'active records' if active_only else 'records'
    rewritten = (f'Pour {source}, identifiants de projets {labels}, quels {records_fr} ont une date de fin déclarée {date_filter} ?'
                 if french else f'For {source} project IDs {labels}, which {records_en} have a reported end date {date_filter}?')
    return {'standalone_question':rewritten, 'method':'structured_query_slots',
            'state':{'context_only':True, 'metric':'project_reported_end_date',
                     'source':source,'lookup_ids':list(ids),'active_only':active_only,
                     'time_period':time_period,'last_question':rewritten}}
