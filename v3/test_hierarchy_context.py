"""Exact hierarchy follow-ups retain level, identity and release-specific citations."""
import json
import sys
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from geographic_model import geographic_model
from geography_context import resolve_hierarchy_followup
import web_api


def history(question):
    return [{'role':'user','content':question},
            {'role':'assistant','content':'Konna belongs to Gao, all 999 are EU-funded. [E99]'}]


@pytest.mark.parametrize('followup', ['And Konna?', 'And in Konna?', 'What about Konna?',
                                      'Same for Konna?', 'Et à Konna ?', 'Et Konna ?'])
def test_original_registry_paths_with_zero_models(followup):
    question = resolve_hierarchy_followup(followup, history('What is the parent hierarchy of Socoura commune?'))
    assert question == 'What is the parent hierarchy of konna commune?'
    model = geographic_model()
    original = model.lookup('Konna','commune',model.preferred)[0]
    assert [p['name'] for p in original['path']] == ['Mali','MOPTI','KONNA','KONNA']
    result = model.answer(question)
    records = json.loads(result['evidence'][0]['content'])['records']
    assert any(r['id'] == original['id'] for r in records)
    assert '[E01]' in result['answer'] and '999' not in result['answer'] and 'funded' not in result['answer']


@pytest.mark.parametrize('base,followup', [
    ('What is the parent hierarchy of Socoura commune?', 'And Bamba?'),
    ('What is the parent hierarchy of Bamba commune?', 'And Konna?'),
    ('What is the parent hierarchy of Socoura commune?', 'And Unknownville?'),
    ('What is the parent hierarchy of Socoura commune?', 'And Konna and Gao?'),
    ('What is the parent hierarchy of Socoura commune?', 'And Konna funded by the EU?'),
    ('What is the parent hierarchy of Socoura commune?', 'And Konna in 2025?'),
    ('What population is recorded for Socoura commune?', 'And Konna?'),
    ('How many communes are in Mali?', 'And Konna?'),
])
def test_ambiguous_names_and_new_constraints_keep_semantic_resolution(base, followup):
    assert resolve_hierarchy_followup(followup, history(base)) is None


def test_context_chain_topic_reset_and_api_without_engine():
    prior=history('What is the parent hierarchy of Socoura commune?')
    resolved=resolve_hierarchy_followup('And Konna?', prior)
    prior.extend([{'role':'user','content':'And Konna?'},
                  {'role':'assistant','content':'Wrong Gao.', 'standalone_question':resolved},
                  {'role':'user','content':'Thanks!'}])
    assert 'socoura commune' in resolve_hierarchy_followup('And Socoura?', prior)
    client=TestClient(web_api.app,base_url='http://127.0.0.1:8765')
    with patch.dict(sys.modules,{'analysis_core':None}):
        response=client.post('/api/chat',json={'question':'And Konna?','prior_messages':prior},
                             headers={'Origin':'http://127.0.0.1:8765'})
        assert response.status_code==200
        body=response.json()
        assert body['metrics']['context_resolution_method']=='structured_geographic_hierarchy'
        assert body['metrics']['model_calls']==body['metrics']['embedding_calls']==0
        assert body['metrics']['estimated_usd']==0 and body['evidence']
        # No prior guest context is implicitly reused.
        response=client.post('/api/chat',json={'question':'And Konna?'},
                             headers={'Origin':'http://127.0.0.1:8765'})
        assert response.status_code==503
    client.close()
    prior.append({'role':'user','content':'What are the humanitarian needs in Socoura?'})
    assert resolve_hierarchy_followup('And Konna?', prior) is None
