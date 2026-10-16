"""Bounded physical-geography facts; precomputed, cited and source-separated."""
from collections import defaultdict
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re

from geographic_model import geographic_model
from source_wave import _fold

PACKAGE = Path(__file__).with_name('country_physical.json.gz')
RASTER = Path(__file__).with_name('country_terrain.tif')


@lru_cache(maxsize=1)
def physical_package():
    with gzip.open(PACKAGE, 'rt', encoding='utf-8') as source: package = json.load(source)
    model = geographic_model(); release = package['boundary_release_id']
    if (package['dataset_id'] != 'mli-physical-country-foundation-v1'
            or model.releases[release]['checksum'] != package['boundary_checksum']
            or any(model.units[row['unit_id']]['release_id'] != release for row in package['terrain'])):
        raise ValueError('Physical layer and boundary source mismatch')
    return package


def physical_plan(question):
    q = _fold(question)
    if len(q) > 1500: return None
    rivers = bool(re.search(r'\b(rivers?|fleuves?|rivieres?|flusse?|flussen)\b', q))
    terrain = bool(re.search(r'\b(elevation\w*|altitud\w*|topograph\w*|terrain|hohe|hohen\w*|wie hoch|highest point|lowest point|point culminant|hochste punkt)\b', q))
    if rivers == terrain: return None
    package = physical_package()
    known_places = {_fold(r['name']) for r in package['terrain']}
    names = sorted([name for name in known_places if name != 'mali' and re.search(r'\b'+re.escape(name)+r'\b',q)],key=q.find)
    if not re.search(r'\bmali\b', q) and not (terrain and names and re.search(r'\b(region\w*|district)\b',q)):
        return None
    grammar = set(('what which is are the of in for s and how much does have give show me '
        'mali map mapped mapping cartographic generalized generalised trace traces through flow flows '
        'river rivers main major name names list elevation elevations altitude altitudes topography topographic terrain '
        'average mean minimum maximum grid values value national nationally country '
        'region regions district commune communes cercle cercles locality localities '
        'compare comparison between with versus vs length long current currently today '
        'highest lowest point points summit summits peak peaks '
        'quel quelle quels quelles est sont le la les du de des au en pour et a l '
        'fleuve fleuves riviere rivieres principaux principales principal principale grands grandes liste noms traversent traverse cartographie cartographies '
        'moyen moyenne moyens moyennes minimal minimale maximal maximale grille valeurs '
        'nationale national pays comparer comparez entre avec longueur actuel actuelle '
        'plus haut haute bas basse point culminant sommet sommets '
        'wie ist sind das der die den dem des im von fur und mit hat welche welcher welches '
        'fluss flusse flussen fliessen fliesst kartiert kartierte kartierten '
        'hohe hohen mittlere mittleren durchschnittliche durchschnittlichen minimale maximale '
        'national land landes regionen bezirk vergleichen vergleich zwischen '
        'lang lange langste hoch hochste niedrigste punkt punkte gipfel heute aktuell durch '
        'metres meters metre meter m').split())
    for name in known_places: grammar.update(name.split())
    river_names = {_fold(r['name']) for r in package['rivers']}
    for name in river_names: grammar.update(name.split())
    if any(word not in grammar and not re.fullmatch(r'(?:19|20)\d{2}',word) for word in q.split()): return None
    unsupported_scope = bool(re.search(r'\b(communes?|cercles?|localit\w*)\b',q))
    if re.search(r'\b(district|bezirk)\b',q) and names != ['bamako']: unsupported_scope = True
    if rivers: unsupported_scope = unsupported_scope or bool(names) or bool(re.search(r'\b(region\w*)\b',q))
    unsupported_time = bool(re.search(r'\b(current\w*|today|actuel\w*|aujourd|heute|aktuell\w*)\b',q)
        or re.search(r'\b(?:19|20)\d{2}\b',q))
    unsupported_measure = (terrain and bool(re.search(r'\b(point\w*|peak\w*|summit\w*|sommet\w*|culminant|gipfel|punkt\w*)\b',q)))
    if rivers and re.search(r'\b(length|long|longueur|lang|lange|langste)\b',q) and not re.search(r'\b(mapped|trace\w*|cartograph\w*|kartiert\w*)\b',q):
        unsupported_measure = True
    return {'metric': 'physical_rivers' if rivers else 'terrain',
        'names': names if terrain else sorted([n for n in river_names if re.search(r'\b'+re.escape(n)+r'\b',q)],key=q.find),
        'level': 'region' if names or re.search(r'\b(region\w*)\b',q) else 'country',
        'unsupported_scope': unsupported_scope, 'unsupported_time': unsupported_time,
        'unsupported_measure': unsupported_measure}


def physical_query(metric, names=None, level='country', river_id=None):
    if metric not in ('terrain','physical_rivers') or level not in ('country','region'):
        raise ValueError('Unsupported physical selection')
    package = physical_package(); names = names or []
    if metric == 'terrain':
        if river_id: raise ValueError('River ID does not select terrain')
        indexed = {_fold(r['name']): r for r in package['terrain'] if r['level'] == level}
        folded = [_fold(name) for name in names]
        if folded and any(name not in indexed for name in folded):
            rows = []; status = 'unknown_requested_place'
        else:
            rows = [indexed[name] for name in folded] if folded else list(indexed.values()); status = 'ok'
        source = package['sources']['terrain']
    else:
        if level != 'country': raise ValueError('River layer supports national cartographic context only')
        groups = defaultdict(list)
        for row in package['rivers']: groups[row['river_id']].append(row)
        if river_id and river_id not in groups: raise ValueError('Unknown source river ID')
        folded = {_fold(name) for name in names}
        known = {_fold(r['name']) for r in package['rivers']}
        if folded - known: rows = []; status = 'unknown_requested_river'
        else:
            rows = [{'river_id': key, 'name': parts[0]['name'], 'source_record_ids': [p['source_record_id'] for p in parts],
                     'feature_classes': sorted({p['source_properties']['featurecla'] for p in parts}),
                     'clipped_cartographic_line_km': sum(p['clipped_line_km'] for p in parts)}
                for key, parts in groups.items() if (not folded or _fold(parts[0]['name']) in folded) and (not river_id or key == river_id)]
            rows.sort(key=lambda r: (_fold(r['name']), r['river_id']))
            status = 'same_name_distinct_rivers' if names and len(rows) > len(folded) else 'ok'
        source = package['sources']['rivers']
    return {'metric': metric, 'status': status, 'rows': rows, 'source': {k:v for k,v in source.items() if k != 'raw_metadata_das'},
        'retrieved_at': package['retrieved_at'], 'boundary_release_id': package['boundary_release_id'],
        'boundary_version': package['boundary_version'], 'boundary_checksum': package['boundary_checksum'],
        'quality': package['quality'], 'source_manifest': package['source_manifest']}


def river_geometry(name=None, river_id=None):
    data = physical_query('physical_rivers', [name] if name else None, river_id=river_id)
    ids = {row['river_id'] for row in data['rows']}; source = data['source']
    features = [{'type': 'Feature', 'id': row['source_record_id'], 'geometry': row['geometry'],
        'properties': {'name': row['name'], 'source_river_id': row['river_id'], 'source_version': 'Natural Earth 5.0.0',
            'feature_class': row['source_properties']['featurecla'], 'source_row': row['source_row'],
            'clipped_cartographic_line_km': row['clipped_line_km'],
            'clip_boundary_release_id': row['clip_boundary_release_id'], 'source_url': source['source_page'],
            'scale_denominator': source['scale_denominator'], 'precision_note': 'Generalized cartographic context; no commune/settlement relationship'}}
        for row in physical_package()['rivers'] if row['river_id'] in ids]
    return {'type': 'FeatureCollection', 'status': data['status'], 'features': features, 'limitations': source['limitations']}


def raster_path():
    if hashlib.sha256(RASTER.read_bytes()).hexdigest() != physical_package()['raster']['sha256']:
        raise ValueError('Terrain raster checksum mismatch')
    return RASTER


def physical_evidence(data):
    source = data['source']; terrain = data['metric'] == 'terrain'
    kind = 'NOAA modeled elevation' if terrain else 'Natural Earth cartographic rivers'
    records = ([f"{r['name']}; COD unit {r['unit_id']}; cells={r['cell_count']}; cell-area-weighted mean={r['cell_area_weighted_mean_m']} m; grid min={r['minimum_grid_value_m']} m; grid max={r['maximum_grid_value_m']} m"
                for r in data['rows']] if terrain else
               [f"{r['name']}; Natural Earth river ID {r['river_id']}; source records {', '.join(r['source_record_ids'])}; classes {', '.join(r['feature_classes'])}"
                for r in data['rows']])
    content = [source['attribution'], 'Version: '+source['version'],
        'Hub calculation/source selection record (not a verbatim publisher quotation):', *records, *source['limitations'],
        'Source response checksums: '+json.dumps({k:v['sha256'] for k,v in data['source_manifest']['files'].items()})]
    if terrain: content += ['Method: '+source['method'], 'Vertical datum: '+source['vertical_datum'],
        'Global input date range only: '+str(source['global_input_period'])+'; individual Mali cell dates not supplied.']
    else: content += ['Pinned source revision: '+source['source_revision']+'; row IDs identify source occurrences, not government codes.']
    evidence = [{'evidence_id': 'E01', 'source_type': 'official_elevation_model' if terrain else 'cartographic_reference',
        'source_family': kind, 'organization': source['provider'], 'document_title': source['version'],
        'record_id': source['dataset_id'], 'source_endpoint': source['source_page'], 'version': source['version'],
        'publication_date': source['publication_date'], 'retrieved_at': data['retrieved_at'],
        'reference_period_start': None, 'reference_period_end': None,
        'geographic_scope': 'COD v03 country/region mask only' if terrain else 'Mali national cartographic context only',
        'locator': '; '.join(row.get('unit_id', row.get('river_id','')) for row in data['rows']), 'content': '\n'.join(content)}]
    boundary = geographic_model().releases[data['boundary_release_id']]
    evidence.append({'evidence_id': 'E02', 'source_type': 'official_geography_registry', 'source_family': 'COD spatial calculation mask',
        'organization': boundary['provider'], 'document_title': boundary['title'], 'release_id': data['boundary_release_id'],
        'source_endpoint': boundary['source_url'], 'version': boundary['upstream_version'],
        'retrieved_at': boundary['retrieved_at'], 'publication_date': boundary['publication_date'],
        'reference_period_start': None, 'reference_period_end': None, 'geographic_scope': 'COD v03 country/region boundaries',
        'locator': 'Calculation mask: '+data['boundary_release_id'],
        'content': 'COD boundary mask for the stated physical calculation. Source SHA256: '+data['boundary_checksum']
            + '. This is not an INSTAT population identity match; no population or commune allocation is attached.'})
    return evidence


def physical_answer(question, language='English'):
    plan = physical_plan(question)
    if not plan: return None
    def tr(en, fr, de): return de if language == 'German' else fr if language == 'French' else en
    if plan['unsupported_scope'] or plan['unsupported_time'] or plan['unsupported_measure']:
        return {'answer': tr('The stored physical layers cannot establish that result. River data supports generalized national cartographic context. Terrain supports coarse COD region/country grid summaries, not surveyed peaks, commune conditions or current measurements. Official river lengths and local river relationships are not verified.',
            'Les couches physiques enregistrées ne permettent pas d’établir ce résultat. Les rivières fournissent un contexte cartographique national généralisé. Le relief permet des résumés de grille par région/pays COD, pas des sommets mesurés, des conditions communales ou des mesures actuelles. Les longueurs officielles et les relations locales des rivières ne sont pas vérifiées.',
            'Die gespeicherten physischen Ebenen belegen dieses Ergebnis nicht. Flussdaten dienen dem generalisierten nationalen Kartenkontext. Geländedaten erlauben grobe COD-Regions-/Landesrasterwerte, keine vermessenen Gipfel, Gemeindewerte oder aktuellen Messungen. Amtliche Flusslängen und lokale Flussbeziehungen sind nicht geprüft.'),
            'evidence': [], 'country': {'status': 'unsupported_physical_selection'}, 'family_counts': {}}
    data = physical_query(plan['metric'], plan['names'], plan['level'] if plan['metric'] == 'terrain' else 'country')
    if not data['rows']: return {'answer': tr('No matching physical source record.','Aucun enregistrement physique correspondant.','Kein passender physischer Quelldatensatz.'), 'evidence': [], 'country': data}
    if plan['metric'] == 'terrain':
        lines = [tr('**Modeled elevation**, using NOAA **ETOPO2022 v1, 60 arc-second** grid cells inside **COD v03** boundaries; heights in metres relative to **EGM2008**. [E01] [E02]',
            '**Altitude modélisée**, grille NOAA **ETOPO2022 v1, 60 secondes d’arc**, cellules à l’intérieur des limites **COD v03**; mètres par rapport à **EGM2008**. [E01] [E02]',
            '**Modellierte Höhe**, NOAA **ETOPO2022 v1, 60-Bogensekunden**-Raster innerhalb der **COD-v03**-Grenzen; Meter bezogen auf **EGM2008**. [E01] [E02]'), '',
            '| '+tr('Place','Lieu','Ort')+' | '+tr('Cell-area-weighted mean','Moyenne pondérée par surface des cellules','Nach Zellfläche gewichtetes Mittel')+' | '+tr('Grid minimum–maximum','Minimum–maximum de grille','Rasterminimum–maximum')+' |', '|---|---:|---:|']
        for row in data['rows']:
            label=row['name']+' (district)' if row['unit_type']=='district' else row['name']
            lines.append(f"| {label} | {row['cell_area_weighted_mean_m']:.1f} m | {row['minimum_grid_value_m']:.0f}–{row['maximum_grid_value_m']:.0f} m |")
        lines += ['', tr('The approximately 1.85 km north–south grid smooths local relief. These extrema are grid values, **not Mali’s surveyed highest/lowest points**. This composite product was published in 2022; input dates vary. No population or commune allocation is made.',
            'La grille d’environ 1,85 km nord–sud lisse le relief local. Ces extrêmes sont des valeurs de grille, **pas les points culminant/le plus bas mesurés du Mali**. Ce produit composite a été publié en 2022; les dates d’entrée varient. Aucune allocation de population ou de commune n’est effectuée.',
            'Das Raster mit rund 1,85 km Nord–Süd-Abstand glättet lokales Relief. Diese Extrema sind Rasterwerte, **nicht Malis vermessene höchste/tiefste Punkte**. Das Kompositprodukt wurde 2022 veröffentlicht; die Eingangsdaten sind unterschiedlich datiert. Keine Zuordnung zu Bevölkerung oder Gemeinden.')]
    else:
        lines = [tr('**Named rivers represented in the stored Natural Earth 5.0.0 layer**, clipped to the COD v03 Mali outline (1:10 million cartographic context). [E01] [E02]',
            '**Rivières nommées représentées dans la couche Natural Earth 5.0.0**, découpées par le contour COD v03 du Mali (contexte cartographique au 1:10 million). [E01] [E02]',
            '**Benannte Flüsse in der gespeicherten Natural-Earth-5.0.0-Ebene**, zugeschnitten auf den COD-v03-Umriss Malis (Kartenkontext 1:10 Millionen). [E01] [E02]'), '']
        counts = defaultdict(int)
        for row in data['rows']: counts[row['name']] += 1
        for row in data['rows']:
            suffix = f" — Natural Earth river ID {row['river_id']}" if counts[row['name']] > 1 else ''
            parts = ' ('+tr('includes a lake-centerline part','comprend une section de ligne médiane de lac','enthält einen See-Mittellinienabschnitt')+')' if 'Lake Centerline' in row['feature_classes'] else ''
            lines.append('- **'+row['name']+'**'+suffix+parts+'. [E01]')
        lines += ['', tr('This is a selected, generalized map inventory, not a complete list of Mali’s watercourses or evidence of present flow. Both Baoulé identities are preserved. No commune/settlement crossing, official river length or navigability is inferred.',
            'Il s’agit d’une sélection cartographique généralisée, pas d’un inventaire complet des cours d’eau du Mali ni d’une preuve d’écoulement actuel. Les deux identités Baoulé sont conservées. Aucun passage par commune/localité, longueur officielle ou navigabilité n’est déduit.',
            'Dies ist eine ausgewählte, generalisierte Kartenübersicht, keine vollständige Gewässerliste oder Aussage über aktuelle Wasserführung. Beide Baoulé-Identitäten bleiben erhalten. Keine Ableitung von Gemeinde-/Ortsquerungen, amtlichen Flusslängen oder Schiffbarkeit.')]
    return {'answer': '\n'.join(lines), 'country': data, 'evidence': physical_evidence(data),
            'family_counts': {'Country physical geography': 2}}
