import ast
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from project_dates import select_examples
from project_references import fongim_project_ids
from project_references import fongim_roster_ids


def test_roster_labels_support_fresh_lookup_without_turning_years_and_counts_into_ids():
    assert fongim_roster_ids('FONGIM four projects: **Project 32:** dates; **Project 664:** dates.')==(32,664)
    assert fongim_roster_ids('FONGIM has 664 projects in 2026. Funding requirements are 32 million.')==()


@pytest.mark.parametrize('question,expected', [
    ('Which FONGIM records — Project ID 664, Project ID 434, Project ID 696 and Project ID 32 — end in 2026?', (32,434,664,696)),
    ('Compare FONGIM project IDs: 664, 434, 696 and 32.', (32,434,664,696)),
    ('Dates des projets FONGIM, identifiants des projets 32 et 696.', (32,696)),
    ('FONGIM ID 664', (664,)),
    ('FONGIM project ID 664. In 2026?', (664,)),
    ('Compare World Bank project ID 664 with P144442', ()),
    ('FONGIM had 664 projects in 2026', ()),
    ('FONGIM project ID 664-A', ()),
])
def test_only_complete_source_qualified_ids(question, expected):
    assert fongim_project_ids(question) == expected


def researcher(locations, projects):
    tree = ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'research_fongim')
    fn.decorator_list = []
    calls = []
    def rows(table, columns, ids):
        calls.append((table, list(ids)))
        return [p for p in projects if p['fongim_project_id'] in ids] if table == 'fongim_projects' else []
    ns = {'fetch_all_rows':lambda *a, **kw:locations, 'get_rows_for_project_ids':rows,
          'ThreadPoolExecutor':ThreadPoolExecutor, 'submit':lambda pool, fn, *args:pool.submit(fn,*args),
          'defaultdict':defaultdict, 'select_examples':select_examples, 'json':json}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<real_fongim_research>', 'exec'), ns)
    return ns['research_fongim'], calls


def test_requested_set_freshly_returns_all_records_even_closed_or_later_ending():
    # More records than the former five-example limit; the explicit set is
    # selected independently of alphabetical or rolling-window examples.
    projects = [{'fongim_project_id':i, 'project_name':f'Project {i}',
                 'status':'Clôturé' if i == 32 else 'En cours',
                 'start_date':'2021-01-01', 'end_date':'2027-01-01' if i == 32 else '2026-12-31'}
                for i in [32,434,664,696,701,702,999]]
    locations = [{'fongim_project_id':p['fongim_project_id'], 'region':'Mopti', 'cercle':'Mopti'} for p in projects]
    research, calls = researcher(locations, projects)
    result = research({'region':'Mopti'}, ending=True, requested_project_ids=(32,434,664,696,701,702))
    records = [e for e in result['evidence'] if e.get('section') == 'Project-ID relationship']
    assert len(records) == 6 and result['project_count'] == 6
    assert all(999 not in ids for _,ids in calls)
    assert any('FONGIM project ID 32:' in e['content'] and '2027-01-01' in e['content'] for e in records)
    assert any('FONGIM project ID 696:' in e['content'] for e in records)
    assert all('Reported dates do not prove actual completion' in e['content'] for e in records)


def test_unknown_or_out_of_geography_identifier_is_not_replaced_by_examples():
    research, calls = researcher([{'fongim_project_id':664,'region':'Mopti'}], [])
    result = research({'region':'Mopti'}, requested_project_ids=(999,))
    assert result['project_count'] == 0 and calls == []
    assert len(result['evidence']) == 1
    assert 'IDs not returned within this source/geography selection: [999]' in result['evidence'][0]['content']
    assert 'does not establish that a project does not exist' in result['evidence'][0]['content']
