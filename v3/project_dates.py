"""Reported project dates are signals for review, never proof of completion."""
from datetime import date, datetime, timedelta, timezone
import re
from source_wave import _fold


def ending_intent(question):
    q = _fold(question)
    if re.search(r'\b(ending|end dates?|past end|still active|closing|close|expire|expiration|echeances?|dates? de fin|termin\w*|finissent|finissant)\b', q):
        return True
    # A bounded project-date follow-up need not repeat the word "ending".
    # Do not apply date screening to unrelated future needs or forecasts.
    return bool(re.search(r'\b(projects?|projets?|interventions?|dated|dates?)\b', q)
                and re.search(r'\b(next|prochains?|prochaines?)\s+(180\s+(days|jours)|(?:six|6)\s+(months|mois))\b', q))


def parsed_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError,TypeError):
        return None


def select_examples(projects, ending=False, asof=None, limit=8):
    asof=asof or datetime.now(timezone.utc).date()
    named=[p for p in projects if p.get('project_name')]
    if not ending:
        return sorted(named,key=lambda p:str(p['project_name']))[:limit],None
    active=[p for p in named if _fold(p.get('status')) in ('en cours','active','implementation','ongoing')]
    upcoming=[p for p in active if parsed_date(p.get('end_date')) and asof<=parsed_date(p['end_date'])<=asof+timedelta(days=180)]
    overdue=[p for p in active if parsed_date(p.get('end_date')) and parsed_date(p['end_date'])<asof]
    missing=[p for p in active if not parsed_date(p.get('end_date'))]
    selected=(sorted(upcoming,key=lambda p:p['end_date'])+sorted(overdue,key=lambda p:p['end_date'],reverse=True))[:limit]
    return selected,{'asof':asof.isoformat(),'window_end':(asof+timedelta(days=180)).isoformat(),
        'upcoming_active_records':len(upcoming),'active_with_past_end_date':len(overdue),'active_missing_valid_end_date':len(missing),
        'limitation':'Reported dates and status are planning/registry signals, not actual completion or currently verified delivery. Overdue active labels conflict with their end dates; latest sync must be shown.'}
