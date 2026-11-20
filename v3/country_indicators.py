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
    if not re.search(r'\b(?:mali|malien(?:ne)?s?)\b',q):return None
    agriculture = bool(re.search(r'\b(agricultur\w*|landwirtschaft\w*)\b', q))
    employment = bool(re.search(r'\b(employment|emploi|beschaftig\w*)\b', q))
    gdp = bool(re.search(r'\b(gdp|pib|bruttoinlandsprodukt)\b', q))
    sector_pair = agriculture and employment and gdp
    electricity = bool(re.search(r'\b(electricity|electrification|electricite|strom\w*)\b', q))
    rural = bool(re.search(r'\brural\w*\b', q))
    urban = bool(re.search(r'\b(?:urban|urbain)\w*\b', q))
    residence_pair = electricity and rural and urban
    water_definition_comparison = bool(re.search(
        r'\b(difference|distinguish|distinguer|distingue|differe\w*)\b', q
    ) and re.search(r'\b(basic|de base|minimal)\b', q)
      and re.search(r'\b(safely managed|gere\w* en toute securite)\b', q))
    lookup = re.sub(r'\b(?:latest available|derniere annee disponible|cite (?:les donnees|the data))\b', '', q)
    if water_definition_comparison:
        lookup = re.sub(r'\bgere\w* en toute securite\b', '', lookup)
    if sector_pair or water_definition_comparison or residence_pair:
        lookup = re.sub(r'\b(?:compar\w*|versus|vs)\b', '', lookup)

    if re.search(r'\b(regions?|cercles?|communes?|localit\w*|villages?|'
        r'conflict\w*|security|securite|humanitar\w*|politic\w*|displace\w*|deplace\w*|'
        r'projects?|projets?|funding|financement|why|pourquoi|impact|priorit\w*|recommend\w*|'
        r'hub|datasets?|sources?|available|compare|compar\w*|versus|vs|forecast\w*|predict\w*|prevision\w*|population of|population du|population de)\b',lookup):return None
    # A national indicator must not answer a place-specific question mentioning Mali.
    if any(n not in {'mali','what','which','are','the','and','how','les','des','pour','une','dans','rural','urban'}
           for n in geographic_model().retrieval_place_names(question)):return None
    codes=[]
    if gdp and not agriculture:
        codes.append('NY.GDP.PCAP.CD' if re.search(r'\b(per capita|par habitant|pro kopf)\b',q) else 'NY.GDP.MKTP.CD')
    if residence_pair:
        codes.extend(("EG.ELC.ACCS.UR.ZS", "EG.ELC.ACCS.RU.ZS"))
        if re.search(r'\b(?:national (?:rate|value|share|figure|average)|taux national|moyenne nationale)\b', q):
            codes.append("EG.ELC.ACCS.ZS")
    elif electricity:
        codes.append('EG.ELC.ACCS.RU.ZS' if rural else
                     'EG.ELC.ACCS.UR.ZS' if urban else 'EG.ELC.ACCS.ZS')
    if re.search(r'\b(drinking water|eau potable|trinkwasser)\b',q):codes.append('SH.H2O.BASW.ZS')
    if re.search(r'\b(sanitation|assainissement|sanitar\w*)\b',q):codes.append('SH.STA.BASS.ZS')
    if re.search(r'\b(forest\w*|foret\w*|wald\w*)\b',q):codes.append('AG.LND.FRST.ZS')
    if agriculture:
        if employment: codes.append('SL.AGR.EMPL.ZS')
        if gdp: codes.append('NV.AGR.TOTL.ZS')
        if not employment and not gdp:
            codes.append('AG.LND.AGRI.ZS' if re.search(r'\b(land|terres|flache\w*)\b',q) else 'NV.AGR.TOTL.ZS')
    if re.search(r'\b(enrol\w*|scolarisation|einschul\w*)\b',q):
        codes.append('SE.SEC.ENRR' if re.search(r'\b(second\w*|sekundar\w*)\b',q) else 'SE.PRM.ENRR')
    if re.search(r'\b(primary completion|achevement du primaire|primarschulabschluss)\b',q):codes.append('SE.PRM.CMPT.ZS')
    if re.search(r'\b(hospital beds|lits d hopital|krankenhausbetten)\b',q):codes.append('SH.MED.BEDS.ZS')
    if re.search(r'\b(reported land area|land area|superficie terrestre|landflache)\b',q):codes.append('AG.LND.TOTL.K2')
    if not codes:return None
    if residence_pair and any(not code.startswith("EG.ELC.ACCS.") for code in codes):
        return None
    # Explicitly unsupported definitions must never be silently relaxed.
    unsupported=bool(re.search(r'\b(safely managed|gere\w* en toute securite|continuous|fiabilite|reliability|constant|real gdp|constant prices|inflation adjusted|constant dollars|net enrol\w*|net d inscription|taux net|attendance)\b',q))
    if water_definition_comparison and codes == ['SH.H2O.BASW.ZS']:
        unsupported = False
    return {'metric':'indicator','compare_residence':residence_pair,'compare_water_definitions':water_definition_comparison,
            'compare_sector_shares':sector_pair,'codes':list(dict.fromkeys(codes)),
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
    years = plan["years"]
    if plan["compare_residence"] and not years and not plan["time_series"]:
        series = indicator_query(plan["codes"], time_series=True)["series"]
        common = set.intersection(*[{row["year"] for row in entry["observations"]
                                     if row["value"] is not None} for entry in series])
        if common:
            years = [max(common)]
        else:
            return {"answer": tr("The stored series have no shared observation year.",
                                 "Les séries enregistrées n’ont aucune année d’observation commune.",
                                 "Die gespeicherten Reihen haben kein gemeinsames Beobachtungsjahr."),
                    "evidence": [], "country": {"status": "no_common_year"}}
    data = indicator_query(plan["codes"], years, plan["time_series"])
    evidence = indicator_evidence(data)
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
    if plan["compare_residence"]:
        urban, rural = ({o["year"]: o["value"] for o in series["observations"] if o["value"] is not None}
                        for series in data["series"][:2])
        lines += ["", tr(
            "Urban and rural percentages use their respective populations. The national percentage, if shown, is a separate observation. [E01, E02]",
            "Les taux urbain et rural ont pour dénominateur leur population respective. Le taux national, s’il est affiché, est une observation distincte. [E01, E02]",
            "Die Stadt- und Landanteile beziehen sich auf die jeweilige Bevölkerung. Der nationale Anteil ist eine eigene Beobachtung. [E01, E02]")]
        for year in sorted(urban.keys() & rural.keys()):
            formula = f"{urban[year]:.3f} − {rural[year]:.3f} ≈ {urban[year] - rural[year]:.3f}"
            lines.append(tr(f"- {year} urban minus rural: {formula} percentage points. [E01, E02]",
                            f"- {year}, taux urbain moins taux rural : {formula} points de pourcentage. [E01, E02]",
                            f"- {year}, Stadt minus Land: {formula} Prozentpunkte. [E01, E02]"))
    if plan['compare_sector_shares']:
        lines += ['', tr('Employment uses total employment as its denominator. Value added uses GDP and includes agriculture, forestry and fishing. These shares describe different quantities, even in the same year. [E01, E02]',
            'L’emploi a pour dénominateur l’emploi total. La valeur ajoutée a pour dénominateur le PIB et inclut l’agriculture, la sylviculture et la pêche. Ces parts mesurent des grandeurs différentes, même pour la même année. [E01, E02]',
            'Die Nenner sind die Gesamtbeschäftigung und das BIP. Die Wertschöpfung umfasst Landwirtschaft, Forstwirtschaft und Fischerei. Die Anteile messen auch im selben Jahr verschiedene Größen. [E01, E02]')]
    if plan['compare_water_definitions'] and plan['codes'] == ['SH.H2O.BASW.ZS']:
        evidence.append({'evidence_id':'E02', 'source_type':'indicator_methodology',
            'source_family':'WHO/UNICEF Joint Monitoring Programme', 'organization':'WHO/UNICEF',
            'document_title':'JMP drinking water service ladder', 'locator':'Drinking water service ladder',
            'source_endpoint':'https://washdata.org/monitoring/drinking-water',
            'content':'Safely managed: improved source accessible on premises, available when needed, and free from faecal and priority chemical contamination. Basic: improved source with collection within 30 minutes round trip.'})
        lines += ['', tr('Basic drinking water uses an improved source with a round trip of no more than 30 minutes. Safely managed adds on-premises access, availability when needed and freedom from contamination. The reported share is for at least basic service. [E01, E02]',
            'Un service de base utilise une source améliorée accessible en 30 minutes aller-retour au maximum. Un service géré en toute sécurité exige une source sur place, disponible quand nécessaire et exempte de contamination. La proportion citée concerne un service au moins de base. [E01, E02]',
            'Die Grundversorgung nutzt eine verbesserte Quelle mit höchstens 30 Minuten für Hin- und Rückweg. Eine sichere Versorgung erfordert eine Quelle vor Ort, bedarfsgerechte Verfügbarkeit und Schadstofffreiheit. Der Anteil gilt für mindestens die Grundversorgung. [E01, E02]')]
    return {'answer':'\n'.join(lines),'evidence':evidence,'country':data,
            'family_counts':{'World Bank WDI country foundation':len(evidence)}}
