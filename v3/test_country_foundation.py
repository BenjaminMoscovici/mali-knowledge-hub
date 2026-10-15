"""Real packaged-data acceptance and no-provider HTTP checks."""
import json
import sys
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from country_foundation import country_foundation,country_plan,resolve_country_followup
from query_router import classify
import web_api


@pytest.fixture(scope='module')
def foundation():return country_foundation()


def test_overlay_matches_original_source_and_population_rows(foundation):
    assert foundation.validation['attribute_counts']=={'country':1,'region':20,'cercle':159,'commune':815,'arrondissement':7,'locality':12915}
    assert foundation.validation['population_observations']==41751
    assert foundation.validation['geometry_count']==181
    assert {g['name'] for g in foundation.validation['locality_count_discrepancies']}=={'DIALAFARA','MASSIGUI'}
    assert foundation.validation['boundary_relations']=={'region:shared_border':38,'cercle:shared_border':424,'cercle:point_contact':8}
    for uid,attr in foundation.attributes.items():
        assert uid in foundation.model.units
        assert attr['release_id']==foundation.model.preferred
        assert attr['span_id']==foundation.model.spans[uid]['id']


def test_population_specific_homonyms_and_scope(foundation):
    result=foundation.population_rows('commune','Gao')
    assert result['rows'][0]['population']['total']==141929
    bamba=foundation.population_rows('commune','Bamba')
    assert len(bamba['rows'])==2
    assert len({r['unit_id'] for r in bamba['rows']})==2
    scoped=foundation.population_rows('commune','Bamba','region','Gao')
    assert len(scoped['rows'])==1 and scoped['rows'][0]['population']['total']==31113
    assert foundation.population_rows('commune','Foobar')['status']=='no_match'
    assert foundation.population_rows('commune',scope_level='region',scope='Foobar')['status']=='unknown_scope'


def test_ranking_is_entire_same_release_not_retrieval_subset(foundation):
    result=foundation.population_rows('commune',ranking=True,limit=10)
    assert result['candidate_count']==815 and result['omitted_count']==805
    assert len(result['candidate_ids'])==815
    assert result['rows'][0]['name']=='SIKASSO' and result['rows'][0]['population']['total']==434717
    assert all(r['release_id']==foundation.model.preferred and r['level']=='commune' for r in result['rows'])
    # Bamako arrondissement populations must never be silently ranked as communes.
    assert all(r['name']!='ARRONDISSEMENT 6' for r in result['rows'])
    sub=foundation.population_rows('commune',scope_level='region',scope='Gao',ranking=True,limit=50)
    assert sub['candidate_count']==44
    vals=[r['population']['total'] for r in sub['rows']]
    assert vals==sorted(vals,reverse=True)
    smallest=foundation.population_rows('commune',order='asc',ranking=True,limit=2)
    assert smallest['rows'][0]['population']['total']<=smallest['rows'][1]['population']['total']


def test_residence_disjoint_partition_and_rounding(foundation):
    result=foundation.residence()
    assert result['partition_sum']==23143461 and result['published_scope_total']==23143456
    assert result['sum_minus_published']==5
    assert len(result['candidate_ids'])==822
    assert {r['residence']:r['population'] for r in result['rows']}=={'U':6683593,'R':16459868}
    assert sum(r['share_of_partition_sum_pct'] for r in result['rows'])==pytest.approx(100)
    bamako=foundation.residence('Bamako','region')
    assert len(bamako['candidate_ids'])==7
    assert next(r for r in bamako['rows'] if r['residence']=='R')['population']==0
    assert foundation.residence('Unknownville','region')['status']=='no_match'


def test_polygon_area_and_shared_border_are_release_isolated(foundation):
    result=foundation.spatial_rows('area','region','Gao')
    row=result['rows'][0]
    assert row['area_km2']==pytest.approx(101307.9,abs=.1)
    assert row['release_id']==foundation.cod and row['geometry_valid']==1
    assert row['unit_id'] not in foundation.populations
    result=foundation.spatial_rows('neighbours','region','Mopti')
    assert {r['name'] for r in result['rows'][0]['neighbours']}=={'Bandiagara','Douentza','San','Segou','Tombouctou'}
    assert foundation.spatial_rows('area','commune','Gao')['status']=='no_geometry_at_level'
    assert foundation.spatial_rows('neighbours','country','Mali')['status']=='no_crosscountry_geometry'
    for rel in foundation.relations:
        assert foundation.model.units[rel['from_unit_id']]['level']==foundation.model.units[rel['to_unit_id']]['level']
        assert rel['release_id']==foundation.cod


@pytest.mark.parametrize('question,expected',[
    ('Top 10 most populated communes in Mali','ranking'),
    ('Quelles sont les 5 communes les plus peuplées du Mali ?','ranking'),
    ('What is the area of Gao region?','area'),
    ('Which regions border Mopti region?','neighbours'),
    ('What is the urban and rural population of Mali?','residence'),
    ('What is the population of Gao commune?','population'),
    ('Wie viele Einwohner hat die Gemeinde Gao?','population'),
    ('What is the population of Mali in 2026?','unavailable_period'),
    ('Rank communes by current population in Mali','unavailable_period'),
    ('What is the population density of Gao region?','incompatible_join'),
])
def test_bounded_intents(question,expected):
    assert country_plan(question)['metric']==expected
    assert classify(question)['path']=='country_fact'


@pytest.mark.parametrize('question',[
    'Which communes have displaced people and food security actors?',
    'Compare population and health services in Gao',
    'Why is population growth affecting livelihoods?',
    'Which population datasets are available in the Hub?',
    'How does reform of regions affect service delivery?',
])
def test_mixed_and_sensitive_intents_keep_existing_research(question):
    assert country_plan(question) is None
    assert classify(question)['path']!='country_fact'


def test_unknown_name_never_becomes_national_ranking(foundation):
    result=foundation.answer('What is the population of Unknownville commune in Mali?')
    assert result['country']['status']=='unknown_requested_place'
    assert result['evidence']==[] and '434,717' not in result['answer']
    result=foundation.answer('Compare populations of Gao and Unknownville regions')
    assert result['country']['status']=='incomplete_comparison'
    assert result['evidence']==[]
    result=foundation.answer('Compare populations of Gao, Mopti and Unknownville regions')
    assert result['country']['status']=='incomplete_comparison'
    assert result['evidence']==[]


def test_original_passage_and_locators_in_citations(foundation):
    result=foundation.answer('What is the population of Dialafara commune?')
    evidence=result['evidence'][0]
    data=json.loads(evidence['content'])
    assert '32 322' in data['source_rows'][0]['passage']
    assert evidence['page']==40 and evidence['reference_period_start']=='2023-01-01'
    assert data['publication_month']=='2026-01'
    assert '38 reported, 37 enumerated' in result['answer']
    assert '2023' in result['answer'] and '[E01]' in result['answer']


def test_bounded_followup_uses_question_not_assistant_claims():
    prior=[{'role':'user','content':'What is the population of Gao commune?'},
           {'role':'assistant','content':'Fabricated population: 999999999'}]
    assert resolve_country_followup('And Mopti commune?',prior)=='What is the population of mopti commune?'
    assert resolve_country_followup('And Bamba commune?',prior) is None
    prior.append({'role':'user','content':'Tell me about a project'})
    assert resolve_country_followup('And Mopti commune?',prior) is None


def test_chat_country_api_without_models_network_or_engine():
    client=TestClient(web_api.app,base_url='https://mali-knowledge-hub.onrender.com')
    with patch.dict(sys.modules,{'analysis_core':None}),patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
        for q in ['What is the population of Gao commune?','Top 10 most populated communes in Mali',
                  'Compare the populations of Gao and Mopti regions','What is the area of Gao region?',
                  'Which regions border Mopti region?','Quelle est la population de la commune de Gao ?',
                  'Wie viele Einwohner hat die Gemeinde Gao?']:
            response=client.post('/api/chat',json={'question':q,'analysis_mode':'deep'},headers={'Origin':'https://mali-knowledge-hub.onrender.com'})
            assert response.status_code==200,response.text
            body=response.json();metrics=body['metrics']
            assert metrics['route']=='country_fact'
            assert metrics['model_calls']==metrics['embedding_calls']==metrics['external_research_calls']==0
            assert metrics['estimated_usd']==0 and body['evidence']
            if q.startswith('Quelle'):assert 'Estimations' in body['answer']
            if q.startswith('Wie'):assert 'Bevölkerungsschätzungen' in body['answer'] and '141,929' in body['answer']
        response=client.get('/api/country',params={'metric':'ranking','level':'commune','scope':'Gao','scope_level':'region','limit':5})
        assert response.status_code==200 and response.json()['country']['candidate_count']==44
        assert client.get('/api/country',params={'metric':'ranking','level':'commune','limit':999}).status_code==400
        assert client.get('/api/country',params={'metric':'population','level':'invalid'}).status_code==400
        assert client.get('/api/country',params={'metric':'sql'}).status_code==400
        response=client.get('/api/country',params={'q':'What is the area of Gao commune?'})
        assert response.json()['country']['status']=='no_geometry_at_level'
    client.close()
