"""Exercise actual research worker wiring without app secrets/bootstrap."""
import ast
from pathlib import Path
import re
import time
import unicodedata
import pytest


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
    def stub(geography,ending=False):
        calls.append((geography,ending));return {'evidence':[]}
    namespace={'question':question,'geography':{'region':'Mopti','cercle':None},'research_fongim':stub,
               're':re,'time':time,'unicodedata':unicodedata}
    exec(compile(ast.Module(body=[normalization,worker],type_ignores=[]),'research-worker','exec'),namespace)
    result,elapsed=namespace['timed_fongim']()
    assert result=={'evidence':[]} and elapsed>=0
    assert calls==[({'region':'Mopti','cercle':None},expected)]
