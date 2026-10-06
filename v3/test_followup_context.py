"""Slot carry-over preserves query constraints and always performs fresh research."""
import sys
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from followup_context import resolve_slots
import web_api


def history(question):
    return [{'role': 'user', 'content': question},
            {'role': 'assistant', 'content': '999 people, all female, in 2099. [E99]'}]


@pytest.mark.parametrize('base,followup,required', [
    ('What is the 2023 population projection for Bandiagara region?', 'What about women?',
     ['female population', '2023', 'Bandiagara region']),
    ('Quelle est la population projetée de la région de Gao en 2023 ?', 'Et les hommes ?',
     ['male population', '2023', 'région de Gao']),
    ('What IDP stocks does DTM report for Socoura in September 2025?', 'What about women?',
     ['female sex-disaggregated', 'DTM', 'Socoura', 'September 2025', 'missing breakdown']),
    ('What intersectoral people-in-need observations are available for Mopti in OCHA HAPI?',
     'What about women?', ['female sex-disaggregated', 'intersectoral', 'Mopti', 'OCHA HAPI']),
    ('What is the 2023 population projection for Bandiagara region?', 'And in 2024?',
     ['2024', 'population projection', 'Bandiagara region']),
    ('Quelle est la population projetée de la région de Mopti en 2023 ?', 'Et en 2024 ?',
     ['2024', 'population projetée', 'région de Mopti']),
    ('What is the 2023 female population projection for Bandiagara region?', 'And at cercle level?',
     ['2023', 'female population', 'Bandiagara cercle']),
])
def test_preserved_slots_no_assistant_facts(base, followup, required):
    result = resolve_slots(followup, history(base))
    assert result and result['state']['context_only']
    assert all(word in result['standalone_question'] for word in required)
    assert '999' not in result['standalone_question'] and '2099' not in result['standalone_question']


def test_chains_sex_switch_social_and_topic_reset():
    prior = history('What is the 2023 population projection for Bandiagara region?')
    female = resolve_slots('What about women?', prior)['standalone_question']
    prior.extend([{'role':'user','content':'What about women?'},
                  {'role':'assistant','standalone_question':female,'content':'Wrong 999.'},
                  {'role':'user','content':'Thanks!'}])
    male = resolve_slots('What about men?', prior)['standalone_question']
    assert 'male population' in male and 'female population' not in male
    assert 'Bandiagara cercle' in resolve_slots('And at cercle level?', prior)['standalone_question']
    prior.append({'role':'user','content':'Which organisations operate in Gao?'})
    assert resolve_slots('What about women?', prior) is None


@pytest.mark.parametrize('base,followup', [
    ('Which organisations operate in Mopti?', 'What about women?'),
    ('Compare population and funding in Gao.', 'What about women?'),
    ('What female and male population projections exist for Gao?', 'What about women?'),
    ('What is the population of women in Gao?', 'What about men?'),
    ('What are the needs and population of Gao?', 'What about women?'),
    ('How many inhabitants are in Gao?', 'What about women?'),
    ('What IDP stock does DTM Round 83 September 2025 report for Socoura?', 'And in 2024?'),
    ('Compare the 2023 and 2024 population of Gao.', 'And in 2025?'),
    ('What population was reported on 2023-09-01 for Gao?', 'And in 2024?'),
    ('What is the population of Bamba commune in 2023?', 'And at commune level?'),
    ('What is the population of Unknownville region in 2023?', 'And at cercle level?'),
    ('What is the population of Gao in 2023?', 'What about women and children?'),
    ('What is the population of Gao in 2023?', 'Which of those are still active?'),
    ('What is the population of Gao in 2023?', 'Are all 999 of them EU-funded?'),
])
def test_ambiguity_and_unsupported_scope_keep_existing_resolver(base, followup):
    assert resolve_slots(followup, history(base)) is None


def test_api_skips_only_rewrite_and_retrieves_for_each_guest():
    requests = []
    def research(question, **kwargs):
        requests.append((question, kwargs))
        return {'answer':'Fresh evidence only [E01]', 'evidence':[{'evidence_id':'E01',
                'content':'Original sex-specific observation; not historical answer text.'}]}
    def no_rewrite(*args, **kwargs):
        raise AssertionError('unnecessary rewrite pass')
    engine = SimpleNamespace(generate_grounded_answer=research, is_source_inventory_question=lambda q:False,
        likely_context_dependent_followup=lambda *args:True, resolve_conversational_question=no_rewrite,
        source_inventory_answer=lambda:'', openai_client=None)
    client = TestClient(web_api.app, base_url='http://127.0.0.1:8765')
    with patch.dict(sys.modules, {'analysis_core':engine}):
        for place in ['Bandiagara', 'Gao']:
            response = client.post('/api/chat', json={'question':'What about women?',
                'prior_messages':history(f'What is the 2023 population projection for {place} region?')},
                headers={'Origin':'http://127.0.0.1:8765'})
            assert response.status_code == 200
            body = response.json()
            assert body['metrics']['context_resolution_method'] == 'structured_query_slots'
            assert body['metrics']['context_api_usage'] == {}
            assert body['evidence'][0]['evidence_id'] == 'E01'
            assert place in body['standalone_question'] and '999' not in body['standalone_question']
        assert len(requests) == 2 and requests[0][0] != requests[1][0]
        # Missing history must not inherit another guest's topic.
        response = client.post('/api/chat', json={'question':'What about women?'},
                               headers={'Origin':'http://127.0.0.1:8765'})
        assert response.status_code == 503
    client.close()
