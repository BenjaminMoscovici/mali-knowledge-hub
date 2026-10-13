"""Rewriting may change wording, never silently widen a selected project set."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest


def rewrite(filename, question, messages, output):
    tree = ast.parse(Path(__file__).with_name(filename).read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'resolve_conversational_question')
    client = SimpleNamespace(responses=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(output_text=output)))
    scope = {'openai_client': client}
    exec(compile(ast.Module(body=[function], type_ignores=[]), filename, 'exec'), scope)
    return scope[function.name](question, messages)


@pytest.mark.parametrize('filename', ['analysis_core.py', 'app.py'])
def test_actual_eu_donor_rewrite_cannot_drop_selected_fongim_id(filename):
    from project_references import fongim_project_ids
    messages = [
        {'role': 'user', 'content': 'What are the humanitarian needs in Mopti?'},
        {'role': 'assistant', 'content': 'Old Mopti topic [E99].'},
        {'role': 'user', 'content': 'Which FONGIM projects are listed for Gao?'},
        {'role': 'assistant', 'content': 'Selected latest project: FONGIM Project ID 664.'},
    ]
    result = rewrite(filename, 'Which of those projects have an explicitly reported EU donor?',
                     messages, 'Which FONGIM projects listed for Gao have an explicitly reported EU donor?')
    assert fongim_project_ids(result) == (664,)
    assert 'Mopti' not in result and 'E99' not in result


@pytest.mark.parametrize('filename', ['analysis_core.py', 'app.py'])
def test_model_cannot_replace_selected_set_with_unknown_or_partial_ids(filename):
    from project_references import fongim_project_ids
    messages = [{'role': 'assistant', 'content': 'FONGIM project IDs 32, 664. Alleged donor EU.'}]
    for output in ['Which FONGIM project ID 999 is EU funded?',
                   'Which FONGIM project ID 664 is EU funded?']:
        result = rewrite(filename, 'Which of those projects are EU-funded?', messages, output)
        assert fongim_project_ids(result) == (32, 664)
        assert 'Alleged' not in result


@pytest.mark.parametrize('question,roster,namespace,identifier', [
    ('Which of those projects are EU-funded?', 'FONGIM Project ID 664.', 'FONGIM', '664'),
    ('Lesquels d’entre eux ont un bailleur européen explicitement déclaré ?',
     'FONGIM Project ID 664.', 'FONGIM', '664'),
    ('Which of those projects have an implementing agency?',
     'World Bank project P164032.', 'World Bank', 'P164032'),
    ('Lesquels parmi eux ont un financement déclaré ?',
     'World Bank project P164032.', 'World Bank', 'P164032'),
    ('Which of those projects have a documented implementer?',
     'EU activity XI-IATI-EC_INTPA-2023-PC-34274;', 'EU IATI', 'XI-IATI-EC_INTPA-2023-PC-34274'),
    ('Lesquels de ces projets ont un acteur de mise en œuvre déclaré ?',
     'EU activity XI-IATI-EC_INTPA-2023-PC-34274;', 'EU IATI', 'XI-IATI-EC_INTPA-2023-PC-34274'),
])
def test_bounded_guard_preserves_namespace_without_prior_claims(question,roster,namespace,identifier):
    from research_context import preserve_project_selection
    result = preserve_project_selection('Which projects were successfully completed in 2099?',
                                        question,[{'role':'assistant','content':roster+' Budget 999; ended in 2099. [E99]'}])
    assert namespace in result and identifier in result and question in result
    assert '2099' not in result and '999' not in result and 'E99' not in result


def test_guard_uses_canonical_identifier_column_not_titles_or_excluded_notes():
    from project_references import fongim_project_ids
    from research_context import preserve_project_selection
    table=('| Source identifier | Project | Reported end/closing |\n|---|---|---|\n'
           '| FONGIM project ID 664 | Successor to FONGIM project ID 32 | 2099-01-01 |\n'
           '\nOther returned records: FONGIM project ID 32.\n')
    result=preserve_project_selection('List all FONGIM projects.',
        'Which of those projects have an EU donor?',[{'role':'assistant','content':table}])
    assert fongim_project_ids(result)==(664,)
    assert '32' not in result and '2099' not in result


@pytest.mark.parametrize('question,namespace,identifier,excluded', [
    ('Which of those FONGIM projects have a donor?', 'FONGIM', '664', 'P164032'),
    ('Which of those World Bank projects have an implementer?', 'World Bank', 'P164032', '664'),
    ("Lesquels de ces projets de l’UE ont un financement déclaré ?", 'EU IATI', 'XI-IATI-EC_INTPA-2023-PC-34274', '664'),
])
def test_explicit_source_selects_only_that_namespace(question,namespace,identifier,excluded):
    from research_context import preserve_project_selection
    mixed='FONGIM project ID 664. World Bank P164032. EU XI-IATI-EC_INTPA-2023-PC-34274;'
    result=preserve_project_selection('Compare all portfolios.',question,[{'role':'assistant','content':mixed}])
    assert namespace in result and identifier in result and excluded not in result


@pytest.mark.parametrize('question,roster', [
    ('Which of those projects have a donor?', 'FONGIM Project ID 664. World Bank P164032.'),
    ('Which of those projects have a donor?', 'FONGIM project IDs '+', '.join(map(str,range(1,14)))+'.'),
    ('Which of those projects have a donor?', 'FONGIM project ID 664. '+'x'*6000),
    ('Which of those projects have a donor?', 'Selected source identifiers for this filter: none.'),
    ('Which of those projects and project ID 999 have a donor?', 'FONGIM Project ID 664.'),
    ('Which projects have a donor?', 'FONGIM Project ID 664.'),
])
def test_guard_does_not_infer_complete_or_new_project_sets(question,roster):
    from research_context import preserve_project_selection
    output='Unchanged semantic question.'
    assert preserve_project_selection(output,question,[{'role':'assistant','content':roster}])==output


def test_guard_preserves_valid_exact_rewrite_and_discards_old_topic():
    from research_context import preserve_project_selection
    output='For World Bank project P164032, who is the implementing agency?'
    messages=[{'role':'assistant','content':'Old FONGIM project ID 664.'},
              {'role':'user','content':'List the World Bank projects.'},
              {'role':'assistant','content':'World Bank P164032.'}]
    assert preserve_project_selection(output,'Which of those projects have an implementer?',messages)==output


def test_social_acknowledgement_does_not_hide_selected_ids():
    from research_context import preserve_project_selection
    messages=[{'role':'user','content':'List the FONGIM projects.'},
              {'role':'assistant','content':'FONGIM project ID 664.'},
              {'role':'user','content':'Thanks!'},
              {'role':'assistant','content':'You are welcome.'}]
    result=preserve_project_selection('List all FONGIM projects.',
        'Which of those projects have an EU donor?',messages)
    assert '664' in result


def test_eu_sentence_punctuation_does_not_become_part_of_identifier():
    from research_context import preserve_project_selection
    identifier='XI-IATI-EC_INTPA-2023-PC-34274'
    result=preserve_project_selection('List all EU projects.',
        'Which of those projects have an implementer?',
        [{'role':'assistant','content':f'EU activity {identifier}.'}])
    assert f'{identifier}:' in result and f'{identifier}.:' not in result


def test_multiple_canonical_tables_do_not_establish_one_selected_set():
    from research_context import preserve_project_selection
    table='| Source identifier | Project |\n|---|---|\n| FONGIM project ID 664 | Project |\n'
    output='Unchanged semantic question.'
    assert preserve_project_selection(output,'Which of those projects have a donor?',
        [{'role':'assistant','content':table+'\n'+table}])==output
