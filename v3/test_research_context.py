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


def test_long_latest_answer_keeps_bounded_head_and_tail_for_late_identifiers():
    messages = [
        {'role':'user', 'content':'List the documented projects in Gao.'},
        {'role':'assistant', 'content':(
            'Gao project roster begins. ' + ('x' * 6800) +
            ' Final entries: FONGIM Project ID 664; World Bank project P166811.')},
    ]
    text = conversation_context(messages)
    assert 'Gao project roster begins.' in text
    assert 'FONGIM Project ID 664' in text and 'P166811' in text
    assert 'middle omitted; context only' in text
    assert len(text) < 7700


def test_long_latest_answer_keeps_only_qualified_middle_identifiers():
    messages = [
        {'role':'user', 'content':'List the documented projects in Gao.'},
        {'role':'assistant', 'content':(
            'Current Gao roster begins. ' + ('x' * 3300) +
            ' Middle entries: FONGIM Project ID 664; World Bank project P166811; '
            'EU activity XI-IATI-EC_INTPA-2023-PC-34274; budget 999; year 2099. ' +
            ('y' * 3300) + ' Final context.')},
    ]
    text = conversation_context(messages)
    assert 'Current Gao roster begins.' in text and 'Final context.' in text
    assert 'FONGIM project IDs 664' in text
    assert 'World Bank project IDs P166811' in text
    assert 'EU IATI activity IDs XI-IATI-EC_INTPA-2023-PC-34274' in text
    assert 'budget 999' not in text and 'year 2099' not in text
    assert 'source-qualified identifiers retained from omitted context only' in text
    assert len(text) < 7700


def test_long_mixed_roster_reserves_middle_identifier_slots_per_source():
    fongim_ids = ', '.join(map(str, range(1, 21)))
    messages = [
        {'role':'user', 'content':'List the documented projects across all three sources.'},
        {'role':'assistant', 'content':(
            'Mixed-source roster begins. ' + ('x' * 3300) +
            f' FONGIM project IDs: {fongim_ids}; '
            'World Bank project P166811; '
            'EU activity XI-IATI-EC_INTPA-2023-PC-34274; '
            'budget 999; year 2099. ' +
            ('y' * 3300) + ' Mixed-source roster ends.')},
    ]
    text = conversation_context(messages)
    assert 'FONGIM project IDs 1' in text
    assert 'World Bank project IDs P166811' in text
    assert 'EU IATI activity IDs XI-IATI-EC_INTPA-2023-PC-34274' in text
    assert 'budget 999' not in text and 'year 2099' not in text
    assert 'source-qualified identifiers retained from omitted context only' in text
    assert len(text) < 7700


def test_long_context_does_not_promote_unqualified_middle_numbers():
    text = conversation_context([{'role':'assistant', 'content':(
        'Roster begins. ' + ('x' * 3300) +
        ' Middle values: project 664; budget 999; year 2099. ' +
        ('y' * 3300) + ' Roster ends.')}])
    assert '664' not in text and '999' not in text and '2099' not in text
    assert 'source-qualified identifiers retained' not in text
    assert len(text) < 6050


def test_context_discards_an_obsolete_topic_after_a_substantive_change():
    messages = [
        {'role':'user', 'content':'What are the humanitarian needs in Mopti?'},
        {'role':'assistant', 'content':'Mopti context reports a gap [E01].'},
        {'role':'user', 'content':'Which organisations operate in Gao?'},
        {'role':'assistant', 'content':'Gao organisation roster [E02].'},
    ]
    text = conversation_context(messages)
    assert 'Gao' in text and 'organisation roster' in text
    assert 'Mopti' not in text and '[E01]' not in text


def test_social_turns_do_not_hide_the_latest_substantive_topic():
    messages = [
        {'role':'user', 'content':'What are the humanitarian needs in Mopti?'},
        {'role':'assistant', 'content':'Old Mopti context [E01].'},
        {'role':'user', 'content':'List the documented FONGIM projects in Gao.'},
        {'role':'assistant', 'content':'FONGIM project ID 32; Project ID 664. [E02]'},
        {'role':'user', 'content':'Thanks!'},
        {'role':'assistant', 'content':'You are welcome.'},
    ]
    text = conversation_context(messages)
    assert 'FONGIM project ID 32' in text and 'Thanks!' in text
    assert 'Old Mopti context' not in text and '[E01]' not in text


def test_resolved_followup_standalone_question_is_a_new_topic_boundary():
    messages = [
        {'role':'user', 'content':'What are the humanitarian needs in Mopti?'},
        {'role':'assistant', 'content':'Old Mopti context [E01].'},
        {'role':'user', 'content':'And there?',
         'standalone_question':'Which organisations operate in Gao?'},
        {'role':'assistant', 'content':'Gao organisation roster [E02].'},
    ]
    text = conversation_context(messages)
    assert 'Which organisations operate in Gao?' in text
    assert 'Old Mopti context' not in text


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
