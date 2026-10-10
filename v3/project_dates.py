"""Reported project dates are signals for review, never proof of completion."""
from datetime import date, datetime, timedelta, timezone
import re
import calendar
from source_wave import _fold


def parsed_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError,TypeError):
        return None


def calendar_end_year(question, asof=None):
    """One explicit calendar year for reported end dates; ambiguous years defer."""
    q = _fold(question)
    if reported_end_window(question, asof):
        return None
    if not re.search(r'\b(end dates?|reported end|closing|close|closes|closure|clotur\w*|ending|ends?|dates? de fin|fin en|echeances?|termin\w*|finissent)\b', q):
        return None
    years = {int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b', q)}
    this_year = bool(re.search(r'\b(?:this year|cette annee)\b', q))
    next_year = bool(re.search(r'\b(?:next year|l annee prochaine|l an prochain)\b', q))
    # Do not silently choose one period from a compound or rolling request.
    if re.search(r'\b(?:next|prochains?) \d{1,2} (?:days?|weeks?|months?|jours?|semaines?|mois)\b', q):
        return None
    if len(years) + int(this_year) + int(next_year) != 1:
        return None
    if len(years) == 1:
        return next(iter(years))
    current = (asof or datetime.now(timezone.utc).date()).year
    return current + int(next_year)


def reported_end_window(question, asof=None):
    """Unambiguous explicit end-date windows, inclusive, anchored to UTC today.

    Calendar months retain the day or clamp it to the last day of the month.
    Unknown, conflicting and multiple periods defer to semantic analysis.
    """
    q = _fold(question)
    if not re.search(r'\b(end dates?|reported end|closing|close|closes|closure|clotur\w*|ending|ends?|dates? de fin|echeances?|termin\w*|finissent)\b', q):
        return None
    asof = asof or datetime.now(timezone.utc).date()
    relative = re.findall(r'\b(?:next|prochains?) (\d{1,2}) (days?|weeks?|months?|jours?|semaines?|mois)\b', q)
    relative += re.findall(r'\b(\d{1,2}) prochains? (jours?|semaines?|mois)\b', q)
    relative += [(n,u) for n,u in re.findall(r'\b(\d{1,2}) (jours?|semaines?|mois) (?:a venir|prochains?)\b', q)]
    ranges = re.findall(r'\b(?:between|from|entre|du) (\d{4}-\d{2}-\d{2}) (?:and|to|et|au) (\d{4}-\d{2}-\d{2})\b', question.lower())
    if len(relative)+len(ranges) != 1:
        return None
    if ranges:
        start,end = map(parsed_date,ranges[0])
        if not start or not end or end < start or len(re.findall(r'\d{4}-\d{2}-\d{2}', question)) != 2:
            return None
    else:
        # A second named year/date/calendar period is not silently ignored.
        if re.search(r'\b(?:19|20)\d{2}\b|\b(this year|cette annee|next year|l annee prochaine|l an prochain|last|past|dernier\w*)\b', q):
            return None
        n,unit=relative[0];n=int(n)
        if not 1 <= n <= 36:
            return None
        start=asof
        if unit in ('month','months','mois'):
            ordinal=asof.year*12+asof.month-1+n
            year,month=divmod(ordinal,12);month+=1
            end=date(year,month,min(asof.day,calendar.monthrange(year,month)[1]))
        else:
            end=asof+timedelta(days=n*(7 if unit in ('week','weeks','semaine','semaines') else 1))
    return (start.isoformat(),end.isoformat())


def select_examples(projects, ending=False, asof=None, limit=8, end_year=None, active_only=False, end_window=None):
    asof=asof or datetime.now(timezone.utc).date()
    named=[p for p in projects if p.get('project_name')]
    if end_window is not None:
        start,end=map(parsed_date,end_window)
        if not start or not end or start > end:
            raise ValueError('Invalid reported end-date window')
        candidates=[p for p in named if not active_only or _fold(p.get('status')) in ('en cours','active','implementation','ongoing')]
        matched=[p for p in candidates if parsed_date(p.get('end_date')) and start <= parsed_date(p['end_date']) <= end]
        selected=sorted(matched,key=lambda p:(p['end_date'],p['project_name']))[:limit]
        return selected, {'asof':asof.isoformat(),'selection_kind':'reported end date in inclusive window',
            'window_start':start.isoformat(),'window_end':end.isoformat(),'active_only':active_only,
            'matching_records':len(matched),'selected_records':len(selected),
            'missing_valid_end_date':sum(parsed_date(p.get('end_date')) is None for p in candidates),
            'limitation':'Explicit inclusive date window, not the default 180-day screen. Reported dates/status do not prove completion, delivery, or successor funding. Bounded source selection, not a complete portfolio.'}
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
