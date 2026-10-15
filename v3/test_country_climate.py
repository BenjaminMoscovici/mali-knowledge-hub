"""Real climate source validation, bounded intent and zero-provider serving."""
from copy import deepcopy
import hashlib
import json
import sqlite3
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from country_climate import climate_package, climate_plan, climate_query, climate_answer
from country_foundation import country_foundation, country_plan
from import_country_climate import validate_responses, validate_attributes
from query_router import classify
from source_inventory import catalogue
import web_api


def test_pinned_responses_reproduce_all_observations_and_quality_checks():
    package = climate_package()
    assert package['source_version'] == 'CRU TS 4.09'
    assert package['reference_start'] == '1991-01-01' and package['reference_end'] == '2020-12-31'
    assert package['publication_date'] is None
    for key, raw in package['raw_responses'].items():
        assert hashlib.sha256(raw.encode()).hexdigest() == package['response_sha256'][key]
    responses = {k: json.loads(package['raw_responses'][k]) for k in ('annual', 'monthly')}
    rows, checks = validate_responses(responses, package['variables'])
    assert rows == package['observations'] and checks == package['quality_checks']
    assert len(rows) == 52
    assert all('ts4.09' in u and '/MLI?' in u for u in package['api_urls'].values())
    assert len(package['product_metadata_checks']) == 8
    for check in package['product_metadata_checks']:
        raw = package['raw_responses']['product_' + check['variable'] + '_' + check['aggregation']]
        assert validate_attributes(check['variable'], check['aggregation'], raw) == check
        with pytest.raises(ValueError):
            validate_attributes(check['variable'], check['aggregation'], raw.replace('ts4.09', 'ts4.07'))
    assert all(row['month'] == 0 for row in rows if row['aggregation'] == 'annual')
    assert climate_query(['pr'], 'annual')['observations'][0]['value'] == 328.5
    assert climate_query(['tas'], 'annual')['observations'][0]['value'] == 29.22
    assert climate_query(['pr'], 'monthly', month=8)['observations'][0]['value'] == 109.86


@pytest.mark.parametrize('fault', ['missing_month', 'extra_place', 'null', 'nan', 'bool', 'unit', 'bad_total', 'bad_temperature'])
def test_importer_rejects_incomplete_or_inconsistent_source_data(fault):
    package = climate_package()
    responses = {k: json.loads(package['raw_responses'][k]) for k in ('annual', 'monthly')}
    variables = deepcopy(package['variables'])
    monthly = responses['monthly']['data']
    if fault == 'missing_month': del monthly['pr']['MLI']['1991-03']
    if fault == 'extra_place': monthly['pr']['SEN'] = monthly['pr']['MLI']
    if fault in ('null', 'nan', 'bool'): monthly['pr']['MLI']['1991-03'] = {'null': None, 'nan': float('nan'), 'bool': True}[fault]
    if fault == 'unit': variables['pr']['unit'] = 'mm/day'
    if fault == 'bad_total': responses['annual']['data']['pr']['MLI']['1991-07'] += 1
    if fault == 'bad_temperature': monthly['tasmin']['MLI']['1991-03'] = 60
    with pytest.raises(ValueError): validate_responses(responses, variables)


@pytest.mark.parametrize('question', [
    'What is the climate of Mali?', 'Average annual rainfall in Mali',
    'Which month is wettest in Mali?', 'Which month is warmest in Mali?',
    'Quelle est la température moyenne annuelle au Mali ?',
    'Quelles sont les précipitations mensuelles au Mali en 1991–2020 ?',
    'Wie ist das Klima in Mali?', 'Monatliche Temperaturen in Mali',
    'Average daily maximum temperature in Mali',
])
def test_national_climate_intents(question):
    assert climate_plan(question)['metric'] == 'climate'
    assert country_plan(question)['metric'] == 'climate'
    assert classify(question)['path'] == 'country_fact'


@pytest.mark.parametrize('question', [
    'What is rainfall in Gao region of Mali?', 'What is rainfall in Socoura, Mali?',
    'What is rainfall in Atlantis, Mali?', 'Compare rainfall in Mali and Senegal',
    'Why is the climate dry in Mali?', 'Explain the impact of Mali rainfall on agriculture',
    'What is the population and rainfall of Mali?', 'Which schools have water in Mali climate?',
    'What are the climate sources available in Mali Knowledge Hub?',
    'What is the maximum recorded temperature in Mali?', 'Rainfall forecast in Mali',
])
def test_other_scopes_definitions_and_analytics_retain_existing_routes(question):
    assert climate_plan(question) is None


@pytest.mark.parametrize('question', [
    'Annual rainfall in Mali in 2023', 'What is the temperature in Mali today?',
    'What is the climate of Mali in 1961–1990?', 'Mali climate 2020',
])
def test_normals_never_silently_replace_other_periods(question):
    result = climate_answer(question)
    assert result['country']['status'] == 'unsupported_climate_period' and not result['evidence']


def test_monthly_results_and_source_cards_make_reference_period_explicit():
    result = climate_answer('Average daily minimum and maximum temperature in Mali')
    assert set(result['country']['variables']) == {'tasmin', 'tasmax'}
    assert '22.18' in result['answer'] and '36.31' in result['answer']
    result = climate_answer('Which month is wettest in Mali?')
    assert '**August**' in result['answer'] and '109.86' in result['answer']
    assert '**February**' in result['answer'] and '1991–2020' in result['answer']
    result = climate_answer('Which month is warmest in Mali?')
    assert '**June**' in result['answer'] and '34.16' in result['answer']
    for language in ('English', 'French', 'German'):
        result = climate_answer('Monthly climate in Mali', language)
        assert len(result['evidence']) == 2
        assert '328.50' in result['answer'] and '29.22' in result['answer']
        for evidence in result['evidence']:
            assert evidence['reference_period_start'] == '1991-01-01'
            assert evidence['reference_period_end'] == '2020-12-31'
            assert 'not single-year observations' in evidence['content']
            assert '1991-07' in evidence['content'] and evidence['version'] == 'CRU TS 4.09'


def test_zero_provider_chat_api_and_catalogue():
    row = next(r for r in catalogue() if 'national climate normals' in r['title'])
    assert row['records'] == 52 and row['state'] == 'loaded' and '4.09' in row['period']
    with TestClient(web_api.app, base_url='https://mali-knowledge-hub.onrender.com') as client:
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network')):
            result = client.post('/api/chat', json={'question': 'What is annual rainfall in Mali?'},
                headers={'Origin': 'https://mali-knowledge-hub.onrender.com'})
            assert result.status_code == 200, result.text
            body = result.json()
            assert '328.50' in body['answer'] and body['metrics']['route'] == 'country_fact'
            assert body['metrics']['model_calls'] == 0 and body['metrics']['estimated_usd'] == 0
            assert body['evidence'][0]['source_endpoint'].endswith('/mali/climate-data-historical')
            data = client.get('/api/country', params={'metric': 'climate', 'variables': 'pr,tas', 'aggregation': 'monthly', 'month': 8}).json()['country']
            assert len(data['observations']) == 2 and data['reference_period'] == '1991-2020'
            assert 'climate' in client.get('/api/country').json()['metrics']
            for extra in ({'period': '1961-1990'}, {'year': 2023}, {'name': 'Gao'}, {'scope': 'Mali'},
                          {'level': 'region'}, {'variables': 'pr,evil'}, {'month': 13}, {'month': 8, 'aggregation': 'annual'}):
                assert client.get('/api/country', params={'metric': 'climate', **extra}).status_code == 400


def test_standalone_export_keeps_climate_dates_provenance_and_country_only_data(tmp_path):
    from export_country_foundation import export
    path = export(tmp_path)
    with sqlite3.connect(path) as db:
        assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
        assert db.execute('pragma foreign_key_check').fetchall() == []
        assert db.execute('select count(*) from country_climate').fetchone()[0] == 52
        assert db.execute('select count(*) from mkh_population_observations').fetchone()[0] == 41751
        assert db.execute('select count(*) from mkh_humanitarian_observations').fetchone()[0] == 0
        assert db.execute("select value from country_climate where variable='pr' and aggregation='annual'").fetchone()[0] == 328.5
        assert db.execute('select distinct reference_start,reference_end from country_climate').fetchall() == [('1991-01-01', '2020-12-31')]
        provenance = json.loads(db.execute('select provenance_json from foundation_climate_datasets').fetchone()[0])
        assert provenance['raw_responses'] == climate_package()['raw_responses']
    assert (tmp_path/'National_Climate_Normals_1991-2020.csv').read_text(encoding='utf-8-sig').count('\n') == 53
