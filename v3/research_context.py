"""Recognise research references and preserve bounded context, never evidence."""
import re
import unicodedata


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
    """Keep the latest roster intact; earlier turns stay narrowly bounded."""
    recent = messages[-10:]
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
            turns.append('ASSISTANT CONTEXT ONLY: ' + str(message['content'])[:limit])
    return '\n\n'.join(turns[-8:])
