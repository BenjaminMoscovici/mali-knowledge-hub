"""Allowlisted national WDI facts; no inferred subnational observations."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re

from geographic_model import geographic_model
from source_wave import _fold

PACKAGE=Path(__file__).with_name('country_indicators.json.gz')


@lru_cache(maxsize=1)
def indicator_package():
    with gzip.open(PACKAGE,'rt',encoding='utf-8') as source:package=json.load(source)
    if package['country_iso3']!='MLI':raise ValueError('Wrong national indicator snapshot')
    return package


def indicator_plan(question):
    q=_fold(question)
    if not re.search(r'\bmali\b',q):return None
    if re.search(r'\b(regions?|cercles?|communes?|localit\w*|villages?|'
        r'conflict\w*|security|securite|humanitar\w*|politic\w*|displace\w*|deplace\w*|'
        r'projects?|projets?|funding|financement|why|pourquoi|impact|priorit\w*|recommend\w*|'
        r'hub|datasets?|sources?|available|compare|compar\w*|versus|vs|forecast\w*|predict\w*|prevision\w*|population of|population du|population de)\b',q):return None
    # A national indicator must not answer a place-specific question mentioning Mali.
    if any(n not in {'mali','what','which','are','the','and','how','les','des','pour','une','dans','rural','urban'}
           for n in geographic_model().retrieval_place_names(question)):return None
    codes=[]
    if re.search(r'\b(gdp|pib|bruttoinlandsprodukt)\b',q):
        codes.append('NY.GDP.PCAP.CD' if re.search(r'\b(per capita|par habitant|pro kopf)\b',q) else 'NY.GDP.MKTP.CD')
    if re.search(r'\b(electricity|electrification|electricite|strom\w*)\b',q):
        codes.append('EG.ELC.ACCS.RU.ZS' if re.search(r'\brural\w*\b',q) else
                     'EG.ELC.ACCS.UR.ZS' if re.search(r'\burban\w*\b',q) else 'EG.ELC.ACCS.ZS')
    if re.search(r'\b(drinking water|eau potable|trinkwasser)\b',q):codes.append('SH.H2O.BASW.ZS')
    if re.search(r'\b(sanitation|assainissement|sanitar\w*)\b',q):codes.append('SH.STA.BASS.ZS')
    if re.search(r'\b(forest\w*|foret\w*|wald\w*)\b',q):codes.append('AG.LND.FRST.ZS')
    if re.search(r'\b(agricultur\w*|landwirtschaft\w*)\b',q):
        codes.append('SL.AGR.EMPL.ZS' if re.search(r'\b(employment|emploi|beschaftig\w*)\b',q) else
                     'AG.LND.AGRI.ZS' if re.search(r'\b(land|terres|flache\w*)\b',q) else 'NV.AGR.TOTL.ZS')
    if re.search(r'\b(enrol\w*|scolarisation|einschul\w*)\b',q):
        codes.append('SE.SEC.ENRR' if re.search(r'\b(second\w*|sekundar\w*)\b',q) else 'SE.PRM.ENRR')
    if re.search(r'\b(primary completion|achevement du primaire|primarschulabschluss)\b',q):codes.append('SE.PRM.CMPT.ZS')
    if re.search(r'\b(hospital beds|lits d hopital|krankenhausbetten)\b',q):codes.append('SH.MED.BEDS.ZS')
    if re.search(r'\b(reported land area|land area|superficie terrestre|landflache)\b',q):codes.append('AG.LND.TOTL.K2')
    if not codes:return None
    # Explicitly unsupported definitions must never be silently relaxed.
    unsupported=bool(re.search(r'\b(safely managed|gere\w* en toute securite|continuous|fiabilite|reliability|constant|real gdp|constant prices|inflation adjusted|constant dollars|net enrol\w*|net d inscription|taux net|attendance)\b',q))
    return {'metric':'indicator','codes':list(dict.fromkeys(codes)),
            'years':[int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',q)],
            'time_series':bool(re.search(r'\b(trend\w*|evolution|time series|tendance\w*|zeitreihe|depuis|since)\b',q)),
            'unsupported_definition':unsupported}


def indicator_query(codes,years=None,time_series=False):
    package=indicator_package();series={s['indicator_id']:s for s in package['series']}
    if not codes or any(c not in series for c in codes):raise ValueError('Unknown indicator')
    results=[]
    for code in codes:
        s=series[code]
        available=[o for o in s['observations'] if o['value'] is not None]
        if years:
            indexed={o['year']:o for o in s['observations']}
            selected=[indexed.get(y,{'year':y,'value':None,'status':'outside_snapshot_window'}) for y in years]
            if time_series and len(years)==2:
                selected=[o for o in s['observations'] if min(years)<=o['year']<=max(years)]
        elif time_series:selected=s['observations']
        else:selected=[max(available,key=lambda o:o['year'])] if available else []
        results.append({'indicator_id':code,'name':s['metadata']['name'],'domain':s['domain'],
            'unit':s['unit'],'country_iso3':'MLI','observations':selected,
            'data_url':s['data_url'],'metadata_url':s['metadata_url'],
            'source_organization':s['metadata'].get('sourceOrganization'),
            'definition':s['metadata'].get('sourceNote'),
            'api_last_updated':s['api_header'].get('lastupdated'),'response_sha256':s['response_sha256']})
    return {'status':'ok','series':results,'retrieved_at':package['retrieved_at'],
        'reference_window':package['reference_window'],'geographic_framework':package['geographic_framework'],
        'limitations':package['limitations']}


def indicator_evidence(data):
    evidence=[]
    for i,series in enumerate(data['series'],1):
        observations=series['observations'];years=[o['year'] for o in observations]
        evidence.append({'evidence_id':f'E{i:02d}','source_type':'official_country_indicator',
            'source_family':'World Bank WDI country foundation','organization':'World Bank WDI; underlying provider retained in source metadata',
            'document_title':series['name'],'record_id':series['indicator_id'],
            'source_endpoint':f"https://data.worldbank.org/indicator/{series['indicator_id']}?locations=ML",
            'retrieved_at':data['retrieved_at'],'version':'WDI API update '+str(series['api_last_updated']),
            'reference_period_start':f'{min(years)}-01-01' if years else None,
            'reference_period_end':f'{max(years)}-12-31' if years else None,
            'locator':'Indicator '+series['indicator_id']+'; MLI; years '+', '.join(map(str,years)),
            'geographic_scope':'Mali — WDI national reporting geography only',
            'content':json.dumps({'series':series,'limitations':data['limitations'],
                                  'reference_window':data['reference_window']},ensure_ascii=False)})
    return evidence


def indicator_answer(question,language='English'):
    plan=indicator_plan(question)
    if not plan:return None
    fr=language=='French';de=language=='German'
    def tr(en,frs,des):return des if de else frs if fr else en
    if plan['unsupported_definition']:
        return {'answer':tr('The stored indicator does not match that definition. Basic WASH is different from safely managed WASH; electricity access does not measure reliability; GDP is stored in current US dollars.',
            'L’indicateur enregistré ne correspond pas à cette définition. Les services WASH de base diffèrent des services gérés en toute sécurité; l’accès à l’électricité ne mesure pas sa fiabilité; le PIB est en dollars courants.',
            'Der gespeicherte Indikator entspricht dieser Definition nicht. Basis-WASH unterscheidet sich von sicher bewirtschafteten Diensten; Stromzugang misst keine Zuverlässigkeit; das BIP liegt in laufenden US-Dollar vor.'),
            'evidence':[],'country':{'status':'unsupported_indicator_definition'}}
    data=indicator_query(plan['codes'],plan['years'],plan['time_series']);evidence=indicator_evidence(data)
    lines=[tr('For **Mali nationally**, the stored World Development Indicators report:',
              'Pour **le Mali au niveau national**, les World Development Indicators enregistrés indiquent :',
              'Für **Mali auf nationaler Ebene** enthalten die gespeicherten World Development Indicators:')]
    for i,series in enumerate(data['series'],1):
        lines+=['',f"**{series['name']}** ({series['unit']})"]
        for o in series['observations']:
            value=f"{o['value']:,.3f}".rstrip('0').rstrip('.') if o['value'] is not None else tr('not reported','non renseigné','nicht angegeben')
            lines.append(f"- {o['year']}: **{value}**. [E{i:02d}]")
        if not series['observations']:lines.append(tr('No reported value in this snapshot window.','Aucune valeur renseignée dans cette fenêtre.','Kein gemeldeter Wert im Zeitfenster.'))
    lines+=['',tr('Each year is the observation year. Without a requested year, this shows the latest non-missing value within the stored window, not a measurement of today’s conditions. National values cannot establish conditions in a commune or at a facility.',
        'Chaque année est celle de l’observation. Sans année demandée, la dernière valeur non manquante de la fenêtre enregistrée est affichée; elle ne décrit pas nécessairement la situation actuelle. Les valeurs nationales ne décrivent pas une commune ou un établissement.',
        'Jedes Jahr bezeichnet das Beobachtungsjahr. Ohne Jahresangabe erscheint der jüngste vorhandene Wert im gespeicherten Zeitfenster, keine Messung der heutigen Lage. Nationale Werte belegen keine Verhältnisse in einer Gemeinde oder Einrichtung.')]
    return {'answer':'\n'.join(lines),'evidence':evidence,'country':data,
            'family_counts':{'World Bank WDI country foundation':len(evidence)}}
