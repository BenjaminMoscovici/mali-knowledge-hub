"""Replay selected public CH/FTS aggregates with exact row provenance.

The Mali slice of the mixed CH/IPC workbook is Cadre Harmonise. Only the
latest Mali exercise is activated; the workbook's filename is not its date.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path

from operational_import import GeoMatcher, worksheet
from source_foundation import stable_id


def number(value):
    if value in (None, "", "-", "–"):
        return None
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("Invalid nonnegative source value")
    return float(result)


class Package:
    def __init__(self):
        self.data = {"tables": {}, "records": [], "releases": {}, "registry": []}

    def add(self, path, source, dataset, provider, title, url, licence, licence_url,
            version, records, limitations, granularity, publication=None, metadata_url=None):
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        release = stable_id(dataset, checksum, "analytical-wave/1")
        run = stable_id(release, "validated-import")
        retrieved = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        start, end = min(r['reference_start'] for r in records), max(r['reference_end'] for r in records)
        tables = {
            "mkh_sources": [{"id": source, "provider": provider, "title": title, "url": metadata_url or url}],
            "mkh_datasets": [{"id": dataset, "source_id": source, "title": title,
                              "refresh_policy": "check provider releases; immutable imports", "current_release_id": None}],
            "mkh_ingestion_runs": [{"id": run, "dataset_id": dataset, "started_at": retrieved, "finished_at": retrieved,
                                    "status": "succeeded", "release_id": release, "error_class": None}],
            "mkh_source_releases": [{"id": release, "dataset_id": dataset, "checksum": checksum,
                "upstream_version": version, "retrieved_at": retrieved, "publication_date": publication,
                "reference_start": start, "reference_end": end, "source_url": url, "original_file": path.name,
                "license": licence, "license_url": licence_url, "attribution": provider, "access": "public_aggregate",
                "transformation": "analytical-wave/1; selected Mali aggregates; original values and row locators retained",
                "quality_json": {"records": len(records), "limitations": limitations}, "run_id": run,
                "status": "validated_with_limitations"}], "mkh_evidence_spans": [], "mkh_source_records": []}
        for record in records:
            record_id = stable_id(release, record['locator'])
            record.update(id=record_id, release_id=release, dataset_id=dataset, version=version,
                          retrieved_at=retrieved, source_url=url, provider=provider, title=title)
            tables['mkh_evidence_spans'].append({"id": record_id, "release_id": release,
                "original_record_id": record['locator'], "page": record.get('page'),
                "printed_page": str(record['page']) if record.get('page') else None,
                "section": record.get('section', record['locator']),
                "passage": json.dumps(record['payload'], ensure_ascii=False), "locator": record['locator']})
            tables['mkh_source_records'].append({"id": record_id, "release_id": release, "span_id": record_id,
                "source_type": record['source_type'], "reference_start": record['reference_start'],
                "reference_end": record['reference_end'], "payload": record['payload']})
        for table, rows in tables.items():
            self.data['tables'].setdefault(table, []).extend(rows)
        self.data['records'].extend(records)
        self.data['releases'][dataset] = release
        self.data['registry'].append({"provider": provider, "source_name": title,
            "analytical_use": ', '.join(sorted({r['source_type'] for r in records})),
            "authoritative_status": "original provider / attributed provider export", "access_route": url,
            "format": path.suffix.lstrip('.').upper(), "authentication": "none", "licence": licence,
            "sensitivity": "public aggregate facts only", "geographic_granularity": granularity,
            "temporal_granularity": version, "update_frequency": "provider cycle; checked per wave",
            "historical_coverage": f"{start} to {end}", "last_successful_retrieval": retrieved,
            "integration_status": "public_access_confirmed", "limitations": limitations,
            "fallback_source": "next provider release / linked original report", "next_action": "deploy and verify cited user answers",
            "responsible_party": "MKH source maintainer", "records": len(records), "checksum": checksum})

    def save(self, output):
        with gzip.GzipFile(filename=str(output), mode='wb', mtime=0) as file:
            file.write(json.dumps(self.data, ensure_ascii=False, separators=(',', ':')).encode())
        output.with_name(output.name.replace('.json.gz', '_registry.json')).write_text(
            json.dumps(self.data['registry'], ensure_ascii=False, indent=2))
        print(json.dumps(Counter(r['source_type'] for r in self.data['records'])))


def food_funding(directory, output):
    package = Package()
    matcher = GeoMatcher()
    meta = json.loads((directory / 'ch_metadata.json').read_text())
    resource = meta['resources'][0]
    records = []
    for row, v in worksheet(directory / 'ch_march26.xlsx', 1):
        if v.get('A') != 'Mali' or v.get('R') != '2025' or v.get('Q') != 'Sep-Dec':
            continue
        period = v['S']
        if period == 'current' and v['U'] == 'Sep-Dec' and v['V'] == '2025':
            start, end = '2025-09-01', '2025-12-31'
        elif period == 'projected' and v['U'] == 'Jun-Aug' and v['V'] == '2026':
            start, end = '2026-06-01', '2026-08-31'
        else:
            raise ValueError('Unreviewed Mali CH reference period')
        phases = {str(n): number(v.get(c)) for n, c in enumerate(('Y', 'Z', 'AA', 'AB', 'AC'), 1)}
        population, phase35 = number(v['W']), number(v['AD'])
        if any(x is None for x in phases.values()) or abs(sum(phases.values()) - population) > max(2, population * .00001):
            raise ValueError(f'CH phase population conflict row {row}')
        if abs(sum(phases[str(n)] for n in (3, 4, 5)) - phase35) > max(2, population * .00001):
            raise ValueError(f'CH phase 3+ conflict row {row}')
        geo = {'region': v['F'], 'region_pcode': v['G'], 'cercle': v['J'], 'cercle_pcode': v['K']}
        records.append({'source_type': 'food_security_classification', 'reference_start': start, 'reference_end': end,
            'locator': f'{resource["name"]} / Sheet1 / row {row}',
            'payload': {'methodology': 'Cadre Harmonise', 'period_type': period,
                'exercise': '2025 Sep-Dec (provider label)', 'reference_label': v['U'] + ' ' + v['V'],
                'population': population, 'phase_class': number(v['X']), 'phase_populations': phases,
                'phase35': phase35, 'unit': 'people_estimated',
                'raw_numeric_values': {c: v.get(c) for c in ('W','X','Y','Z','AA','AB','AC','AD')},
                'geography': geo, 'geo_resolution': matcher.match(geo),
                'coverage': 'source-reported cercle/analysis area; historical geography vintage, not commune estimates',
                'limitations': 'Current means current to late-2025 exercise, not today. Projection is June-August 2026; no fresh 2026 observation. Source current-period label Sep-Dec differs from conventional Oct-Dec CH seasonal terminology; retained unchanged.'}})
    if len(records) != 112 or Counter(r['payload']['period_type'] for r in records) != {'current': 56, 'projected': 56}:
        raise ValueError('CH latest Mali slice changed; review required')
    package.add(directory/'ch_march26.xlsx', 'fsnwg-ch', 'mli-ch-late2025', meta['organization']['title'],
        'Mali Cadre Harmonise — late-2025 analysis / June-August 2026 projection', resource['url'],
        meta['license_title'], meta['license_url'], '2025 Sep-Dec exercise', records,
        ['112 records: 56 current and 56 projected analysis areas; latest Mali exercise in this workbook is late 2025, despite March 2026 filename.',
         'Old P-codes and parent labels may conflict with COD v03; unresolved matches retained; no commune-level estimates.',
         'Population phase estimates have decimal precision; raw publisher numbers retained; population phase is distinct from area phase.'],
        'source-reported regions/cercles; unresolved geography vintage', metadata_url='https://data.humdata.org/dataset/'+meta['id'])
    # Small fact extraction, not reproduction of the bulletin's full text or PDF.
    bulletin = 'https://ict.cilss.int/sites/default/files/2026-08/CH-FICHE-COMMUNICATION-JUIN-2026_Version-finale.pdf'
    record = {'source_type': 'food_security_classification', 'reference_start': '2026-06-01', 'reference_end': '2026-08-31',
        'locator': 'CILSS July 2 2026 bulletin / page 3 Table 2 Mali; page 4 methodology', 'page': 3,
        'payload': {'methodology': 'Cadre Harmonise', 'period_type': 'projected', 'exercise': 'October/November 2025 carried forward (page 4)',
            'reference_label': 'June-August 2026', 'population': 25568962, 'phase_class': None,
            'phase_populations': {'1':19878962,'2':4129811,'3':1503535,'4':56654,'5':None},
            'phase35':1560189, 'unit':'people_estimated', 'geography':{'country':'Mali'},
            'geo_resolution':{'matches':{},'issues':[]}, 'coverage':'national analyzed population, not all population or a subnational allocation',
            'limitations':'Projection carried forward from October/November 2025; not a March/June 2026 fresh assessment. Phase 5 is printed dash, retained unknown. Geography and population vintage differ from INSTAT/HPC.'}}
    package.add(directory/'ch_june2026.pdf', 'cilss-ch', 'mli-ch-june2026-bulletin', 'CILSS',
        'CILSS CH June-August 2026 national projection — Mali', bulletin, 'Public factual table extraction; full-text rights not assumed',
        bulletin, 'Published 2 July 2026; late-2025 projection carried forward', [record],
        ['Only one Mali national factual table; PDF/full text not redistributed.', 'No Mali current-2026 classification in this bulletin.'],
        'national only', publication='2026-07-02')
    meta = json.loads((directory/'fts_metadata.json').read_text()); resource = meta['resources'][0]
    records = []
    with (directory/'fts0.csv').open(encoding='utf-8', newline='') as file:
        for row, v in enumerate(csv.DictReader(file), 2):
            year = int(v['year'])
            records.append({'source_type':'funding_aggregate', 'reference_start':f'{year}-01-01', 'reference_end':f'{year}-12-31',
                'locator':f'fts_requirements_funding_mli.csv / row {row}',
                'payload':{'country':'Mali','plan_id':v['id'] or None,'plan_code':v['code'] or None,'name':v['name'],
                    'year':year,'requirements':number(v['requirements']),'funding':number(v['funding']),
                    'percent_funded_reported':number(v['percentFunded']),'currency':'USD',
                    'funding_definition':'FTS total reported funding includes contributions, commitments and carry-over unless otherwise specified; not synonymous with disbursements or delivery',
                    'provider_updated_at':resource['last_modified'],'geography':{'country':'Mali'}}})
    package.add(directory/'fts0.csv', 'ocha-fts', 'mli-fts-requirements-funding', meta['organization']['title'],
        'Mali FTS plan requirements and reported funding', resource['url'], meta['license_title'], meta['license_url'],
        'FTS export updated '+resource['last_modified'], records,
        ['National plan/year aggregates only; no actor, project or sector attribution.', 'Plan and non-plan funding remain separate; future usage years are not current funding.',
         'Percent funded is publisher-rounded; requirements are not funding. Reported funding is not proof of disbursement or service delivery.'],
        'national plan/year only', metadata_url='https://data.humdata.org/dataset/'+meta['id'])
    matcher.db.close()
    package.save(output)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('directory',type=Path); parser.add_argument('output',type=Path)
    args=parser.parse_args(); food_funding(args.directory,args.output)
