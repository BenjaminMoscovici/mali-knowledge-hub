"""National, versioned climate normals with no runtime network/model calls."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re

from source_wave import _fold

PACKAGE = Path(__file__).with_name('country_climate.json.gz')
VARIABLES = ('pr', 'tas', 'tasmin', 'tasmax')
MONTHS = {
    'English': ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'),
    'French': ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'),
    'German': ('Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'),
}
LABELS = {
    'English': {'pr': 'Precipitation', 'tas': 'Mean temperature', 'tasmin': 'Average daily minimum temperature', 'tasmax': 'Average daily maximum temperature'},
    'French': {'pr': 'Précipitations', 'tas': 'Température moyenne', 'tasmin': 'Minimum quotidien moyen', 'tasmax': 'Maximum quotidien moyen'},
    'German': {'pr': 'Niederschlag', 'tas': 'Mittlere Temperatur', 'tasmin': 'Mittleres tägliches Temperaturminimum', 'tasmax': 'Mittleres tägliches Temperaturmaximum'},
}


@lru_cache(maxsize=1)
def climate_package():
    with gzip.open(PACKAGE, 'rt', encoding='utf-8') as source:
        package = json.load(source)
    if (package['dataset_id'] != 'mli-cckp-cru-ts4.09-1991-2020' or package['country_iso3'] != 'MLI'
            or len(package['observations']) != 52):
        raise ValueError('Wrong climate snapshot')
    return package


def climate_plan(question):
    q = _fold(question)
    if len(q) > 1500 or not re.search(r'\bmali\b', q):
        return None
    if not re.search(r'\b(climat\w*|klima\w*|temperatur\w*|rainfall|precipitation\w*|pluviometr\w*|niederschlag\w*|wettest|driest|warmest|coldest|hottest|coolest|warmste|kalteste|trockenste|nasseste)\b', q):
        return None
    # Explicit grammar keeps mixed analytics, unknown places and non-national
    # scopes on their established research routes. Never infer national scope
    # merely because the question mentions Mali.
    words = set(q.split())
    grammar = set(('what is are the of in for s and which how much does have give show me '
        'mali climate climat klima temperature temperatures temperatur temperaturen rainfall precipitation '
        'precipitations pluviometrie niederschlag niederschlage mean average daily minimum maximum '
        'monthly annual yearly normal normals climatology historical long term typical weather current today '
        'wettest driest warmest coldest hottest coolest month months rain rains '
        'quel quelle quels quelles est sont le la les du de des au en pour et a l '
        'moyen moyenne moyens moyennes quotidien quotidienne mensuel mensuelle mensuels mensuelles '
        'annuel annuelle annuels annuelles normales normale climatologie historique historiques '
        'plus moins chaud chaude froid froide pluvieux pluvieuse sec seche mois actuel actuelle '
        'actuels actuelles aujourd hui meteo donne donnez montrez '
        'wie ist sind das der die den dem des im von fur und mit hat welche welcher welches '
        'mittlere mittleren mittlerer durchschnittliche durchschnittlichen jahrlich jahrliche jahrlichen '
        'monatlich monatliche monatlichen langjahrige langjahrigen klimamittel klima normalwerte '
        'monat monate monaten warmste kalteste heisseste trockenste nasseste heute aktuell aktuelle '
        '1991 2020 celsius degrees degres grad mm millimetres millimeters').split())
    if any(word not in grammar and not re.fullmatch(r'(?:19|20)\d{2}', word) for word in words):
        return None
    years = [int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b', q)]
    unsupported = bool(years and sorted(years) != [1991, 2020]) or bool(re.search(
        r'\b(current|today|weather|actuel\w*|aujourd hui|meteo|heute|aktuell\w*)\b', q))
    precipitation = bool(re.search(r'\b(rainfall|precipitation\w*|pluviometr\w*|niederschlag\w*|wettest|driest|pluvieux|pluvieuse|sec|seche|trockenste|nasseste)\b', q))
    temperature = bool(re.search(r'\b(temperatur\w*|warmest|coldest|hottest|coolest|chaud\w*|froid\w*|warmste|kalteste|heisseste)\b', q))
    variables = []
    if precipitation: variables.append('pr')
    if temperature:
        extremes = []
        if re.search(r'\b(minimum|minimale)\b', q): extremes.append('tasmin')
        if re.search(r'\b(maximum|maximale)\b', q): extremes.append('tasmax')
        variables.extend(extremes or ['tas'])
    if not variables: variables = ['pr', 'tas']
    monthly = bool(re.search(r'\b(month\w*|mensuel\w*|mois|monat\w*|wettest|driest|warmest|coldest|hottest|coolest|warmste|kalteste|trockenste|nasseste)\b', q))
    return {'metric': 'climate', 'variables': variables, 'aggregation': 'both' if monthly else 'annual',
            'unsupported_period': unsupported}


def climate_query(variables=None, aggregation='both', period='1991-2020', month=None):
    variables = list(VARIABLES) if variables is None else variables
    if (not variables or any(v not in VARIABLES for v in variables) or len(set(variables)) != len(variables)
            or aggregation not in ('annual', 'monthly', 'both') or period != '1991-2020'
            or (month is not None and (type(month) is not int or not 1 <= month <= 12 or aggregation != 'monthly'))):
        raise ValueError('Unsupported climate selection')
    package = climate_package()
    rows = [dict(row) for row in package['observations'] if row['variable'] in variables
            and (aggregation == 'both' or row['aggregation'] == aggregation)
            and (month is None or row['month'] == month)]
    return {**{k: package[k] for k in ('dataset_id', 'country_iso3', 'source_version', 'reference_start', 'reference_end',
        'reference_period', 'retrieved_at', 'publication_date', 'grid_resolution_degrees', 'geographic_framework',
        'source_organization', 'source_page', 'upstream_page', 'attribution', 'license', 'license_url',
        'api_urls', 'response_sha256', 'limitations')},
        'status': 'ok', 'variables': {v: package['variables'][v] for v in variables}, 'observations': rows}


def climate_evidence(data):
    evidence = []
    for i, variable in enumerate(data['variables'], 1):
        metadata = data['variables'][variable]
        rows = [row for row in data['observations'] if row['variable'] == variable]
        content = [f"{data['source_version']}; Mali national climatology; {data['reference_period']}.",
                   metadata['label'] + ': ' + metadata['info'],
                   'Source values (' + metadata['unit'] + '):']
        content += [f"{row['aggregation']}; month={row['month']}; value={row['value']}; source coordinate={row['source_coordinate']}" for row in rows]
        content += ['API coordinates identify normal months, not single-year observations.',
                    'Response SHA256: ' + json.dumps(data['response_sha256'], sort_keys=True),
                    data['attribution'], *data['limitations']]
        evidence.append({'evidence_id': f'E{i:02d}', 'source_type': 'official_climate_climatology',
            'source_family': 'World Bank CCKP / CRU national climatology', 'organization': data['source_organization'],
            'document_title': metadata['label'].replace('\u200b', '') + ' — Mali 1991–2020 climate normal',
            'record_id': data['dataset_id'] + ':' + variable, 'source_endpoint': data['source_page'],
            'retrieved_at': data['retrieved_at'], 'version': data['source_version'],
            'reference_period_start': data['reference_start'], 'reference_period_end': data['reference_end'],
            'locator': f"MLI; {variable}; {data['reference_period']}; " + ', '.join(sorted({r['aggregation'] for r in rows})),
            'geographic_scope': data['geographic_framework'], 'content': '\n'.join(content)})
    return evidence


def climate_answer(question, language='English'):
    plan = climate_plan(question)
    if not plan: return None
    language = language if language in MONTHS else 'English'
    def tr(en, fr, de): return {'English': en, 'French': fr, 'German': de}[language]
    if plan['unsupported_period']:
        return {'answer': tr('The stored climate dataset covers **1991–2020 normals only**. It cannot establish current weather, conditions in a single year or a different climate reference period.',
            'Le jeu climatique enregistré couvre uniquement les **normales 1991–2020**. Il ne permet pas d’établir la météo actuelle, les conditions d’une seule année ou une autre période climatique.',
            'Der gespeicherte Klimadatensatz enthält ausschließlich **Klimamittel 1991–2020**. Er belegt weder aktuelles Wetter noch Verhältnisse eines einzelnen Jahres oder eines anderen Bezugszeitraums.'),
            'country': {'status': 'unsupported_climate_period'}, 'evidence': [], 'family_counts': {}}
    data = climate_query(plan['variables'], plan['aggregation'])
    evidence = climate_evidence(data); labels = LABELS[language]
    lines = [tr('For **Mali nationally**, the **1991–2020 climate normals** from World Bank CCKP / **CRU TS 4.09** report:',
        'Pour **le Mali au niveau national**, les **normales climatiques 1991–2020** de la Banque mondiale CCKP / **CRU TS 4.09** indiquent :',
        'Für **Mali auf nationaler Ebene** enthalten die **Klimamittel 1991–2020** der Weltbank CCKP / **CRU TS 4.09**:')]
    for i, variable in enumerate(plan['variables'], 1):
        annual = next(row for row in data['observations'] if row['variable'] == variable and row['aggregation'] == 'annual')
        unit = tr('mm/year', 'mm/an', 'mm/Jahr') if variable == 'pr' else '°C'
        lines.append(f"- {labels[variable]} ({tr('annual normal', 'normale annuelle', 'Jahresmittel')}): **{annual['value']:.2f} {unit}**. [E{i:02d}]")
    if plan['aggregation'] == 'both':
        lines += ['', '| ' + tr('Month', 'Mois', 'Monat') + ' | ' + ' | '.join(
            labels[v] + ' (' + data['variables'][v]['unit'] + f') [E{i:02d}]' for i, v in enumerate(plan['variables'], 1)) + ' |',
            '|' + '---|' * (len(plan['variables']) + 1)]
        indexed = {(r['variable'], r['month']): r['value'] for r in data['observations'] if r['aggregation'] == 'monthly'}
        for month in range(1, 13):
            lines.append('| ' + MONTHS[language][month-1] + ' | ' + ' | '.join(f'{indexed[v, month]:.2f}' for v in plan['variables']) + ' |')
        for i, variable in enumerate(plan['variables'], 1):
            high = max(range(1, 13), key=lambda m: indexed[variable, m])
            low = min(range(1, 13), key=lambda m: indexed[variable, m])
            lines += ['', f"{labels[variable]} — " + tr('highest monthly normal', 'normale mensuelle la plus élevée', 'höchstes Monatsmittel')
                + f": **{MONTHS[language][high-1]}**; " + tr('lowest', 'la plus faible', 'niedrigstes')
                + f": **{MONTHS[language][low-1]}**. [E{i:02d}]"]
    lines += ['', tr('These are long-term national averages, not current weather or conditions in a particular commune. Precipitation is accumulated mm per month/year; temperature maxima/minima are averages of daily values, not recorded extremes.',
        'Il s’agit de moyennes nationales de longue période, pas de la météo actuelle ni des conditions d’une commune. Les précipitations sont des cumuls en mm par mois/an; les maxima/minima de température sont des moyennes quotidiennes, pas des records.',
        'Dies sind langfristige nationale Mittelwerte, keine aktuellen Wetterdaten oder Gemeindewerte. Niederschlag ist die akkumulierte Menge in mm pro Monat/Jahr; Temperaturmaxima/-minima sind Mittel täglicher Werte, keine Rekorde.')]
    return {'answer': '\n'.join(lines), 'evidence': evidence, 'country': data,
            'family_counts': {'World Bank CCKP / CRU national climatology': len(evidence)}}
