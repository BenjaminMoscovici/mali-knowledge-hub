"""Final presentation must preserve evidence provenance and fail-closed citations."""
import ast
import re
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from answer_presentation import instructions
from citations import verify
from language import answer_language
from synthesis_context import prepare, serialize


def invoke(depth, text):
    source = ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef)
              and n.name == '_generate_grounded_answer')
    calls = []
    ledger = [{'evidence_id': 'E01', 'source_type': 'knowledge_base_document',
               'document_title': 'Synthetic source', 'document_id': 'qa',
               'publication_date': '2026-10-06', 'section': 'Body paragraph 4', 'locator': 'Body paragraph 4',
               'page_number': None, 'geographic_scope': 'Mali national',
               'content': 'Planned for 2027. EUR 890.10 and USD 12,345.67. No delivery evidence.'}]
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=text)
    research = {'ledger': ledger, 'joined': {}, 'geography': {}, 'source_plan': {},
                'family_counts': {}, 'hapi_raw_count': 0, 'fongim_project_count': 0,
                'research_seconds': 0, 'execution_trace': {}}
    ns = {'re': re, 'time': time, 'PHASE': SimpleNamespace(set=lambda _: None),
          'get_mode': lambda _: {'document_count': 3, 'max_output_tokens': 1200},
          'run_four_source_research': lambda *args, **kw: research,
          'prepare_synthesis': prepare, 'serialize_synthesis': serialize,
          'build_join_context': lambda *args: {}, 'prompt_context': lambda _: '',
          'answer_instructions': instructions, 'availability_note': lambda *args: '',
          'intersectoral_locality_note': lambda _: '', 'answer_language': answer_language,
          'verify_citations': verify,
          'openai_client': SimpleNamespace(responses=SimpleNamespace(create=create))}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'synthesis-contract', 'exec'), ns)
    result = ns['_generate_grounded_answer']('Quel budget est prévu ?', depth=depth)
    return calls, result, ledger


@pytest.mark.parametrize('depth', ['quick', 'balanced', 'deep'])
def test_same_evidence_single_pass_original_currencies_dates_locations(depth):
    calls, result, ledger = invoke(depth, 'Prévu pour 2027 [E01].')
    assert len(calls) == 1 and calls[0]['reasoning'] == {'effort': 'none'}
    prompt = calls[0]['input']
    for exact in ['EUR 890.10', 'USD 12,345.67', '2027', '2026-10-06',
                  'Mali national', 'No delivery evidence.', 'Body paragraph 4']:
        assert exact in prompt
    assert 'French' in prompt
    assert result['evidence'] == ledger
    assert result['execution_trace']['synthesis_context']['citation_audit']['valid']


@pytest.mark.parametrize('depth', ['quick', 'balanced', 'deep'])
def test_presentation_still_rejects_unprovided_evidence_id(depth):
    _, result, _ = invoke(depth, 'Unsupported claim [E99].')
    assert result['answer'].startswith('I could not verify')
    assert not result['execution_trace']['synthesis_context']['citation_audit']['valid']
