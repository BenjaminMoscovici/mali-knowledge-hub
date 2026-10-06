"""Narrow geography continuity tested against real release-specific records."""
import json
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from geographic_model import geographic_model
from geography_context import resolve_count_followup
import web_api


def history(question):
    return [{'role': 'user', 'content': question},
            {'role': 'assistant', 'content': '999 units, all EU funded.'}]


@pytest.mark.parametrize('base,followup,count,level', [
    ('How many municipalities are in Mali?', 'And in Gao?', 44, 'region'),
    ('How many communes are in Mali?', 'And in Mopti?', 50, 'region'),
    ('How many communes are in Gao cercle?', 'And in Ansongo?', 4, 'cercle'),
    ('How many cercles are in Mali?', 'And in Gao?', 16, 'region'),
    ('How many communes are in Mali?', 'And in Mopti cercle?', 12, 'cercle'),
    ('Combien de communes compte le Mali ?', 'Et à Gao ?', 44, 'region'),
])
def test_real_counts_and_citation_witnesses(base, followup, count, level):
    standalone = resolve_count_followup(followup, history(base))
    assert standalone and '999' not in standalone and 'funded' not in standalone
    result = geographic_model().answer(standalone)
    witness = json.loads(result['evidence'][0]['content'])['query_scope_counts'][0]
    assert witness['count'] == len(set(witness['source_unit_ids'])) == count
    assert witness['parent_level'] == level
    assert all(geographic_model().units[uid]['release_id'] == witness['release_id']
               for uid in witness['source_unit_ids'])
    assert '[E01]' in result['answer']


def test_topic_reset_social_turn_chain_and_explicit_level():
    prior = history('How many municipalities are in Mali?')
    prior.append({'role': 'user', 'content': 'Thanks!'})
    gao = resolve_count_followup('And in Gao?', prior)
    prior.extend([{'role': 'user', 'content': 'And in Gao?'},
                  {'role': 'assistant', 'content': '999', 'standalone_question': gao}])
    assert resolve_count_followup('And in Mopti?', prior) == 'How many communes are in mopti region?'
    prior.append({'role': 'user', 'content': 'What are humanitarian needs in Mopti?'})
    assert resolve_count_followup('And in Gao?', prior) is None


@pytest.mark.parametrize('base,followup', [
    ('How many communes are in Mali?', 'And in Unknownville?'),
    ('How many communes are in Mali?', 'And in Gao and Mopti?'),
    ('How many communes are in Mali?', 'And in Gao funded by the EU?'),
    ('How many communes are in Mali?', 'What about women?'),
    ('How many communes are in Mali?', 'And in Bamba commune?'),
    ('How many communes are in Mali?', 'And in Gao in 2025?'),
    ('How many communes are in Gao and Mopti?', 'And in Sikasso?'),
    ('How many communes are in Mali?', 'And in Gao commune?'),
    ('How many EU-funded communes are in Mali?', 'And in Gao?'),
    ('What is the population of Mali?', 'And in Gao?'),
])
def test_ambiguous_or_analytical_questions_keep_existing_resolver(base, followup):
    assert resolve_count_followup(followup, history(base)) is None


def test_api_no_model_no_network_no_cross_guest_context():
    client = TestClient(web_api.app, base_url='https://mali-knowledge-hub.onrender.com')
    with patch.dict('sys.modules', {'analysis_core': None}), \
         patch('requests.sessions.Session.request', side_effect=AssertionError('network')), \
         patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('network')):
        for base, expected in [('How many municipalities are in Mali?', '44 recorded commune'),
                               ('How many cercles are in Mali?', '16 recorded cercle')]:
            r = client.post('/api/chat', json={'question': 'And in Gao?', 'prior_messages': history(base)},
                            headers={'Origin': 'https://mali-knowledge-hub.onrender.com'})
            assert r.status_code == 200 and expected in r.json()['answer']
            assert r.json()['metrics']['context_resolution_method'] == 'structured_geographic_count'
            assert r.json()['metrics']['model_calls'] == r.json()['metrics']['embedding_calls'] == 0
            assert r.json()['metrics']['estimated_usd'] == 0
        # A new guest has no context from either of the preceding requests.
        r = client.post('/api/chat', json={'question': 'And in Gao?'},
                        headers={'Origin': 'https://mali-knowledge-hub.onrender.com'})
        assert r.status_code == 503
    client.close()
