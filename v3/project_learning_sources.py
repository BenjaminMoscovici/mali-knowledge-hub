"""Exact project-ID joins across WB profiles, WB IATI and historical IEG."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import gzip
import json
import logging
from pathlib import Path
import re

from analytical_sources import evidence
from operational_sources import publish_operational_snapshot
from project_dates import parsed_date, calendar_end_year
from source_wave import _fold


@lru_cache(maxsize=1)
def package():
    with gzip.open(Path(__file__).with_name('source_wave4.json.gz'),'rt',encoding='utf-8') as file:
        return json.load(file)


def item(rows,content,title,family):
    result=evidence(rows,content,title,'Mali; country-level project context, local location unverified',
                    'project country profile only',data=package())
    result['source_family']=family
    return result


from evidence_cache import snapshot_cached

@snapshot_cached("source_wave4.json.gz")
def retrieve_project_learning(question,limit=12):
    folded=_fold(question);results=[]
    learning=bool(re.search(r'\b(learning|lessons?|evaluat\w*|worked|failed|results|constraints|recommend\w*|appris|enseign\w*|reussi\w*|echoue\w*)\b',folded))
    project=bool(re.search(r'\b(iati|world bank|banque mondiale|projects?|projets?|financ\w*|fund\w*|interventions?|closing|ending)\b',folded))
    ids=set(re.findall(r'\bP\d{6}\b',question.upper()))
    if not (learning or project or ids):return []
    rows=[r for r in package()['records'] if r['source_type']=='development_project']
    today=datetime.now(timezone.utc).date()
    ending=bool(re.search(r'\b(ending|closing|close|echeances?|termin\w*|end dates?)\b',folded))
    end_year=calendar_end_year(question, today)
    if learning and not ids:ids={'P144442'}
    if ids:
        selected=[r for r in rows if r['payload']['project_id'] in ids]
    elif end_year is not None:
        active_only=bool(re.search(r'\b(active|en cours)\b',folded))
        selected=[r for r in rows if parsed_date(r['payload']['closing_date_reported'])
                  and parsed_date(r['payload']['closing_date_reported']).year==end_year
                  and (not active_only or r['payload']['status']=='Active')]
        selected=sorted(selected,key=lambda r:(r['payload']['closing_date_reported'],r['payload']['project_id']))[:4]
    elif ending:
        selected=[r for r in rows if r['payload']['status']=='Active' and parsed_date(r['payload']['closing_date_reported'])
                  and parsed_date(r['payload']['closing_date_reported'])<=today+timedelta(days=180)]
        selected.sort(key=lambda r:(parsed_date(r['payload']['closing_date_reported'])<today,r['payload']['closing_date_reported']))
        selected=selected[:4]
    else:
        selected=sorted([r for r in rows if r['payload']['status'] in ('Active','Pipeline')],
                        key=lambda r:(r['payload']['status']=='Pipeline',r['payload']['board_date_reported'] or ''),reverse=True)[:4]
    if selected:
        counts={status:sum(r['payload']['status']==status for r in rows) for status in ('Active','Pipeline','Closed','Dropped')}
        results.append(item(selected,
            f'World Bank v3 exact-Mali country-profile snapshot has {len(rows)} project IDs, source status counts {counts}. '
            f'The following {len(selected)} profiles are a bounded selection, not all projects or confirmed local interventions. '
            +(f'Hub retrieval filter: reported closing date in calendar year {end_year}, not a rolling 180-day window. ' if end_year is not None and not ids else '')+
            'Regional/multicountry profiles are excluded. Country attribution does not place a project in the user-selected region/commune. '
            'Retrieval date is not project-level update date. Pipeline board dates are planned; Active with past closing date is a registry conflict, not proven ongoing delivery. '
            'Financial API fields lack explicit currency/unit metadata in this export and are not exposed as verified money; do not infer disbursements.',
            'World Bank Mali project profile scope','World Bank projects'))
    for r in selected:
        p=r['payload']; pid=p['project_id']
        flags=list(p['flags'])
        if p['status']=='Active' and parsed_date(p['closing_date_reported']) and parsed_date(p['closing_date_reported'])<today:
            flags.append('active_label_is_overdue_as_of_query')
        results.append(item([r],
            f'World Bank project {pid}: {p["title"]}; source status {p["status"]}; reported board date {p["board_date_reported"]}; '
            f'reported closing date {p["closing_date_reported"]}; borrower {p["borrower"] or "not reported"}; implementing agency {p["implementing_agency"] or "not reported"}. '
            f'Project-level update date {p["project_updated_at"] or "unavailable"}; flags {flags}. Query date {today}. '
            'This is national project-profile evidence, not verified activity/reach in a selected locality. Missing sector/geography is not inferred from its title. '
            'Future board dates are planned; a closing date does not prove completion. Raw financial fields have unverified units and are omitted from analytical amounts.',
            'World Bank — '+pid+' — '+p['title'],'World Bank projects'))
    selected_ids={r['payload']['project_id'] for r in selected}
    iati=[r for r in package()['records'] if r['source_type']=='aid_activity' and r['payload']['project_id'] in selected_ids]
    # For explicit IATI browsing, show a small source-status sample even if profiles select newer projects absent in WB's IATI subset.
    if not iati and 'iati' in folded and not ids:
        iati=sorted([r for r in package()['records'] if r['source_type']=='aid_activity'],
                    key=lambda r:r['payload']['end_date_reported'] or '',reverse=True)[:3]
    for r in iati[:4]:
        p=r['payload']
        profile=next((x['payload'] for x in rows if x['payload']['project_id']==p['project_id']),None)
        link=('Exact project-ID identity link to WB profile: '+p['project_id']+'; WB source status '+profile['status']+', reported closing date '+str(profile['closing_date_reported'])+'. ' if profile else 'No matching profile in selected exact-country subset. ')
        results.append(item([r],
            f'IATI activity {p["activity_id"]}, publisher {p["publisher"]} ref {p["publisher_ref"]}, title {p["title"]}; '
            f'source status {p["status"]}, reported start/end dates {p["start_date_reported"]}/{p["end_date_reported"]}. '
            f'Country percentage label {p["country_percent_reported"]}; funder refs {p["funder_refs"]}; sectors {json.dumps(p["sectors"],ensure_ascii=False)}. '
            +link+f'{p["source_sector_rows"]} sector rows deduplicated into one activity; repeated financial values must not be summed. '
            'Differences between source statuses/dates remain visible, not silently overwritten. IATI is self-reported; country assignment does not prove subnational presence. '
            'Only 36 WB activities are integrated, not all IATI Mali. Raw money fields have unverified currency/conversion/transaction period and are not interpreted as verified disbursements.',
            'IATI World Bank — '+p['activity_id'],'IATI World Bank activity subset'))
    if learning or 'P144442' in ids:
        for r in [r for r in package()['records'] if r['source_type']=='evaluation_finding']:
            p=r['payload']
            results.append(item([r],
                f'IEG ICRR0023565, exact project ID {p["project_id"]}, PDF page {p["page"]}, finding type {p["finding_kind"]}. '
                +p['finding']+' Methodology: '+p['methodology']+'. Transferability: '+p['transferability']+'. '
                'This historical project review does not demonstrate effectiveness of current FONGIM/OCHA actors or coverage of current needs; recommendations are experience-based hypotheses for context review.',
                'IEG P144442 — '+p['finding_kind'],'IEG evaluation and learning'))
    return results[:limit]


def publish_project_learning_logged():
    try:
        logging.getLogger('mkh.sources').info('project_learning_wave %s',json.dumps(publish_operational_snapshot(package())))
    except Exception as error:
        logging.getLogger('mkh.sources').warning('project_learning_wave publication_failed error_class=%s',type(error).__name__)
