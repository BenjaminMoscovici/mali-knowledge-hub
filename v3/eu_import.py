"""Replay a bounded EU evidence wave. Original source files stay outside git.

Facts retain money stage, historical period, country allocation and exact locators.
The IATI fallback export lacks transaction currency/date/kind; no money totals
are inferred from it. Source text and personal/site data are not redistributed.
"""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from analytical_import import Package

EU_NOTICE='https://commission.europa.eu/legal-notice_en'
C4_NOTICE='https://capacity4dev.europa.eu/legal_en'
MIP='https://international-partnerships.ec.europa.eu/document/download/b79ab8be-c041-4d28-bd0e-74d80e8217b1_en?filename=mip-2021-c2021-9376-mali-annex_fr.pdf'
COUNTRY='https://international-partnerships.ec.europa.eu/countries/mali_en'
ECHO='https://ec.europa.eu/echo/files/funding/hip2026/echo_-af_bud_2026_91000_ta_v5.pdf'


def fact(kind,locator,title,facts,start,end,stage='strategy_programming_intent',page=None,sectors=(),geography=None):
    return {'source_type':kind,'locator':locator,'page':page,'reference_start':start,'reference_end':end,
        'payload':{'title':title,'evidence_stage':stage,'facts':facts,'sectors':list(sectors),
            'geography':geography or {'country':'Mali'},'geo_resolution':{'matches':{},'issues':[]},
            'limitations':'Source intent/status is not confirmed delivery, coverage or impact. Geography is source scope, not an approved local administrative match.'}}


def ingest(directory,output):
    package=Package();asof='2026-10-02'
    def add(path,source,dataset,provider,title,url,version,records,limitations,granularity='national Mali; no approved local allocation',licence='CC BY 4.0 for EU-owned content; factual extraction and changes indicated',notice=EU_NOTICE,publication=None):
        package.add(directory/path,source,dataset,provider,title,url,licence,notice,version,records,limitations,granularity,publication)
    rows=[fact('eu_programming','PDF page 79 / NDICI annex introduction','Joint programming 2020–2024',
        {'participants':['EU','Germany','Belgium','Denmark','Spain','France','Italy','Luxembourg','Netherlands','Sweden','Czechia','Switzerland','Norway','EIB','Finland'],
         'participant_period':'historical 2020–2024; not current 2026 membership'},'2020-01-01','2024-12-31',page=79),
      fact('eu_programming','PDF page 87 / printed annex page 9 / section 7','NDICI 2021–2027 priorities and Mali plan alignment',
        {'axes':['state functioning','jobs for a green economy','essential human needs'],
         'explicit_plan_alignment':'CREDD and joint programming 2020–2024; does not establish alignment with later SNEDD or a specific PDSEC'},'2021-01-01','2027-12-31',page=87,sectors=['governance','employment','environment','education','health']),
      fact('eu_programming','PDF page 94 / printed annex page 16 / section 8 financial table','Original NDICI indicative 2021–2024 envelope',
        {'currency':'EUR','unit':'million','money_stage':'indicative_programming','state_functioning':150,'green_economy_jobs':135,'essential_human_needs':82,'support_measures':6,'total':373,
         'scope':'initial 2021–2024 only; not 2025–2027, a commitment, disbursement or implementation result'},'2021-01-01','2024-12-31',page=94)]
    add('doc0.pdf','eu-intpa','mli-eu-original-programming','European Commission DG INTPA','Mali joint programming and NDICI 2021–2027 annex',MIP,'C(2021)9376 annex; original programming',rows,['Original historical programme must be read alongside current EU overview and MTR. PDF has 140 pages; selected facts only.'])
    rows=[fact('eu_programming','Mali country page / Our partnership / priorities / retrieved snapshot','Current EU partnership overview',
        {'priorities':['direct support to population','young people','socio-economic development','territorial approach with focus on South'],
         'participants':['EU','Germany','Belgium','Spain','Italy','Netherlands','Switzerland'],'update_date':'webpage publication/update date unavailable'},asof,asof,sectors=['employment','environment','education','health']),
      fact('eu_programming','Mali country page / Our partnership / 2021–2024','EU-reported grant commitments 2021–2024',
        {'amount':151000000,'currency':'EUR','money_stage':'provider_reported_commitment','priorities':['growth and green economy','human development and young people'],
         'scope':'national grants committed in 2021–2024; not money disbursed; not a subtractable delivery gap against the original 373m'},'2021-01-01','2024-12-31',stage='financing_commitment'),
      fact('eu_programming','Mali country page / 2025–2027 complex settings','EU 2025–2027 approach',
        {'approach':'Mali funding through complex-settings approach for central Sahel',
         'priorities':['basic services','resilience','social cohesion','civic participation','prevention of violent extremism','climate response'],
         'money_stage':'no Mali-specific envelope reported here'},'2025-01-01','2027-12-31',sectors=['health','education','protection','environment'])]
    add('intpa.html','eu-intpa','mli-eu-current-overview','European Commission DG INTPA','EU Mali current partnership overview',COUNTRY,'Retrieved 2026-10-02; web update date unverified',rows,['Snapshot not verified publication date. Historical commitments and current programming intent are distinct.'])
    rows=[fact('eu_tei','Team Europe Actors / Proposal / infographic as of January 2022','Mali Environment and Climate Change TEI',
        {'priorities':['natural resources management','water and soils','green agriculture','renewable energy'],
         'participants':['EU','Belgium','Denmark','France','Germany','Italy','Luxembourg','Netherlands','Spain','Sweden','AFD','EIB','Proparco'],
         'source_phase':'design/proposal as of January 2022; current implementation unverified'},'2022-01-01','2022-01-31',sectors=['environment','wash','agriculture','energy'])]
    add('tei_environment.html','eu-team-europe','mli-eu-tei-environment','DG INTPA Team Europe Tracker','Mali environment/climate TEI factual metadata','https://capacity4dev.europa.eu/resources/team-europe-tracker/partner-countries/mali/mali-environment-and-climate-change_en','January 2022 design metadata',rows,['Historical initiative proposal; no confirmed budgets, delivery or reach.'],licence='Attributed factual metadata only; platform text/media not redistributed',notice=C4_NOTICE)
    rows=[fact('eu_tei','Team Europe Actors / Proposal / infographic as of January 2022','Mali Youth TEI',
        {'priorities':['vocational training access and quality','digitalisation','diversified training','jobs and professional integration','ministry capacity','decentralised vocational training'],
         'participants':['EU','Belgium','Czechia','Denmark','France','Germany','Italy','Luxembourg','Netherlands','Spain','AFD','BIO','EIB','FMO','Proparco'],
         'source_phase':'design/proposal as of January 2022; current implementation unverified'},'2022-01-01','2022-01-31',sectors=['education','employment','governance'])]
    add('tei_youth.html','eu-team-europe','mli-eu-tei-youth','DG INTPA Team Europe Tracker','Mali youth TEI factual metadata','https://capacity4dev.europa.eu/resources/team-europe-tracker/partner-countries/mali/mali-youth_en','January 2022 design metadata',rows,['Historical initiative proposal, not a current actor roster or verified project.'],licence='Attributed factual metadata only; platform text/media not redistributed',notice=C4_NOTICE)
    rows=[fact('eu_project_metadata','Project details / duration / budget / contract number','Mali-Centre pour la sécurité et le développement',
        {'contract_id':'T05-EUTF-REG-SAH-01-02','organisations':['SIPRI','Point Sud'],'funder':'European Union',
         'status':'Completed','start_date_reported':'2018-08-01','end_date_reported':'2023-12-31','budget':3000000,'currency':'EUR','money_stage':'reported_project_budget',
         'source_updated_at':'2026-09-09','purpose':'research on population priorities for security, governance and development','results':'no verified results extracted from current overview'},'2018-08-01','2023-12-31',stage='implementation_status_reported',sectors=['governance','research','protection'],geography={'country':'Mali','source_area':'central Mali; no commune list'})]
    add('c4_centre.html','eu-capacity4dev','mli-eu-capacity4dev-centre','SIPRI / Point Sud via Capacity4dev','Mali-Centre project factual metadata','https://capacity4dev.europa.eu/projects/mali-centre-pour-la-securite-et-le-developpement_en','Project overview updated 9 September 2026',rows,['One historical project only, platform-maintained status; budget not disbursement; no impact attributed.'],licence='Attributed factual metadata only; contributor text/media not redistributed',notice=C4_NOTICE,granularity='central Mali source label; no administrative crosswalk')
    for pid,title,signature,amount,total,promoter,sector in [
        ('20100250','KABALA AEP BAMAKO','2013-12-16',50000000,159000000,"SOCIETE MALIENNE DE PATRIMOINE DE L'EAU POTABLE",'wash'),
        ('20140756','KABALA II- EAU ET ASSAINISSEMENT BAMAKO','2017-06-08',50000000,182000000,"SOCIETE MALIENNE DE PATRIMOINE DE L'EAU POTABLE",'wash'),
        ('20180359','EDM - BOUCLE 225 KV NORD BAMAKO','2020-12-22',45000000,115000000,'ENERGIE DU MALI-SA','energy')]:
        rows=[fact('eib_project','Reference / Signed / Proposed EIB finance / Total cost / Promoter / Sector(s)',title,
            {'project_id':pid,'source_status':'Signed','signature_date':signature,'promoter':promoter,'proposed_finance_approximate':amount,
             'total_cost_approximate':total,'currency':'EUR','money_stage':'proposed_approximate_finance_on_signed_profile','closing_date':None,'approval_date':None,
             'scope':'Bamako project description; no arrondissements/communes assigned','results':None,'disbursements':None,
             'associated_documents':'ESDS/ESIA titles and links on source profile; supporting contents not ingested'},signature,signature,stage='financing_signature',sectors=[sector],geography={'country':'Mali','source_city':'Bamako'})]
        rows[0]['payload']['geo_resolution']['issues']=[{'label':'Bamako','reason':'city_description_only_no_approved_administrative_unit_assignment'}]
        add('eib_'+pid+'.html','eib','mli-eib-'+pid,'European Investment Bank',title,'https://www.eib.org/en/projects/all/'+pid,'Signed profile; retrieved 2026-10-02',rows,['Selected three historical project profiles, not full Mali portfolio. No closing, disbursement, current delivery or verified results. Amount retains proposed approximate label even though profile status is Signed.'],licence='Small factual profile subset only; no copyrighted description/document redistribution',notice='https://www.eib.org/en/terms-of-use.htm',granularity='Bamako city description; no arrondissement/commune coverage')
    rows=[fact('echo_programming','PDF page 5 / section 2 / Mali row','DG ECHO Mali indicative allocation 2026 v5',
        {'humanitarian_aid_including_eie':30000000,'disaster_preparedness':2000000,'total':32000000,'currency':'EUR',
         'money_stage':'indicative_country_allocation','regional_hip_total':276000000,'regional_total_scope':'West and Central Africa, not Mali',
         'conditions':'Commission may not allocate all funds and may use regional/plurinational approaches; not project grants or disbursements'},'2026-01-01','2026-12-31',page=5),
      fact('echo_programming','PDF page 28 / section 5.5 Mali','DG ECHO Mali targeting and food-security priorities 2026',
        {'priorities':['conflict-driven acute needs','newly displaced people','populations without basic services','least-covered and inaccessible areas','protection at centre of assistance'],
         'food_security_targeting':'CH phase 4 priority and CH/IPC phase 3 with aggravating factors; household targeting required, not automatic area-level beneficiary count',
         'methodology':'needs-based targeting; CH labels not casually reclassified as IPC'},'2026-01-01','2026-12-31',page=28,sectors=['food_security','protection']),
      fact('echo_programming','PDF page 29 / section 5.5 Mali','DG ECHO displacement, education and WASH programming',
        {'priorities':['rapid response for newly displaced','out-of-school crisis-affected children including host communities','safe and inclusive education','water access and sanitation with protection/conflict sensitivity'],
         'results':'targeting instructions, not measured beneficiary reach'},'2026-01-01','2026-12-31',page=29,sectors=['displacement','education','wash']),
      fact('echo_programming','PDF page 30 / section 5.5 Mali','DG ECHO shelter, protection, health and nutrition programming',
        {'priorities':['newly displaced and vulnerable host families for shelter','extreme-risk protection cases','health services in high-risk areas','nutrition and referrals','gender-based violence survivor assistance'],
         'results':'programming priorities, not demonstrated delivery'},'2026-01-01','2026-12-31',page=30,sectors=['shelter','protection','health','nutrition'])]
    add('echo_annex.pdf','eu-echo','mli-echo-hip2026-v5','European Commission DG ECHO','West and Central Africa HIP2026 technical annex v5 — Mali subset',ECHO,'Version 5, 16 September 2026',rows,['Mali allocation 32m EUR is indicative. Whole HIP 276m EUR covers region. Partner lists for funding cycles are eligible/existing partners, not verified grants. No HIP project-level delivery/results.'],publication='2026-09-16')
    # Reuse the legitimately retrieved same-day public HDX export. Its mtime
    # remains the successful retrieval time, not the time of a failed refresh.
    meta=json.loads((directory/'iati_metadata.json').read_text());resource=meta['resources'][0]
    groups=defaultdict(list)
    for n,v in enumerate(csv.DictReader((directory/'iati_mali.csv').open(encoding='utf-8')),2):
        if v['reporting_ref'] in ('XI-IATI-EC_INTPA','XI-IATI-EC_ECHO') and v['country_code']=='Mali' and v['country_percent']=='100.0':
            groups[(v['reporting_ref'],parse_qs(urlparse(v['aid']).query)['aid'][0])].append((n,v))
    rows=[]
    for (publisher,aid),g in sorted(groups.items()):
        v=g[0][1]
        if any(any(w[k]!=v[k] for k in ('title','status_code','day_start','day_end','commitment','spend')) for _,w in g):raise ValueError('Conflicting repeated IATI activity facts')
        if not aid.startswith(publisher+'-'):raise ValueError('Publisher/identifier mismatch')
        r=fact('eu_activity','iati-activities-in-mali-no-location-information.csv / rows '+','.join(str(n) for n,_ in g),v['title'],
            {'activity_id':aid,'publisher_ref':publisher,'status':v['status_code'],'start_date_reported':v['day_start'] or None,
             'end_date_reported':v['day_end'] or None,'date_type':'planned/actual not preserved in fallback CSV; source-reported only',
             'country_percent_reported':100,'funder_refs':sorted({w['funder_ref'] for _,w in g}),
             'implementing_organisations':None,'participating_organisations':None,'linked_documents':None,
             'source_sector_rows':len(g),'sector_labels':sorted({w['sector_code'] for _,w in g}),
             'sector_rows':[{'group':w['sector_group'],'label':w['sector_code'],'percent_reported':w['sector_percent']} for _,w in g],
             'financial_raw':{k:v[k] for k in ('commitment','spend','commitment_eur','spend_eur')},
             'financial_unit_status':'Fallback CSV lacks original currency, transaction types, value dates and hierarchy. Raw totals are not verified commitments/disbursements; not displayed as money.',
             'money_stage':'unverified_export_totals_not_analytical_amounts','geography_scope':'100% source country allocation; no local locations in this export',
             'results':None},asof,asof,stage='activity_registry_status')
        r['payload']['limitations']='Self-reported activity registry status does not prove delivery. Start/end planned-vs-actual unknown. Subnational names in titles are mentions, not approved locations. Missing implementers, budgets, transactions, linked documents and results cannot be inferred.'
        rows.append(r)
    counts={p:sum(r['payload']['facts']['publisher_ref']==p for r in rows) for p in ('XI-IATI-EC_INTPA','XI-IATI-EC_ECHO')}
    if counts!={'XI-IATI-EC_INTPA':134,'XI-IATI-EC_ECHO':172}:raise ValueError('Review changed publisher/country subset')
    add('iati_mali.csv','eu-iati','mli-eu-iati-fallback','DG INTPA / DG ECHO through IATI HDX export','Mali EU IATI country activity subset',resource['url'],'HDX snapshot retrieved 2 October 2026; export updated '+resource['last_modified'],rows,
        ['134 INTPA + 172 ECHO exact-country activities, identifier deduplication. 37 ECHO multi-country allocations excluded.',
         'Publisher XML routes currently time out; successful same-day HDX retrieval used. Subsequent refresh timeout did not alter retrieval date.',
         'No financial analysis from unverified CSV totals or date-type conversion. No implementer/partner or linked-document reconstruction.'],licence='EU-owned factual activity metadata; EC attribution/reuse notice; full export and third-party descriptions not redistributed')
    package.save(output)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();ingest(args.directory,args.output)
