"""Continuity controls use real, versioned geography and fresh API research."""
import json
import re
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from conversation_state import resolve,state_from_history
from geographic_model import geographic_model
from query_router import classify
import web_api


def history(question):
    return [{'role':'user','content':question},{'role':'assistant','content':'A deliberately false answer: 999 units, all EU funded.'}]


def test_metric_comes_from_question_and_counts_from_original_registry():
    result=resolve('And in Gao?',history('How many municipalities are in Mali?'))
    assert result['method']=='structured_context' and not result['needs_model']
    answer=geographic_model().answer(result['standalone_question'])
    assert '44 recorded commune(s)' in answer['answer'] and '999' not in answer['answer']
    evidence=json.loads(answer['evidence'][0]['content'])
    count=evidence['query_scope_counts'][0]
    assert count['count']==len(count['source_unit_ids'])==44
    assert all(geographic_model().units[uid]['release_id']==count['release_id'] for uid in count['source_unit_ids'])


def test_cercle_scope_does_not_silently_become_region():
    result=resolve('And in Ansongo?',history('How many communes are in Gao cercle?'))
    answer=geographic_model().answer(result['standalone_question'])
    assert '4 recorded commune(s)' in answer['answer']
    assert json.loads(answer['evidence'][0]['content'])['query_scope_counts'][0]['parent_level']=='cercle'


def test_population_sex_period_and_level_carry_without_assistant_facts():
    prior=history('What is the 2023 population projection for Bandiagara region?')
    female=resolve('What about women?',prior)
    assert 'female population' in female['standalone_question']
    prior.append({'role':'assistant','standalone_question':female['standalone_question'],'content':'Wrong 999 female people.'})
    cercle=resolve('And at cercle level?',prior)
    assert '2023' in cercle['standalone_question'] and 'female population' in cercle['standalone_question']
    assert 'Bandiagara cercle' in cercle['standalone_question'] and '999' not in cercle['standalone_question']


def test_social_turn_and_topic_reset():
    prior=history('How many communes are in Mali?')+[{'role':'user','content':'Thanks!'}]
    assert 'communes' in resolve('And in Gao?',prior)['standalone_question']
    prior.append({'role':'user','content':'What IDP stocks does DTM report for Socoura in September 2025?'})
    result=resolve('What about women?',prior)
    assert 'Socoura' in result['standalone_question'] and '2025' in result['standalone_question']
    assert 'female' in result['standalone_question'] and result['state']['topic']=='displacement'


def test_genuine_ambiguities_and_explicit_place_control():
    for question,base,kind in [('How much was that?',"Compare Mali’s 2026 funding requirement, reported funding and people targeted.",'measure'),
        ('When did it end?','Compare the World Bank P144442 evaluation and the EIB Kabala project record.','project'),
        ('What about women?','Which organisations are present in Mopti in OCHA 3W?','indicator'),
        ('And how many communes are there?','Compare the populations of Gao region and Mopti region in 2023.','place')]:
        result=resolve(question,history(base))
        assert result['clarification_required'] and kind in result['clarification_answer'].lower()
        assert not result['needs_model']
    assert resolve('How many communes are there?',[])['clarification_required']
    assert not resolve('How many communes are there in Mali?',[])['clarification_required']


def test_obvious_followup_never_loads_model_engine_and_owns_context():
    client=TestClient(web_api.app,base_url='https://mali-knowledge-hub.onrender.com')
    with patch.dict('sys.modules',{'analysis_core':None}):
        a=client.post('/api/chat',json={'question':'And in Gao?','prior_messages':history('How many municipalities are in Mali?')},headers={'Origin':'https://mali-knowledge-hub.onrender.com'})
        b=client.post('/api/chat',json={'question':'And in Gao?','prior_messages':history('How many cercles are in Mali?')},headers={'Origin':'https://mali-knowledge-hub.onrender.com'})
    assert a.status_code==b.status_code==200
    assert '44 recorded commune(s)' in a.json()['answer']
    assert '16 recorded cercle(s)' in b.json()['answer']
    for r in [a,b]:
        assert r.json()['conversation_state']['context_only'] is True
        assert r.json()['metrics']['model_calls']==r.json()['metrics']['embedding_calls']==0


def test_operational_presence_remains_joined_research():
    assert classify('Which communes have documented intervention presence in Mopti?')['path']=='complex_research'


def test_french_evidence_limits_do_not_become_platform_source_inventory():
    import ast
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='is_source_inventory_question')
    from synthesis_context import fold
    namespace={'re':re,'normalize_text':fold}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'inventory-control','exec'),namespace)
    inventory=namespace['is_source_inventory_question']
    query='Quelles sont ses limites comme preuve de résultats ?'
    assert not inventory(query)
    resolved=resolve(query,history('Que prévoit la SNEDD 2024–2033 pour les services de base ?'))
    assert 'SNEDD' in resolved['standalone_question'] and not inventory(resolved['standalone_question'])
    assert not resolved['needs_model'] and resolved['language']=='French'
    for question in ['What are your sources?', 'Quelles sont vos sources ?', 'Welche Quellen hast du?']:
        assert inventory(question)
