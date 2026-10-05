"""Exercise actual research worker wiring without app secrets/bootstrap."""
import ast
from pathlib import Path
import re
import time
import unicodedata
import pytest
from conversation_state import referenced_fongim_ids


@pytest.mark.parametrize('question,expected',[
    ('Which FONGIM projects are ending in Mopti?',True),
    ('Quels projets arrivent à échéance dans Mopti ?',True),
    ('Which organizations are present in Mopti?',False)])
def test_fongim_research_worker_uses_defined_normalization_and_requested_scope(question,expected):
    module=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    research=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='run_four_source_research')
    worker=next(n for n in research.body if isinstance(n,ast.FunctionDef) and n.name=='timed_fongim')
    normalization=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='normalize_text')
    calls=[]
    def stub(geography,ending=False,referenced_ids=()):
        assert referenced_ids==()
        calls.append((geography,ending));return {'evidence':[]}
    namespace={'question':question,'geography':{'region':'Mopti','cercle':None},'research_fongim':stub,
               're':re,'time':time,'unicodedata':unicodedata,'referenced_fongim_ids':referenced_fongim_ids}
    exec(compile(ast.Module(body=[normalization,worker],type_ignores=[]),'research-worker','exec'),namespace)
    result,elapsed=namespace['timed_fongim']()
    assert result=={'evidence':[]} and elapsed>=0
    assert calls==[({'region':'Mopti','cercle':None},expected)]


def test_prior_subset_retrieves_closed_and_active_current_records_without_expansion():
    import json
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from project_dates import select_examples
    module=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='research_fongim')
    function.decorator_list=[]
    rows=[{'fongim_project_id':i,'project_name':f'Project {i}',
           'status':'Closed' if i==461 else 'En cours','end_date':'2026-12-31'} for i in [461,715,888]]
    calls=[]
    def get_rows(table,columns,ids):
        calls.append((table,ids))
        return [row for row in rows if row['fongim_project_id'] in ids] if table=='fongim_projects' else []
    namespace={'json':json,'defaultdict':defaultdict,'select_examples':select_examples,
        'ThreadPoolExecutor':ThreadPoolExecutor,'submit':lambda pool,fn,*a:pool.submit(fn,*a),
        'get_rows_for_project_ids':get_rows,'fetch_all_rows':lambda *a,**k:[
            {'fongim_project_id':i,'region':'Mopti','cercle':'Mopti','commune_raw':'Mopti'} for i in [461,715,888]]}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'bounded-project-retrieval','exec'),namespace)
    result=namespace['research_fongim']({'region':'Mopti'},ending=True,referenced_ids=(461,715,999))
    assert result['project_count']==2 and result['location_count']==2
    assert all(ids==[461,715] for _,ids in calls)
    relationships=[e['content'] for e in result['evidence'] if e.get('section')=='Project-ID relationship']
    assert len(relationships)==2 and any('Status: Closed' in text for text in relationships)
    assert not any('project ID 888' in text for text in relationships)
    selection=json.loads(next(e['content'] for e in result['evidence'] if e.get('section')=='Bounded identifier lookup'))
    assert selection['unmatched_project_ids']==[999]
    empty=namespace['research_fongim']({'region':'Mopti'},referenced_ids=(999,))
    assert empty['project_count']==0 and 'does not establish inactivity' in empty['evidence'][0]['content']
