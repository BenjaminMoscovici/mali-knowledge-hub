"""Bounded, cited CH and financing retrieval. Each measure retains its scope."""
from datetime import datetime, timezone
from functools import lru_cache
import gzip
import json
import logging
from pathlib import Path
import re

from operational_sources import _scope, publish_operational_snapshot
from source_wave import _fold


@lru_cache(maxsize=1)
def package():
    with gzip.open(Path(__file__).with_name('source_wave3.json.gz'),'rt',encoding='utf-8') as file:
        return json.load(file)


def evidence(rows, content, title, scope, precision, data=None):
    first=rows[0]
    data=package() if data is None else data
    publication=next(r['publication_date'] for r in data['tables']['mkh_source_releases'] if r['id']==first['release_id'])
    return {'source_type':first['source_type'], 'source_family':'Cadre Harmonise food security' if first['source_type']=='food_security_classification' else 'OCHA FTS financing',
        'document_title':title,'document_type':'public_aggregate_evidence','organization':first['provider'],
        'version':first['version'],'publication_date':publication,
        'reference_period_start':first['reference_start'],'reference_period_end':first['reference_end'],
        'valid_from':first['reference_start'],'valid_until':first['reference_end'],
        'retrieved_at':first['retrieved_at'],'source_endpoint':first['source_url'],
        'record_id':first['id'],'release_id':first['release_id'], 'page':first.get('page'),
        'section':'; '.join(r['locator'] for r in rows), 'locator':'; '.join(r['locator'] for r in rows),
        'geographic_scope':scope,'geographic_precision':precision,'content':content}


def retrieve_analytical_evidence(question, limit=8):
    folded=_fold(question); results=[]
    food=bool(re.search(r'\b(cadre harmonise|ch|ipc|food\w*|aliment\w*|faim|hunger|needs|besoins|displace\w*|deplace\w*)\b',folded))
    finance=bool(re.search(r'\b(fts|fund\w*|financ\w*|budget\w*|requirements|requi\w*|disburs\w*|decaisse\w*|commit\w*|engage\w*|hnrp|hrp|hpc)\b',folded))
    if food:
        rows=[r for r in package()['records'] if r['dataset_id']=='mli-ch-late2025']
        selected,scope,level=_scope(question,rows)
        commune_request=bool(re.search(r'\bcommune\b',folded))
        caveat=('No commune estimates are available; the following are higher-level context only, not estimates for the requested commune. ' if commune_request else '')
        for period in ('current','projected'):
            subset=[r for r in selected if r['payload']['period_type']==period]
            # Keep complete area sets when small; use an explicitly disclosed sample otherwise.
            sample=sorted(subset,key=lambda r:(-r['payload']['phase35'],r['locator']))[:8]
            if sample:
                details=[{'source_region':r['payload']['geography']['region'],'source_cercle':r['payload']['geography']['cercle'],
                    'area_phase':r['payload']['phase_class'],'phase3plus_people_estimated':r['payload']['phase35'],
                    'analyzed_population':r['payload']['population'],'phase_populations':r['payload']['phase_populations'],
                    'geography_validation':r['payload']['geo_resolution']} for r in sample]
                content=(f'Cadre Harmonise, not IPC. {scope}. Exercise {sample[0]["payload"]["exercise"]}; '
                    f'period type {period}; reference label {sample[0]["payload"]["reference_label"]}; '
                    f'{len(sample)} of {len(subset)} source analysis-area rows selected by highest phase-3+ population, not severity rank. '
                    +caveat+json.dumps(details,ensure_ascii=False)+'. '
                    'Area classification is different from the population distribution across phases. Values are estimates, not exact enumerated persons. '
                    'Current is current to late-2025 analysis; projected June-August 2026 is not observed delivery or an October 2026 current assessment. '
                    'Source region/cercle codes are an older geography vintage. Same-name regions can have different boundaries; unresolved codes/parents are not approved joins. '
                    'Do not sum selected rows into regional totals, estimate communes, divide by INSTAT/HPC denominators or infer absence of need.')
                results.append(evidence(sample,content,'Mali Cadre Harmonise — '+period,scope,'source-reported cercle/analysis area; geography vintage unresolved'))
        national=[r for r in package()['records'] if r['dataset_id']=='mli-ch-june2026-bulletin']
        r=national[0];p=r['payload']
        results.append(evidence(national,
            'NATIONAL context only, CILSS bulletin published 2 July 2026, page 3 Table 2 and page 4 methodology. '
            f'Cadre Harmonise June-August 2026 projected phase3+ population {p["phase35"]:,}, analyzed population {p["population"]:,}; '
            f'phase populations {json.dumps(p["phase_populations"])}. Phase 5 printed dash is unknown, not zero. '
            'Mali projection is carried forward from October/November 2025 analysis, NOT a new March/June 2026 assessment. '
            'This national estimate is not regional or commune evidence and its population denominator must not be substituted for INSTAT census or HPC population. '
            'It does not establish observed hunger in October 2026, actual beneficiaries reached or intervention coverage.',
            'CILSS Cadre Harmonise — Mali national projection','Mali; national only','national analyzed population'))
    if finance:
        years={int(y) for y in re.findall(r'\b(?:19|20)\d{2}\b',question)} or {datetime.now(timezone.utc).year}
        for r in package()['records']:
            p=r['payload']
            if r['source_type']!='funding_aggregate' or p['year'] not in years:
                continue
            content=(f'Mali national FTS usage year {p["year"]}; plan {p["plan_id"] or "outside/unspecified plan"}, '
                f'code {p["plan_code"]}, name {p["name"]}. Currency USD. Requirements {p["requirements"] if p["requirements"] is not None else "not reported"}; '
                f'total reported funding {p["funding"] if p["funding"] is not None else "not reported"}; publisher-rounded funded percentage {p["percent_funded_reported"]}. '
                f'Provider updated {p["provider_updated_at"]}. {p["funding_definition"]}. '
                'Plan and non-plan figures are separate; do not add funding usage years. Future-year reported amounts are not current-year funding. '
                'No actor/project/sector/subnational breakdown in this export; cannot attribute this funding to a FONGIM project, local coverage or population reached. '
                'A funding-requirements gap is an arithmetic financing gap, not an observed service-coverage gap.')
            results.append(evidence([r],content,p['name']+' — FTS '+str(p['year']),'Mali; national plan/year only','national only'))
    return results[:limit]


def publish_analytical_logged():
    try:
        logging.getLogger('mkh.sources').info('analytical_wave %s',json.dumps(publish_operational_snapshot(package())))
    except Exception as error:
        logging.getLogger('mkh.sources').warning('analytical_wave publication_failed error_class=%s',type(error).__name__)
