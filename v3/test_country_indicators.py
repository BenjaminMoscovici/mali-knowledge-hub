import json
import math
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from country_indicators import indicator_package,indicator_plan,indicator_query,indicator_answer
from country_foundation import country_foundation
from source_inventory import catalogue
import web_api


def test_official_metadata_observation_identity_and_missing_values_retained():
    package=indicator_package()
    assert len(package['series'])==17
    assert sum(o['value'] is not None for s in package['series'] for o in s['observations'])==151
    for s in package['series']:
        assert s['country_iso3']=='MLI' and s['source_id']=='2'
        assert s['metadata']['id']==s['indicator_id']
        assert s['metadata']['sourceNote'] and s['metadata']['sourceOrganization']
        assert len(s['response_sha256'])==64
        assert {o['year'] for o in s['observations']}==set(range(2015,2027))
        assert len(s['observations'])==12
        assert all(o['value'] is None or math.isfinite(o['value']) for o in s['observations'])


def test_latest_means_observation_year_not_retrieval_or_api_update():
    data=indicator_query(['SH.MED.BEDS.ZS','EG.ELC.ACCS.ZS'])
    assert data['series'][0]['observations'][0]['year']==2018
    assert data['series'][1]['observations'][0]['year']==2024
    result=indicator_answer('Hospital beds in Mali')
    assert '2018' in result['answer']
    assert result['evidence'][0]['reference_period_start']=='2018-01-01'
    assert '2018' not in result['evidence'][0]['retrieved_at']


def test_specific_missing_year_not_replaced_with_latest():
    data=indicator_query(['SH.MED.BEDS.ZS'],[2024])
    assert data['series'][0]['observations'][0]['value'] is None
    result=indicator_answer('Hospital beds in Mali in 2024')
    assert 'not reported' in result['answer'] and '0.25' not in result['answer']
    assert indicator_query(['EG.ELC.ACCS.ZS'],[2030])['series'][0]['observations'][0]['status']=='outside_snapshot_window'
    result=indicator_query(['EG.ELC.ACCS.ZS'],[2020,2024],True)
    assert [o['year'] for o in result['series'][0]['observations']]==list(range(2020,2025))


@pytest.mark.parametrize('question',[
    'What is electricity access in Gao region of Mali?',
    'What is drinking water access in Socoura, Mali?',
    'Compare Mali and Burkina Faso electricity access',
    'What is the population of Mali and electricity access?',
    'Which projects improved electricity access in Mali?',
    'Why is primary school enrolment low in Mali?',
])
def test_national_series_do_not_answer_subnational_or_analytical_requests(question):
    assert indicator_plan(question) is None


@pytest.mark.parametrize('question',[
    'What is access to safely managed drinking water in Mali?',
    'What is electricity reliability in Mali?',
    'What is real GDP in Mali?',
    'What is net enrolment in Mali?',
])
def test_different_definitions_are_not_silently_substituted(question):
    result=indicator_answer(question)
    assert result['country']['status']=='unsupported_indicator_definition' and not result['evidence']


def test_national_series_in_source_inventory_and_cited_chat_without_network():
    row=next(r for r in catalogue() if 'national development indicators' in r['title'])
    assert row['state']=='loaded' and row['records']==151
    client=TestClient(web_api.app,base_url='https://mali-knowledge-hub.onrender.com')
    with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
        r=client.post('/api/chat',json={'question':'What is electricity access in Mali?'},headers={'Origin':'https://mali-knowledge-hub.onrender.com'})
        assert r.status_code==200,r.text
        body=r.json()
        assert '2024' in body['answer'] and body['metrics']['route']=='country_fact'
        assert body['metrics']['model_calls']==0 and body['evidence']
        evidence=json.loads(body['evidence'][0]['content'])
        assert evidence['series']['indicator_id']=='EG.ELC.ACCS.ZS'
        assert evidence['series']['definition'] and evidence['series']['source_organization']
        r=client.get('/api/country',params={'metric':'indicator','indicator':'SH.H2O.BASW.ZS','year':2024})
        assert r.status_code==200
        assert r.json()['country']['series'][0]['observations'][0]['year']==2024
        assert client.get('/api/country',params={'metric':'indicator','indicator':'evil_sql'}).status_code==400
        r=client.get('/api/country',params={'metric':'geometry','level':'region','name':'Gao'})
        assert r.status_code==200 and r.headers['content-type'].startswith('application/geo+json')
        feature=r.json()['features'][0]
        assert feature['geometry']['type'] in ('Polygon','MultiPolygon')
        assert feature['properties']['population_join'].startswith('not approved')
        assert 'population' not in feature['properties']
    client.close()
