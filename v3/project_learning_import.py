"""World Bank project facts, deduplicated WB IATI and small IEG findings."""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from analytical_import import Package

WB_API='https://search.worldbank.org/api/v3/projects?format=json&qterm=Mali&rows=500&fl=id,project_name,countryshortname,projectstatusdisplay,status,boardapprovaldate,closingdate,totalamt,curr_total_commitment,borrower,impagency,sector_namecode,sector1,p2a_updated_date,projectdocs'
IEG_URL='https://documents1.worldbank.org/curated/en/099090624032518175/pdf/P144442-9238b018-2490-4f90-b1e6-f992f61c90ca.pdf'


def ingest(directory,output):
    package=Package()
    raw=json.loads((directory/'worldbank_mali_v3.json').read_text())
    projects=[p for p in raw['projects'].values() if p.get('countryshortname')=='Mali']
    if len(projects)!=215 or len({p['id'] for p in projects})!=215:
        raise ValueError('WB selected-country scope changed')
    asof=datetime.fromtimestamp((directory/'worldbank_mali_v3.json').stat().st_mtime,timezone.utc).date().isoformat()
    records=[]
    for p in projects:
        flags=[];closing=p.get('closingdate');approval=(p.get('boardapprovaldate') or '')[:10] or None
        if closing and closing<asof and p['status']=='Active':flags.append('active_label_with_past_closing_date')
        if approval and approval>asof:flags.append('future_board_date_planned_not_approved')
        if not p.get('p2a_updated_date'):flags.append('project_level_update_date_unavailable')
        payload={'project_id':p['id'],'title':p['project_name'],'country':'Mali','status':p['status'],
            'board_date_reported':approval,'closing_date_reported':closing,'borrower':p.get('borrower'),
            'implementing_agency':p.get('impagency'),'project_updated_at':p.get('p2a_updated_date'),
            'financial_raw':{k:p.get(k) for k in ('totalamt','curr_total_commitment')},
            'financial_unit_status':'API export has no explicit currency/unit field; values retained raw, not exposed as verified money',
            'sector':None,'geography':{'country':'Mali'},'flags':flags,
            'limitations':'Country-level project profile only. Regional/multicountry projects excluded. Active is source status, not verified delivery; missing closing date is not indefinite activity. No local geography, actual reach or impact in this selected export.'}
        records.append({'source_type':'development_project','reference_start':asof,'reference_end':asof,
            'locator':f'World Bank v3 API / projects / {p["id"]}', 'payload':payload})
    package.add(directory/'worldbank_mali_v3.json','world-bank-projects','mli-world-bank-v3','World Bank',
        'World Bank Projects and Operations — exact Mali country profiles',WB_API,'CC BY 4.0 (World Bank open data)',
        'https://datacatalog.worldbank.org/search/dataset/0037800/world-bank-projects-operations',
        'v3 API snapshot '+asof,records,
        ['215 exact-Mali profiles; 62 regional/multicountry search hits excluded.',
         'Source status/date conflicts retained. Project-level update dates missing in most profiles; retrieval does not make old fields current.',
         'Financial API fields retained raw until units validated; not disbursements. No commune/cercle locations in selected export.'],
        'country project profile only')
    meta=json.loads((directory/'iati_metadata.json').read_text());resource=meta['resources'][0]
    groups=defaultdict(list)
    with (directory/'iati0.csv').open(encoding='utf-8',newline='') as file:
        for row,v in enumerate(csv.DictReader(file),2):
            if v['reporting_ref']=='44000' and v['country_code']=='Mali':
                aid=parse_qs(urlparse(v['aid']).query)['aid'][0]
                if not re.fullmatch(r'44000-P\d{6}',aid):raise ValueError('Unknown WB IATI identifier')
                groups[aid].append((row,v))
    if len(groups)!=36 or sum(len(g) for g in groups.values())!=136:raise ValueError('WB IATI subset changed')
    records=[]
    for aid,group in sorted(groups.items()):
        first=group[0][1]
        fixed=('title','status_code','day_start','day_end','commitment','spend','country_percent')
        if any(any(v[k]!=first[k] for k in fixed) for _,v in group):raise ValueError('Repeated IATI activity facts conflict')
        records.append({'source_type':'aid_activity','reference_start':asof,'reference_end':asof,
            'locator':'iati-activities-in-mali-no-location-information.csv / rows '+','.join(str(n) for n,_ in group),
            'payload':{'activity_id':aid,'project_id':aid.split('-',1)[1],'publisher':'World Bank','publisher_ref':'44000',
                'title':first['title'],'status':first['status_code'],'start_date_reported':first['day_start'] or None,
                'end_date_reported':first['day_end'] or None,'country':'Mali','country_percent_reported':first['country_percent'],
                'funder_refs':sorted({v['funder_ref'] for _,v in group}),
                'sectors':[{'group':v['sector_group'],'label':v['sector_code'],'percent_reported':v['sector_percent']} for _,v in group],
                'financial_raw':{k:first[k] for k in ('commitment','spend','commitment_eur','spend_eur','commitment_gbp','spend_gbp','commitment_cad','spend_cad')},
                'financial_unit_status':'Default commitment/spend currency and conversion period not explicit in selected export; raw values not exposed as verified transactions/disbursements',
                'geography':{'country':'Mali'},'source_sector_rows':len(group),
                'limitations':'Self-reported activity record. Deduplicated by exact IATI activity ID; repeated sector rows are not additional financing. No approved subnational location. Project-ID link is identity, not evidence of outcomes. Wider publishers and questionable location export excluded.'}})
    package.add(directory/'iati0.csv','iati-worldbank','mli-iati-worldbank','World Bank / IATI via HDX',
        'Mali IATI — World Bank publisher 44000 activity subset',resource['url'],
        'World Bank open-data attribution policy; WB factual subset only',
        'https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets',
        'HDX export updated '+resource['last_modified'],records,
        ['36 activities from 136 sector rows; exact identifier deduplication; no sector-level financial summation.',
         'Only World Bank publisher 44000, not complete IATI Mali. Other publisher licences unreviewed.',
         'Questionable coordinates and descriptions omitted. Raw financial fields await unit/transaction validation.'],
        'country activity only',metadata_url='https://data.humdata.org/dataset/'+meta['id'])
    # Under 180 words of findings, paraphrased; no original document/full text redistribution.
    findings=[
        ('results',9,'IEG reports productive assets remaining in use at 86%, below the revised 95% target. Some beneficiary totals include double counting; reported Konna benefits lack supporting data.'),
        ('constraints',11,'IEG rates outcome Moderately Satisfactory and efficiency Modest. Insecurity, procurement delays, COVID-19 and suspended disbursements delayed delivery; closing was extended by almost four years.'),
        ('recommendations',17,'Lessons support participatory local plans and experienced local monitoring partners. Third-party capacity and procurement delays require assessment. These are project-experience lessons, not experimental proof of effectiveness.')]
    records=[]
    for kind,page,finding in findings:
        records.append({'source_type':'evaluation_finding','reference_start':'2013-12-06','reference_end':'2022-12-31','page':page,
            'locator':f'IEG ICRR0023565 / P144442 / PDF page {page}',
            'payload':{'project_id':'P144442','finding_kind':kind,'finding':finding,'page':page,
                'methodology':'Independent desk-based ICR validation; retrospective project evidence',
                'geography':{'country':'Mali'},'transferability':'Historical Mali reconstruction project, including Konna/Mopti. No counterfactual attribution; no automatic transfer to current actors, communes or 2026 needs. Source ICR quality rated High, while some outcome indicators remain limited.',
                'document_title':'IEG Implementation Completion Report Review — Mali Reconstruction and Economic Recovery (P144442)'}})
    package.add(directory/'p144442_ieg.pdf','worldbank-ieg','mli-ieg-p144442','World Bank Independent Evaluation Group',
        'IEG P144442 — small historical findings collection',IEG_URL,
        'Public factual findings/paraphrases only; full-text reproduction rights not assumed',IEG_URL,
        'ICRR0023565; project 2013–2022; document publication date unverified',records,
        ['One project review and three short findings with exact PDF pages; not an evaluation repository.',
         'No causal attribution, current-project endorsement or unrestricted full-text redistribution.',
         'Recommendations reflect this project experience; transferability requires current-context checks.'],
        'historical Mali project; Konna/Mopti context only')
    package.save(output)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();ingest(args.directory,args.output)
