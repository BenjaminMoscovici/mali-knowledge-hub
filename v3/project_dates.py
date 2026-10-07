"""Reported project dates are signals for review, never proof of completion."""
from datetime import date, datetime, timedelta, timezone
import re
from source_wave import _fold


def parsed_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError,TypeError):
        return None


def calendar_end_year(question, asof=None):
    """One explicit calendar year for reported end dates; ambiguous years defer."""
    q = _fold(question)
    if not re.search(r'\b(end dates?|reported end|closing|ending|ends? in|dates? de fin|fin en|echeances?|termin\w*|finissent)\b', q):
        return None
    years = {int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b', q)}
    if len(years) == 1:
        return next(iter(years))
    if not years and re.search(r'\b(this year|cette annee)\b', q):
        return (asof or datetime.now(timezone.utc).date()).year
    return None


def select_examples(projects, ending=False, asof=None, limit=8, end_year=None, active_only=False):
    asof=asof or datetime.now(timezone.utc).date()
    named=[p for p in projects if p.get('project_name')]
    if end_year is not None:
        candidates = [p for p in named if not active_only or _fold(p.get('status')) in ('en cours','active','implementation','ongoing')]
        matched = [p for p in candidates if parsed_date(p.get('end_date')) and parsed_date(p['end_date']).year == end_year]
        selected = sorted(matched, key=lambda p:(p['end_date'],p['project_name']))[:limit]
        return selected, {'asof':asof.isoformat(), 'selection_kind':'reported end date in calendar year',
            'year':end_year, 'active_only':active_only, 'matching_records':len(matched), 'selected_records':len(selected),
            'missing_valid_end_date':sum(parsed_date(p.get('end_date')) is None for p in candidates),
            'limitation':'Calendar-year selection from returned registry records, not a rolling 180-day window. Reported dates and status do not prove actual completion or currently verified delivery.'}
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
