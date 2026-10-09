"""Bounded query-slot carry-over. History is context, never factual evidence."""
import re
from datetime import datetime, timezone
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
    english = re.fullmatch(r'which of (?:those projects|these projects|them) '
                          r'(?:have (?:a )?(?:reported )?(?:end|closing) dates?|end|are ending|close|are closing) '
                          r'(?:in )?((?:19|20)\d{2}|this year|(?:the )?next \d{1,2} (?:days?|weeks?|months?))', q)
    french = re.fullmatch(r'lesquels de ces projets ont une date de (?:fin|cloture) '
                         r'(?:en ((?:19|20)\d{2})|dans les \d{1,2} prochains? (?:jours?|semaines?|mois))', q)
    matched = english or french
    if not matched:
        return None
    from project_dates import reported_end_window
    window = reported_end_window(question)
    period = english[1] if english else french[1]
    if not window and (period is None or 'next' in period):
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
        year = datetime.now(timezone.utc).year if period == 'this year' else int(period)
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
