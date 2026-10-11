"""Recognise research references and preserve bounded context, never evidence."""
import re
import unicodedata


def _qualified_context_identifiers(value):
    """Return bounded source identifiers, never surrounding answer claims."""
    from project_references import fongim_roster_ids

    text = str(value)
    # Conversation output should never contain enormous identifier tokens, but
    # bound them here so malformed text cannot crowd out the retained context.
    safe_fongim_text = re.sub(r'\d{13,}', '', text)
    groups = (
        ('FONGIM project IDs', tuple(map(str, fongim_roster_ids(safe_fongim_text)))),
        ('World Bank project IDs', tuple(dict.fromkeys(
            re.findall(r'\bP\d{6}\b', text.upper())))),
        ('EU IATI activity IDs', tuple(dict.fromkeys(
            re.findall(r'\bXI-IATI-EC_(?:INTPA|ECHO)-[A-Z0-9][A-Z0-9._/-]{0,119}'
                       r'(?![A-Z0-9._/-])',
                       text.upper())))),
    )
    remaining = 20
    found = []
    for namespace, identifiers in groups:
        selected = identifiers[:remaining]
        found.extend((namespace, identifier) for identifier in selected)
        remaining -= len(selected)
        if not remaining:
            break
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


def conversation_context(messages):
    """Keep the latest topic and roster intact; older topics do not leak in."""
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
