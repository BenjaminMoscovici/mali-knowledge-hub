"""Cited EU evidence: programming, commitment, signature and status stay distinct."""
from datetime import datetime,timedelta,timezone
from functools import lru_cache
import gzip,json,logging,re
from pathlib import Path
from analytical_sources import evidence
from operational_sources import publish_operational_snapshot
from project_dates import parsed_date, calendar_end_year
from source_wave import _fold

@lru_cache(maxsize=1)
def package():
    with gzip.open(Path(__file__).with_name('source_wave5.json.gz'),'rt',encoding='utf-8') as f:return json.load(f)


def item(row,extra=''):
    p=row['payload'];facts={k:v for k,v in p['facts'].items() if k!='financial_raw'}
    content=(f'EU evidence stage: {p["evidence_stage"]}. Title: {p["title"]}. '+json.dumps(facts,ensure_ascii=False)
        +'. Source geography: '+json.dumps(p['geography'],ensure_ascii=False)+'. '
        'Reference period '+row['reference_start']+' to '+row['reference_end']+'. '
        'For activity records this is a registry retrieval snapshot, not delivery dates; for EIB it is signature date, not project duration. '
        'Programming intent, approved action, commitment, disbursement, implementation and results are separate stages. '
        'Amounts from different stages, periods, currencies or scopes must not be added or subtracted into funding/coverage gaps. '
        +p['limitations']+' '+extra)
    result=evidence([row],content,p['title'],'; '.join(f'{k}: {v}' for k,v in p['geography'].items()),
        'source-reported scope only; no approved commune/cercle coverage',data=package())
    result['source_family']='EU / Team Europe — '+row['source_type']
    result['valid_from']=result['valid_until']=None
    return result


from evidence_cache import snapshot_cached


def _activity_item(row, today):
    """Preserve the source facts, dates and limitations for every selection path."""
    facts = row['payload']['facts']
    flags = []
    end = parsed_date(facts['end_date_reported'])
    start = parsed_date(facts['start_date_reported'])
    if end and end < today:
        flags.append('Historical reported end date: do not describe this record as current activity or current needs alignment; mention its dates and status explicitly')
    if end and end < today and facts['status'] == 'Implementation':
        flags.append('Implementation status with past reported end: unresolved registry conflict')
    if start and start > today:
        flags.append('Future reported start: planned/actual type unavailable; not confirmed current delivery')
    result=item(row, f'Query date {today}; flags {flags}. Bounded selection from 134 INTPA and 172 ECHO exact-country activities; 37 ECHO multi-country records excluded. '
        'No verified transaction money, implementers, linked documents, outcomes or local coverage in this fallback. Names in titles are geographical mentions only. '
        'Source sector codes are preserved separately from title-derived thematic relevance; a WASH title does not change a reported governance sector code.')
    result['project_record']={'source_namespace':'EU IATI','source_id':facts['activity_id'],
        'title':row['payload']['title'],'status':facts['status'],
        'start_date':facts['start_date_reported'],'end_date':facts['end_date_reported'],
        'source_updated_at':None}
    return result


def _referenced_activities(question, records):
    """Match complete source IDs or unique complete INTPA codes, never prefixes."""
    q = _fold(question)
    if not re.search(r'\b(?:xi iati ec (?:intpa|echo)|\d{4} pc \d{4,8})\b', q):
        return []
    activities = [r for r in records if r['source_type'] == 'eu_activity']
    codes = re.findall(r'\b\d{4} pc \d{4,8}\b', q)
    unique_codes = {}
    for code in codes:
        matches = [r for r in activities if
                   _fold(r['payload']['facts']['activity_id']).endswith(' ' + code)]
        if len(matches) == 1:
            unique_codes[code] = matches[0]['id']
    return [r for r in activities if r['id'] in unique_codes.values() or re.search(
        r'\b' + re.escape(_fold(r['payload']['facts']['activity_id'])) + r'\b', q)]


@snapshot_cached("source_wave5.json.gz")
def retrieve_eu_evidence(question,limit=20):
    q=_fold(question)
    data=package()['records'];today=datetime.now(timezone.utc).date()
    referenced = _referenced_activities(question, data)
    broader = bool(re.search(
        r'\b(compare\w*|compar\w*|other|autres?|priorit\w*|needs?|besoins?|'
        r'align\w*|portfolio|portefeuille|national|ndici|team europe|echo hip)\b', q))
    if referenced and not broader:
        # Exact activity questions need their complete source record, not a
        # country-programming bundle or unrelated activity examples. Other
        # evidence families are still retrieved independently by the Hub.
        return [_activity_item(r, today) for r in referenced][:limit]
    # Institutional names and instruments are evidence-family intent, not
    # evidence of funding, implementing roles or current local delivery.
    if not re.search(
        r'\b(eu|ue|european union|union europeenne|europaische union|'
        r'european commission|commission europeenne|europaische kommission|'
        r'team europe|equipe europe|intpa|echo|tei|eib|bei|capacity4dev|'
        r'kabala|t05 eutf|ndici|global gateway|eutf|european development fund|'
        r'fonds europeen de developpement)\b', q
    ) and not re.search(r'\bDUE\b',question) and not referenced:return []
    ending=bool(re.search(r'\b(ending|end dates?|closing|echeances?|termin\w*|finissent)\b',q))
    end_year=calendar_end_year(question, today)
    active_only=bool(re.search(r'\b(active|currently active|en cours)\b',q))
    themes=[]
    for key,pattern in {'food_security':r'food|aliment|faim|hunger|agric','wash':r'wash|water|eau|assain|sanitation',
        'education':r'educ|ecole|school|learn|appren|vocational|formation','health':r'health|sante',
        'nutrition':r'nutri','protection':r'protect','employment':r'job|emploi|youth|jeune',
        'environment':r'climat|environment|environnement|green|vert','energy':r'energ|electric',
        'governance':r'govern|gouvern|state|etat','displacement':r'displace|deplace|dtm'}.items():
        if re.search(pattern,q):themes.append(key)
    from geographic_model import geographic_model
    wanted_geo=geographic_model().retrieval_place_names(question)
    def place_score(r):
        # Rank actual title/geography mentions, not repeated limitations or
        # incidental substrings. A matching name remains a mention only.
        p=r['payload']
        text=' '+_fold(p['title']+' '+json.dumps(p['geography'],ensure_ascii=False))+' '
        return sum((' '+g+' ') in text for g in wanted_geo)
    def score(r):
        p=r['payload'];text=_fold(json.dumps(p,ensure_ascii=False))
        return (place_score(r),sum(t in p['sectors'] for t in themes)*4+sum(w in text for w in q.split() if len(w)>4))
    fixed=[r for r in data if r['source_type'] not in ('eu_activity','eib_project','eu_project_metadata','eu_tei')]
    fixed.sort(key=lambda r:(r['dataset_id']=='mli-eu-current-overview',score(r)),reverse=True)
    results=[_activity_item(r, today) for r in referenced]+[item(r) for r in fixed]
    for pub in ('XI-IATI-EC_INTPA','XI-IATI-EC_ECHO'):
        rows=[r for r in data if r['source_type']=='eu_activity' and r['payload']['facts']['publisher_ref']==pub]
        if end_year is not None:
            rows=[r for r in rows if parsed_date(r['payload']['facts']['end_date_reported'])
                  and parsed_date(r['payload']['facts']['end_date_reported']).year==end_year
                  and (not active_only or r['payload']['facts']['status']=='Implementation')]
            rows.sort(key=lambda r:(-place_score(r),r['payload']['facts']['end_date_reported']))
        elif ending:
            rows=[r for r in rows if r['payload']['facts']['status']=='Implementation' and parsed_date(r['payload']['facts']['end_date_reported'])
                and parsed_date(r['payload']['facts']['end_date_reported'])<=today+timedelta(days=180)]
            rows.sort(key=lambda r:(-place_score(r),parsed_date(r['payload']['facts']['end_date_reported'])<today,r['payload']['facts']['end_date_reported']))
        else:rows.sort(key=lambda r:(score(r),r['payload']['facts']['status']=='Implementation',r['payload']['facts']['start_date_reported'] or ''),reverse=True)
        for r in rows[:2]:
            if r['id'] not in {x['record_id'] for x in results}:
                result=_activity_item(r, today)
                if end_year is not None:
                    result['content']+=f' Hub retrieval filter: reported end date in calendar year {end_year}, not a rolling 180-day window; bounded source examples, not a complete portfolio.'
                results.append(result)
    other=[r for r in data if r['source_type'] in ('eu_tei','eu_project_metadata','eib_project')]
    other.sort(key=lambda r:(score(r),r['source_type']!='eib_project'),reverse=True)
    results.extend(item(r,'Selected historical project/initiative, not a complete portfolio or current actor roster.') for r in other)
    return results[:limit]


def publish_eu_logged():
    try:logging.getLogger('mkh.sources').info('eu_wave %s',json.dumps(publish_operational_snapshot(package())))
    except Exception as error:logging.getLogger('mkh.sources').warning('eu_wave publication_failed error_class=%s',type(error).__name__)
