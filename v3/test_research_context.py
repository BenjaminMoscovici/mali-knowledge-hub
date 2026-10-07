"""Professional follow-ups preserve references and re-research their facts."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from research_context import conversation_context, has_reference, preserve_lookup_namespace


@pytest.mark.parametrize('question', [
    'Which of those projects have a reported end date in 2026?',
    'Which of them have an explicitly reported EU donor?',
    'Can you compare these interventions with documented needs in Mopti?',
    'How does that compare with the evidence for Gao?',
    'Which projects listed above have a successor documented?',
    'Lesquels de ces projets ont une date de fin en 2026 ?',
    'Quels financements parmi ceux-ci sont des décaissements vérifiés ?',
    'Quels projets parmi eux ont un acteur de mise en œuvre identifié ?',
    'Quelles interventions mentionnées ci-dessus sont encore actives ?',
])
def test_references_inside_long_questions(question):
    assert has_reference(question)
    for filename in ('app.py', 'analysis_core.py'):
        tree = ast.parse(Path(__file__).with_name(filename).read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'likely_context_dependent_followup')
        scope = {'normalize_text': lambda x: x.casefold()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), filename, 'exec'), scope)
        assert scope[function.name](question, [{'role': 'user', 'content': 'Earlier question'}])
        assert not scope[function.name](question, [])


@pytest.mark.parametrize('question', [
    'Which projects have a reported end date in 2026?',
    'Compare EU financing and humanitarian needs in Mopti.',
    'What do evaluations report about interventions in Gao?',
    'Quels projets sont financés par des bailleurs européens au Mali ?',
])
def test_standalone_questions_are_not_references(question):
    assert not has_reference(question)


def test_last_roster_keeps_late_identifiers_without_unbounded_history():
    roster = 'Project context. ' * 160 + 'Final listed project: P144442.'
    messages = [{'role': 'assistant', 'content': 'Old answer. ' * 1000},
                {'role': 'user', 'content': 'List the documented projects in Mali.'},
                {'role': 'assistant', 'content': roster}]
    text = conversation_context(messages)
    assert 'Final listed project: P144442.' in text
    assert 'ASSISTANT CONTEXT ONLY:' in text
    assert len(text) < 7000
    assert len(conversation_context([{'role':'assistant', 'content':'x'*50000}])) < 6050


def test_rewriter_preserves_set_and_date_rules_and_context_is_not_evidence():
    captured = []
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(output_text='Investigate reported end dates for P144442 in 2026.')
    tree = ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'resolve_conversational_question')
    scope = {'openai_client': SimpleNamespace(responses=SimpleNamespace(create=create))}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'rewrite', 'exec'), scope)
    result = scope[function.name]('Which of those projects end this year?', [
        {'role':'user', 'content':'List projects in Mali.'},
        {'role':'assistant', 'content':'Context. '*220+'P144442 reportedly ended in 2099.'}])
    assert 'P144442' in captured[0]['input']
    assert 'CURRENT QUERY DATE (UTC):' in captured[0]['input']
    assert 'not proof of status, funding' in captured[0]['instructions']
    assert 'fresh retrieval' in captured[0]['instructions']
    assert 'calendar period' in captured[0]['instructions']
    assert result == 'Investigate reported end dates for P144442 in 2026.'


def test_rewrite_dropping_source_namespace_still_selects_exact_roster():
    from project_references import fongim_project_ids
    messages=[{'role':'assistant','content':'FONGIM records: Project ID 664; Project ID 434; Project ID 696; Project ID 32. All allegedly ended in 2099.'}]
    rewritten='Which of those projects (IDs 664, 434, 696, 32) have a reported end date in 2026?'
    result=preserve_lookup_namespace(rewritten,'Which of those projects have a reported end date in 2026?',messages)
    assert fongim_project_ids(result)==(32,434,664,696)
    assert '2099' not in result and 'allegedly' not in result


@pytest.mark.parametrize('question,rewritten', [
    ('Which projects end in 2026?','Which projects (IDs 32, 664) end in 2026?'),
    ('Which of those projects end in 2026?','Which projects (IDs 32, 999) end in 2026?'),
    ('Which of those projects end in 2026?','Which World Bank projects (IDs 32, 664) end in 2026?'),
])
def test_namespace_recovery_never_invents_a_source_for_unknown_or_new_sets(question,rewritten):
    messages=[{'role':'assistant','content':'FONGIM records: Project ID 664; Project ID 32.'}]
    assert preserve_lookup_namespace(rewritten,question,messages)==rewritten
