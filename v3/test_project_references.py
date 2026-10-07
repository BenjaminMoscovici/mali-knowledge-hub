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
    def locations_read(table, **kwargs):
        calls.append((table, kwargs.get('in_filters')))
        return locations
    ns = {'fetch_all_rows':locations_read, 'get_rows_for_project_ids':rows,
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
    assert calls[0] == ('fongim_project_locations', {'fongim_project_id':[32,434,664,696,701,702]})
    assert all(999 not in ids for _,ids in calls[1:])
    assert any('FONGIM project ID 32:' in e['content'] and '2027-01-01' in e['content'] for e in records)
    assert any('FONGIM project ID 696:' in e['content'] for e in records)
    assert all('Reported dates do not prove actual completion' in e['content'] for e in records)


def test_unknown_or_out_of_geography_identifier_is_not_replaced_by_examples():
    research, calls = researcher([{'fongim_project_id':664,'region':'Mopti'}], [])
    result = research({'region':'Mopti'}, requested_project_ids=(999,))
    assert result['project_count'] == 0 and calls == [('fongim_project_locations', {'fongim_project_id':[999]})]
    assert len(result['evidence']) == 1
    assert 'IDs not returned within this source/geography selection: [999]' in result['evidence'][0]['content']
    assert 'does not establish that a project does not exist' in result['evidence'][0]['content']


def test_unscoped_location_research_remains_unfiltered():
    research, calls=researcher([], [])
    result=research({'region':'Mopti'})
    assert result['evidence']==[] and calls==[('fongim_project_locations', None)]


def test_paginated_identifier_filter_retains_all_matching_locations_and_geography():
    from types import SimpleNamespace
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='fetch_all_rows')
    data=[{'fongim_project_id':i,'region':region,'is_present_in_source':present}
          for i,region,present in [(664,'Mopti',True)]*5+[(32,'Gao',True),(664,'Mopti',False),(999,'Mopti',True)]*300]
    reads=[]
    class Query:
        def __init__(self): self.equal={};self.member={}
        def select(self,columns):return self
        def eq(self,key,value):self.equal[key]=value;return self
        def in_(self,key,values):self.member[key]=values;return self
        def range(self,start,end):self.start=start;self.end=end;return self
        def execute(self):
            selected=[r for r in data if all(r[k]==v for k,v in self.equal.items())
                      and all(r[k] in v for k,v in self.member.items())]
            reads.append((dict(self.equal),dict(self.member),self.start,self.end))
            return SimpleNamespace(data=selected[self.start:self.end+1])
    ns={'supabase':SimpleNamespace(table=lambda _:Query()),'execute_read':lambda q,_:q.execute()}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<real_pagination>','exec'),ns)
    filters={'region':'Mopti','is_present_in_source':True}
    result=ns['fetch_all_rows']('fongim_project_locations',eq_filters=filters,
                              in_filters={'fongim_project_id':[664,32]},page_size=2)
    assert len(result)==5 and len(reads)==3
    assert all(equal==filters and member=={'fongim_project_id':[664,32]} for equal,member,_,_ in reads)
    assert ns['fetch_all_rows']('table',in_filters={'fongim_project_id':[]})==[] and len(reads)==3
    # Callers that request the complete geography keep ordinary pagination.
    assert len(ns['fetch_all_rows']('table',eq_filters=filters,page_size=1000))==305
