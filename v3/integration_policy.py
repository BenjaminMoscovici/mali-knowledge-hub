"""Source intent and source-reported status controls for Issue #1."""
import re
from routing import _normal


def reported_active_requested(question):
    q = _normal(question)
    return bool(re.search(r'\b(?:active|actifs?|actives?|currently|actuellement|en cours|ongoing|aktuell|derzeit|laufend\w*)\b', q)) and not bool(re.search(r'\b(?:not active|pas actifs?|non actifs?|nicht aktiv)\b', q))


def integration_intent(question):
    q = _normal(question)
    presence = bool(re.search(r'\b(?:3w|5w|who does what|qui fait quoi|presence|present|actors?|acteurs?|interventions?|respond\w*|reponse|lacunes?|gaps?|coverage|couverture)\b', q))
    needs = bool(re.search(r'\b(?:needs?|besoins?|hno|hnrp|pin|people in need)\b', q))
    named = bool(re.search(r'\b(?:3w|5w)\b', q))
    return {'ocha_3w': named or (presence and needs) or (presence and 'fongim' not in q), 'needs': needs, 'named_3w': named}


def select_reported_active(projects, requested):
    if not requested:
        return projects, None
    selected = [p for p in projects if _normal(str(p.get('status') or '')).strip() in ('en cours', 'active', 'ongoing', 'implementation')]
    return selected, {'selection': 'source-reported ongoing status only', 'input_projects': len(projects), 'selected_projects': len(selected), 'excluded_projects': len(projects)-len(selected), 'limitation': 'Snapshot status is not proof of current activity. Reported dates may conflict with status; show synchronization timestamp and original dates.'}


def bounded_integration_sources(question):
    q = _normal(question)
    if re.search(r'\bhno\b', q) and not re.search(r'\b(?:fongim|3w|5w|dtm|cadre|ipc|hapi|compare\w*|compar\w*|coverage|couverture|interventions?)\b', q):
        return {'foundation', 'geographic_model'}
    if re.search(r'\b(?:3w|5w)\b', q) and not re.search(r'\b(?:fongim|hno|hnrp|needs?|besoins?|dtm|cadre|ipc|hapi|fts|fund\w*|financ\w*|strateg\w*|priorit\w*)\b', q):
        return {'operational', 'geographic_model'}
    return None
