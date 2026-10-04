"""Behavioral acceptance: source hierarchy and routes that avoid research."""
import sys
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
import web_api
from geographic_model import geographic_model, canonical_geography_evidence
from query_router import classify


@pytest.fixture(scope='module')
def model():
    return geographic_model()


def test_release_counts_and_parent_integrity(model):
    summary = model.summary()
    instat = next(r for r in summary['releases'] if r['preferred_hierarchy'])
    assert instat['counts'] == {'country':1, 'region':19, 'district':1,
        'cercle':159, 'commune':815, 'arrondissement':7, 'locality':12915}
    cod = next(r for r in summary['releases'] if r['dataset_id']=='mli-cod-ab')
    assert cod['counts']['cercle']==160 and cod['counts']['region']==19
    assert summary['crosswalk_status_counts']=={'proposed':171}
    assert len(summary['unresolved_places'])==10
    assert len(summary['proposed_crosswalks'])==171
    for u in model.units.values():
        path = model.path(u['id'])
        assert path[-1]['id']==u['id']
        assert all(model.units[p['id']]['release_id']==u['release_id'] for p in path)


def test_mopti_children_and_cited_paths(model):
    answer = model.answer('Which communes belong to Mopti cercle?')
    assert '12 recorded commune(s)' in answer['answer']
    for name in ['BASSIROU','DIALLOUBE','FATOMA','KOUBAYE','KOUNARI','MOPTI',
                 'OURO MODI','OUROUBE DOUDE','SASALBE','SIO','SOCOURA','SOYE']:
        assert name in answer['answer']
    socoura = model.lookup('Socoura', 'commune', model.preferred)
    assert len(socoura)==1
    assert [p['name'] for p in socoura[0]['path']]==['Mali','MOPTI','MOPTI','SOCOURA']
    assert socoura[0]['original_record_id'] and socoura[0]['locator']
    cod = next(r for r,v in model.releases.items() if v['dataset_id']=='mli-cod-ab')
    assert model.lookup('Mopti', 'region', cod)[0]['identifiers']
    assert answer['evidence'][0]['page'] >= 194
    assert all(e['source_endpoint'].startswith('https://') for e in answer['evidence'])
    assert 'OURO MODI (commune)' in model.answer('What is the administrative path for Ouro Modi commune?')['answer']


def test_homonyms_are_distinct_not_merged(model):
    bamba = model.lookup('Bamba', 'commune', model.preferred)
    assert len(bamba)==2 and bamba[0]['id']!=bamba[1]['id']
    assert bamba[0]['parent_id']!=bamba[1]['parent_id']
    result = model.answer('Are the Bamba communes the same administrative entity?')
    assert 'distinct identities' in result['answer']
    assert all(u['id'] in result['evidence'][0]['content'] for u in bamba)


def test_unknown_place_does_not_return_national_count(model):
    assert 'No exact match' in model.answer('What is the hierarchy of Unknownville commune?')['answer']
    assert '815 communes' not in model.answer('What is the hierarchy of Unknownville commune?')['answer']


def test_unresolved_places_can_be_inspected(model):
    result=model.answer('Which geographic places remain unresolved between versions?')
    assert 'Baraoueli' in result['answer'] and 'no_name_parent_match' in result['answer']
    assert 'Baraoueli' in result['evidence'][1]['content']


@pytest.mark.parametrize('question,path',[
    ('Hey, how are you?','conversational'),('Hi','conversational'),('Thanks!','conversational'),
    ('What can you do?','conversational'),('Can you explain that more simply?','conversation_only'),
    ('How is Mali administratively structured, and how many regions, cercles and communes are there?','simple_geography'),
    ('Which communes belong to Mopti cercle?','simple_geography'),
    ('What is the full administrative path for Socoura commune?','simple_geography'),
    ('Hi, what are the needs in Mopti?','complex_research'),
    ('Which communes have displaced people and food security actors?','complex_research'),
    ('And which communes belong there?','complex_research'),
    ('How does reform of regions affect service delivery?','complex_research'),
])
def test_conservative_routing(question,path):
    assert classify(question)['path']==path


def test_fast_routes_do_not_load_engine_or_call_network():
    # Missing analysis module deliberately explodes if research is loaded.
    client = TestClient(web_api.app,base_url='https://mali-knowledge-hub.onrender.com')
    with patch.dict(sys.modules,{'analysis_core':None}), patch('requests.sessions.Session.request',side_effect=AssertionError('network')), patch('httpx.HTTPTransport.handle_request',side_effect=AssertionError('network')):
        for q,route in [('Hey, how are you?','conversational'),
                        ('How is Mali administratively structured, and how many regions, cercles and communes are there?','simple_geography')]:
            r=client.post('/api/chat',json={'question':q,'analysis_mode':'deep'},
                headers={'Origin':'https://mali-knowledge-hub.onrender.com'})
            assert r.status_code==200
            data=r.json(); metrics=data['metrics']
            assert metrics['route']==route
            assert metrics['model_calls']==metrics['embedding_calls']==metrics['external_research_calls']==0
            assert metrics['estimated_usd']==0
            if route=='simple_geography':
                assert '159 cercles' in data['answer'] and len(data['evidence'])==2
                assert data['evidence'][0]['version']=='edition-2023-published-2026-01'
    client.close()


def test_simplification_without_history_never_calls_model():
    from conversation_transform import restate
    with patch('conversation_transform.transform_client',side_effect=AssertionError('model call')):
        assert 'Which answer' in restate('Simplify that',[], 'English')['answer']


def test_restatement_uses_only_previous_answer_and_one_model_call():
    from conversation_transform import restate
    from types import SimpleNamespace
    calls=[]
    fake=SimpleNamespace(begin=lambda:(None,'test'),finish=lambda t,r:{'call_count':1},
        responses=SimpleNamespace(create=lambda **kw:(calls.append(kw) or SimpleNamespace(output_text='Presence does not establish delivery. [E01]'))))
    with patch('conversation_transform.transform_client',return_value=fake):
        result=restate('Explain that more simply',[
            {'role':'user','content':'User instruction to research again'},
            {'role':'assistant','content':'Recorded presence does not establish delivery. [E01]'}],'English')
    assert len(calls)==1
    assert calls[0]['input']==[{'role':'user','content':'Recorded presence does not establish delivery. [E01]'}]
    assert 'at most 120 words' in calls[0]['instructions']
    assert result['evidence']==[] and '[E01]' not in result['answer']
    assert 'Sources remain with the original answer' in result['answer']


def test_public_summary_lookup_and_invalid_release():
    client=TestClient(web_api.app)
    summary=client.get('/api/geography').json()
    assert summary['preferred_release_id']==geographic_model().preferred
    matches=client.get('/api/geography',params={'name':'Bamba','level':'commune'}).json()
    assert matches['total_matches']==2
    assert client.get('/api/geography',params={'release':'made-up'}).status_code==404
    assert client.get('/api/geography',params={'level':'made-up'}).status_code==400
    client.close()


def test_joined_evidence_keeps_geography_versions_separate():
    evidence=canonical_geography_evidence('Compare needs, presence and EU projects in Mopti')
    assert len(evidence)==1
    assert 'not an approved identity crosswalk' in evidence[0]['content']
    assert '159' in evidence[0]['content'] and '815' in evidence[0]['content']
