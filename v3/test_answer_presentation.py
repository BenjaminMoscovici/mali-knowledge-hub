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


def invoke(depth, text, extra_evidence=()):
    source = ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef)
              and n.name == '_generate_grounded_answer')
    calls = []
    ledger = [{'evidence_id': 'E01', 'source_type': 'knowledge_base_document',
               'document_title': 'Synthetic source', 'document_id': 'qa',
               'publication_date': '2026-10-06', 'section': 'Body paragraph 4', 'locator': 'Body paragraph 4',
               'page_number': None, 'geographic_scope': 'Mali national',
               'content': 'Planned for 2027. EUR 890.10 and USD 12,345.67. No delivery evidence.'}]
    ledger.extend(extra_evidence)
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


@pytest.mark.parametrize('depth', ['balanced', 'deep'])
def test_professional_synthesis_keeps_conflicting_roles_and_missing_values(depth):
    evidence = [
        {'evidence_id': 'E02', 'source_type': 'fongim_structured',
         'source_family': 'FONGIM intervention data', 'content':
         'Project QA; source-reported donor: EU; recorded associated '
         'organisation: Actor A; implementer: not supplied; '
         'disbursement: missing; source status: Closed; sync: 2026-08-28.'},
        {'evidence_id': 'E03', 'source_type': 'eu_iati_activity',
         'source_family': 'European Union', 'content':
         'Project QA; publisher: EC; status: Implementation; '
         'title mentions Mopti; operational locations: not verified.'},
    ]
    calls, result, ledger = invoke(depth, 'Roles remain unverified [E02, E03].', evidence)
    assert len(calls) == 1
    for item in evidence:
        assert item['content'] in calls[0]['input']
    assert result['evidence'] == ledger
    assert result['execution_trace']['synthesis_context']['citation_audit']['valid']
    assert instructions('quick') not in calls[0]['instructions']


def test_quick_presentation_unchanged_from_accepted_baseline():
    import subprocess
    baseline = subprocess.check_output(
        ['git', 'show', 'd7484a66248171180d0ad43e10b5fea461f6668f:v3/answer_presentation.py'],
        cwd=Path(__file__).parent, text=True)
    tree = ast.parse(baseline)
    original = next(ast.literal_eval(n.value) for n in tree.body
                    if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'DEFAULT_RESPONSE'
                            for t in n.targets))
    assert instructions('quick') == original
