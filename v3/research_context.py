"""Recognise research references and preserve bounded context, never evidence."""
import re
import unicodedata


def _context_identifier_groups(value):
    """Read source-qualified identifiers without surrounding answer claims."""
    from project_references import fongim_roster_ids

    text = str(value)
    # Conversation output should never contain enormous identifier tokens, but
    # bound them here so malformed text cannot crowd out the retained context.
    safe_fongim_text = re.sub(r'\d{13,}', '', text)
    return (
        ('FONGIM project IDs', tuple(map(
            str, fongim_roster_ids(safe_fongim_text, limit=None,
                                   preserve_order=True)))),
        ('World Bank project IDs', tuple(dict.fromkeys(
            re.findall(r'\bP\d{6}\b', text.upper())))),
        ('EU IATI activity IDs', tuple(dict.fromkeys(
            re.findall(r'\bXI-IATI-EC_(?:INTPA|ECHO)-[A-Z0-9][A-Z0-9._/-]{0,119}'
                       r'(?![A-Z0-9._/-])',
                       text.upper())))),
    )


def _qualified_context_identifiers(value):
    """Return bounded source identifiers, never surrounding answer claims."""
    groups = _context_identifier_groups(value)
    # Keep the global ceiling, but allocate it across every namespace that is
    # present. Within each namespace, sample the complete ordered roster from
    # first to last rather than always taking its first IDs. This preserves
    # early and late lookup context when a single source alone exceeds the cap,
    # without promoting surrounding claims or widening fresh lookup limits.
    allocated = [0 for _ in groups]
    remaining = 20
    while remaining and any(allocated[index] < len(identifiers)
                            for index, (_, identifiers) in enumerate(groups)):
        for index, (_, identifiers) in enumerate(groups):
            if remaining and allocated[index] < len(identifiers):
                allocated[index] += 1
                remaining -= 1

    def spread(identifiers, count):
        if count >= len(identifiers):
            return identifiers
        if count <= 1:
            return identifiers[:count]
        last = len(identifiers) - 1
        return tuple(identifiers[(offset * last) // (count - 1)]
                     for offset in range(count))

    found = []
    for (namespace, identifiers), count in zip(groups, allocated):
        found.extend((namespace, identifier)
                     for identifier in spread(identifiers, count))
    return tuple(found)


def _identifier_marker(identifiers):
    grouped = []
    for namespace, identifier in identifiers:
        if grouped and grouped[-1][0] == namespace:
            grouped[-1][1].append(identifier)
        else:
            grouped.append([namespace, [identifier]])
    summary = '; '.join(
        f'{namespace} {", ".join(values)}' for namespace, values in grouped)
    marker = '...[middle omitted; context only]...'
    if summary:
        marker += ('\n...[source-qualified identifiers retained from omitted context '
                   f'only: {summary}]...')
    return '\n' + marker + '\n'


def _bounded_context_text(value, limit):
    """Retain both ends and omitted identifiers within the original budget."""
    text = str(value)
    if len(text) <= limit:
        return text
    identifiers = _qualified_context_identifiers(text)
    omitted = ()
    # Adding an identifier appendix slightly widens the omitted middle. Repeat
    # until every qualified identifier outside the retained ends is covered.
    while True:
        marker = _identifier_marker(omitted)
        head = (limit - len(marker)) // 2
        tail = limit - len(marker) - head
        retained = set(_qualified_context_identifiers(text[:head] + text[-tail:]))
        widened = tuple(item for item in identifiers if item not in retained)
        if widened == omitted:
            break
        omitted = widened
    return text[:head] + marker + text[-tail:]


def has_reference(question):
    text = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold())
                   if not unicodedata.combining(c))
    text = re.sub(r'[^\w\s]', ' ', text)
    text = ' '.join(text.split())
    nouns = (r'projects?|interventions?|programmes?|programs?|activities|actors?|'
             r'organisations?|organizations?|records?|findings?|needs?|priorities|'
             r'allocations?|transactions?|sources?|figures?|results?|options?')
    patterns = (
        rf'\b(?:those|these|the above|previously listed)\s+(?:{nouns})\b',
        r'\b(?:of|among|from)\s+(?:them|those|these)\b',
        r'\b(?:mentioned|listed|discussed)\s+(?:above|earlier|previously)\b',
        r'\b(?:that|this)\s+(?:compare|comparison|finding|analysis|result|figure)\b',
        r'\bces\s+(?:projets?|interventions?|programmes?|activites|acteurs?|'
        r'organisations?|resultats?|besoins|priorites|financements?|sources|chiffres)\b',
        r'\b(?:parmi|entre)\s+(?:eux|elles|ceux|celles)\b',
        r'\b(?:ceux|celles)\s+(?:ci|la)\b',
        r'\b(?:mentionnes?|mentionnees?|listes?|listees?|cites?|citees?)\s+'
        r'(?:ci dessus|precedemment|plus haut)\b',
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _latest_topic_messages(messages):
    """Exclude exchanges superseded by a newer substantive question."""
    recent = messages[-10:]
    # A complete newer research question supersedes every older topic. Social
    # acknowledgements and conversation-only transforms do not: a user may say
    # thanks, then continue filtering the latest evidence set. Stored
    # standalone questions make resolved follow-ups safe topic boundaries too.
    from query_router import classify
    starts = []
    for index, message in enumerate(recent):
        if message.get('role') != 'user':
            continue
        value = message.get('standalone_question') or message.get('content')
        if isinstance(value, str) and value.strip() and classify(value)['path'] not in {
                'conversational', 'conversation_only'}:
            starts.append(index)
    if starts:
        recent = recent[starts[-1]:]
    return recent


def conversation_context(messages):
    """Keep the latest topic and roster intact; older topics do not leak in."""
    recent = _latest_topic_messages(messages)
    assistants = [i for i, row in enumerate(recent)
                  if row.get('role') == 'assistant' and row.get('content')]
    last = assistants[-1] if assistants else None
    turns = []
    for index, message in enumerate(recent):
        if message.get('role') == 'user':
            value = message.get('standalone_question') or message.get('content')
            if value:
                turns.append('USER QUESTION: ' + str(value)[:1600])
        elif message.get('role') == 'assistant' and message.get('content'):
            limit = 6000 if index == last else 800
            turns.append('ASSISTANT CONTEXT ONLY: ' +
                         _bounded_context_text(message['content'], limit))
    return '\n\n'.join(turns[-8:])


def preserve_project_selection(standalone, question, messages):
    """Prevent a semantic selector from replacing its complete bounded roster.

    Only source IDs survive. When a rewrite changes the set, the original
    user question supplies every criterion; model-added claims are discarded.
    Unnamed mixed sets, explicit new IDs and incomplete rosters remain outside
    this guard rather than being treated as a complete selection.
    """
    q = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold())
                if not unicodedata.combining(c))
    q = ' '.join(re.sub(r'[^\w\s]', ' ', q).split())
    en = re.match(r'which of (?:those|these) '
                  r'(?:(?P<source>fongim|world bank|eu) )?projects\b', q)
    fr = re.match(r'lesquels de ces projets'
                  r'(?: (?P<source>fongim|de la banque mondiale|de l ue|ue))?\b', q)
    pronoun = re.match(r'(?:which of them|lesquels d entre eux|lesquels parmi eux)\b', q)
    if not (en or fr or pronoun):
        return standalone
    # A user-authored explicit identity is a new constraint, not a pronoun
    # selection that can be replaced by the preceding complete roster.
    if (any(ids for _, ids in _context_identifier_groups(question)) or
            re.search(r'\b(?:ids?|identifiants?)\s+\d+\b', q)):
        return standalone
    from query_router import classify
    recent = _latest_topic_messages(messages)
    latest = ''
    social_exchange = False
    for row in recent:
        if row.get('role') == 'user':
            value = row.get('standalone_question') or row.get('content', '')
            social_exchange = classify(value)['path'] in {
                'conversational', 'conversation_only'}
        elif row.get('role') == 'assistant' and row.get('content') and not social_exchange:
            latest = row['content']
    if (not latest or len(latest) >= 5900
            or 'Selected source identifiers for this filter: none.' in latest
            or 'Identifiants source sélectionnés par ce filtre : aucun.' in latest):
        return standalone
    # Canonical result tables supply only their identifier column. Titles and
    # excluded-record notes must not enlarge the selected set.
    lines = latest.splitlines()
    headers = [i for i, line in enumerate(lines)
               if line.lstrip().startswith('|') and re.search(
                   r'^\|\s*(?:Source identifier|Identifiant source)\s*\|', line.lstrip(),
                   re.I)]
    if headers:
        if len(headers) != 1:
            return standalone
        columns = []
        for line in lines[headers[0] + 1:]:
            if not line.lstrip().startswith('|'):
                break
            columns.append(line.split('|')[1].strip())
        latest = '\n'.join(columns)
    groups = [(namespace, tuple(value.rstrip('.:') for value in ids)) for namespace, ids in
              _context_identifier_groups(latest) if ids]
    source_labels = {'fongim': 'FONGIM project IDs',
                     'world bank': 'World Bank project IDs',
                     'de la banque mondiale': 'World Bank project IDs',
                     'eu': 'EU IATI activity IDs', 'ue': 'EU IATI activity IDs',
                     'de l ue': 'EU IATI activity IDs'}
    match = en or fr
    named = source_labels.get(match.groupdict().get('source')) if match else None
    if named:
        groups = [(namespace, ids) for namespace, ids in groups if namespace == named]
    if len(groups) != 1 or len(groups[0][1]) > 12:
        return standalone
    namespace, ids = groups[0]
    rewritten = [(family, tuple(value.rstrip('.:') for value in values)) for family, values in
                 _context_identifier_groups(standalone) if values]
    if len(rewritten) == 1 and rewritten[0][0] == namespace and set(rewritten[0][1]) == set(ids):
        return standalone
    labels = ', '.join(ids)
    french_names = {'FONGIM project IDs': 'FONGIM',
                    'World Bank project IDs': 'World Bank',
                    'EU IATI activity IDs': 'EU IATI'}
    prefix = (f'Pour {french_names[namespace]}, identifiants de projets {labels} : '
              if fr or q.startswith('lesquels ') else f'For {namespace} {labels}: ')
    return prefix + question.strip()


def preserve_lookup_namespace(standalone, question, messages):
    """Keep a known source namespace when a rewrite preserves only its IDs.

    The prior roster supplies lookup context, never its dates/donor/status.
    Only an explicit reference and an exact subset of that roster qualify.
    """
    from project_references import fongim_project_ids, fongim_roster_ids
    if not has_reference(question) or re.search(r'\bfongim\b', standalone, re.I):
        return standalone
    if re.search(r'\b(world bank|banque mondiale|intpa|echo|xi.iati|P\d{6})\b', standalone, re.I):
        return standalone
    latest = next((m.get('content','') for m in reversed(messages)
                   if m.get('role') == 'assistant' and m.get('content')), '')
    prior = set(fongim_roster_ids(latest))
    requested = set(fongim_project_ids('FONGIM ' + standalone))
    if requested and requested <= prior:
        return 'FONGIM source project IDs: ' + ', '.join(map(str,sorted(requested))) + '. ' + standalone
    return standalone
