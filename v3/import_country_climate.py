"""Import a pinned national CRU climatology; no administrative crosswalks.

The portal's climatology JavaScript specifies TS 4.09, unlike its older general
collection documentation. Keep that exact version in both API requests.
"""
import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

import requests

VARIABLES = ('pr', 'tas', 'tasmin', 'tasmax')
PERIOD = '1991-2020'
VERSION = 'CRU TS 4.09'
PAGE = 'https://climateknowledgeportal.worldbank.org/country/mali/climate-data-historical'
CONFIG = 'https://climateknowledgeportal.worldbank.org/themes/custom/cckpmodern/js/GeoPage/topic-climate-data-historical.js'
CATALOG = 'https://climateknowledgeportal.worldbank.org/themes/custom/cckpmodern/js/Products/Catalog.js'
ELEMENTS = 'https://climateknowledgeportal.worldbank.org/data/elements_by_id/climatology'
UPSTREAM = 'https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.09/'


def api_url(aggregation):
    if aggregation not in ('annual', 'monthly'):
        raise ValueError('Unsupported aggregation')
    return ('https://cckpapi.worldbank.org/api/v1/cru-x0.5_climatology_'
            + ','.join(VARIABLES) + '_climatology_' + aggregation
            + '_1991-2020_mean_historical_cru_ts4.09_mean/MLI?_format=json')


def attributes_url(variable, aggregation):
    return (f'https://climatedata.worldbank.org/thredds/dodsC/CRM/cru-x0.5/{variable}/cru-ts4.09-historical/'
            f'climatology-{variable}-{aggregation}-mean_cru-x0.5_cru-ts4.09-historical_climatology_mean_1991-2020.nc.das')


def validate_attributes(variable, aggregation, text):
    expected = {'wb_variant_label': 'ts4.09', 'wb_period_label': PERIOD, 'wb_type_label': 'climatology',
                'wb_collection_label': 'cru-x0.5', 'wb_variable_label': variable,
                'wb_aggregation_label': aggregation, 'wb_scenario_label': 'historical',
                'wb_model_label': 'cru', 'wb_product_label': 'climatology',
                'wb_statistic_label': 'mean', 'wb_percentile_label': 'mean'}
    for key, value in expected.items():
        if not re.search(r'String ' + re.escape(key) + r' "' + re.escape(value) + r'";', text):
            raise ValueError('Incompatible NetCDF product metadata: ' + key)
    block = re.search(r'climatology-' + variable + '-' + aggregation + r'-mean \{([^}]+)\}', text)
    unit = 'mm' if variable == 'pr' else 'degC'
    if not block or not re.search(r'String units "' + unit + r'";', block[1]):
        raise ValueError('Incompatible NetCDF product unit')
    if 'Open Government License' not in text or 'open-government-licence/version/3/' not in text:
        raise ValueError('Product data licence not verified')
    return {'variable': variable, 'aggregation': aggregation, 'source_unit': unit,
            'source_version': VERSION, 'reference_period': PERIOD, 'passed': True}


def validate_responses(responses, variables):
    """Fail closed on missing/extra places, periods, units or observations."""
    if set(responses) != {'annual', 'monthly'} or set(variables) != set(VARIABLES):
        raise ValueError('Unexpected response/variable coverage')
    rows = []
    for variable in VARIABLES:
        expected_unit = 'mm' if variable == 'pr' else '°C'
        if variables[variable]['unit'] != expected_unit or not variables[variable]['info']:
            raise ValueError('Unverified unit or definition')
    for aggregation, response in responses.items():
        if response.get('metadata', {}).get('status') != 'success' or response['metadata'].get('messages'):
            raise ValueError('Unsuccessful climate response')
        data = response['data']
        if set(data) != set(VARIABLES):
            raise ValueError('Incomplete climate variables')
        expected = {f'1991-{month:02d}' for month in range(1, 13)} if aggregation == 'monthly' else {'1991-07'}
        for variable in VARIABLES:
            if set(data[variable]) != {'MLI'} or set(data[variable]['MLI']) != expected:
                raise ValueError('Wrong geography or incomplete climatological coordinates')
            for coordinate, value in sorted(data[variable]['MLI'].items()):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError('Missing or invalid climate value')
                if not (0 <= value <= 10000 if variable == 'pr' else -80 <= value <= 70):
                    raise ValueError('Implausible climate value')
                rows.append({'variable': variable, 'aggregation': aggregation,
                             'month': int(coordinate[-2:]) if aggregation == 'monthly' else 0,
                             'source_coordinate': coordinate, 'value': value, 'status': 'reported'})
        for coordinate in expected:
            if not data['tasmin']['MLI'][coordinate] <= data['tas']['MLI'][coordinate] <= data['tasmax']['MLI'][coordinate]:
                raise ValueError('Inconsistent minimum/mean/maximum temperatures')
    # Check annual totals/means independently using monthly values and source
    # two-decimal precision. Temperature weights include every calendar day in
    # the complete 30-year normal, including leap years.
    checks = []
    days = {m: sum(calendar.monthrange(y, m)[1] for y in range(1991, 2021)) for m in range(1, 13)}
    for variable in VARIABLES:
        monthly = responses['monthly']['data'][variable]['MLI']
        derived = (sum(monthly.values()) if variable == 'pr' else
                   sum(monthly[f'1991-{m:02d}'] * days[m] for m in days) / sum(days.values()))
        annual = responses['annual']['data'][variable]['MLI']['1991-07']
        tolerance = 0.065 if variable == 'pr' else 0.01
        if abs(annual - derived) > tolerance + 1e-9:
            raise ValueError('Annual/monthly climatology inconsistency: ' + variable)
        checks.append({'variable': variable, 'annual_source_value': annual,
                       'monthly_derived_check': derived, 'rounding_tolerance': tolerance,
                       'method': 'sum of monthly precipitation' if variable == 'pr' else 'calendar-day-weighted monthly temperature',
                       'passed': True})
    return sorted(rows, key=lambda r: (r['variable'], r['aggregation'], r['month'])), checks


def fetch(output):
    raw = {}; responses = {}; urls = {}
    for aggregation in ('annual', 'monthly'):
        url = api_url(aggregation)
        response = requests.get(url, timeout=40); response.raise_for_status()
        raw[aggregation] = response.content.decode('utf-8')
        responses[aggregation] = json.loads(raw[aggregation]); urls[aggregation] = url
    response = requests.post(ELEMENTS, data={'elements[]': list(VARIABLES)}, timeout=40)
    response.raise_for_status()
    raw['variable_metadata'] = response.content.decode('utf-8')
    variables = json.loads(raw['variable_metadata'])['data']['variable']
    rows, checks = validate_responses(responses, variables)
    def retrieve_attributes(selection):
        variable, aggregation = selection; url = attributes_url(variable, aggregation)
        response = requests.get(url, timeout=40); response.raise_for_status()
        text = response.content.decode('utf-8')
        return variable + '_' + aggregation, url, text, validate_attributes(variable, aggregation, text)
    selections = [(v, a) for v in VARIABLES for a in ('annual', 'monthly')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        products = list(pool.map(retrieve_attributes, selections))
    product_checks = []; metadata_urls = {}
    for key, url, text, check in products:
        raw['product_' + key] = text; metadata_urls[key] = url; product_checks.append(check)
    package = {
        'dataset_id': 'mli-cckp-cru-ts4.09-1991-2020', 'country_iso3': 'MLI',
        'source_version': VERSION, 'reference_start': '1991-01-01', 'reference_end': '2020-12-31',
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'publication_date': None,
        'reference_period': PERIOD, 'grid_resolution_degrees': 0.5,
        'geographic_framework': 'World Bank CCKP national MLI spatial aggregation; no INSTAT/COD administrative crosswalk',
        'source_organization': 'World Bank Climate Change Knowledge Portal; Climatic Research Unit (University of East Anglia) and Met Office',
        'source_page': PAGE, 'upstream_page': UPSTREAM,
        'license': 'CRU upstream: Open Government Licence; mandatory source acknowledgement',
        'license_url': 'https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/',
        'attribution': 'Climatic Research Unit (University of East Anglia) and Met Office; national aggregation via World Bank CCKP',
        'api_urls': urls, 'variable_metadata_url': ELEMENTS,
        'product_metadata_urls': metadata_urls, 'product_metadata_checks': product_checks,
        'variable_metadata_request': {'method': 'POST', 'elements[]': list(VARIABLES)},
        'version_verification': {'portal_configuration': CONFIG, 'api_url_builder': CATALOG,
            'note': 'The portal climatology configuration requests TS 4.09; general collection documentation describes the older TS 4.07. No versions are combined.'},
        'raw_responses': raw,
        'response_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k, v in raw.items()},
        'variables': variables, 'observations': rows, 'quality_checks': checks,
        'limitations': [
            '1991–2020 long-term national climate normals, not observations for 1991, current weather, forecasts or a yearly time series.',
            'API labels 1991-MM and annual 1991-07 are climatological coordinates for the complete reference period; annual July is not a July observation.',
            'CRU interpolates weather-station observations on a 0.5-degree grid; station coverage and representativeness vary.',
            'National averages conceal large spatial differences; do not allocate to regions, communes, settlements or facilities.',
            'Precipitation is mean accumulated precipitation per calendar month/year in mm; tasmax/tasmin are average daily maxima/minima, not recorded extremes.',
            'The snapshot contains four variables, twelve monthly normals and one annual normal each; no missing value is replaced with zero.',
            'Retrieval date is not a climate observation date or an indicator-specific publication date.',
        ],
    }
    Path(output).write_bytes(gzip.compress(json.dumps(package, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0))
    print(json.dumps({'observations': len(rows), 'source_version': VERSION, 'reference_period': PERIOD, 'checks': checks}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', required=True)
    fetch(parser.parse_args().output)
