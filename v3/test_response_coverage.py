"""Coverage research preserves source boundaries and retrieves response evidence."""
import ast,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from synthesis_context import response_search_question,response_coverage_workflow


@pytest.mark.parametrize('q',[
    'What can we establish about coverage of needs across sectors?',
    'Which humanitarian needs remain uncovered by the response?',
    'Quelle couverture des besoins par la réponse humanitaire ?',
    'Quels besoins sont couverts dans ces secteurs ?',
    'What are the response gaps?',
])
def test_coverage_asks_for_measured_evidence_without_assuming_coverage(q):
    query=response_search_question(q)
    assert query.startswith(q+'\n') and 'reporting periods and footnotes' in query
    assert 'do not independently establish needs coverage' in query


@pytest.mark.parametrize('q',[
    'What is mobile network coverage in Mali?', 'Describe government priorities in Mopti.',
    'What needs are documented in Gao?', 'What insurance coverage is available?',
    'Which World Bank projects end in 2027?', 'Compare reported UNICEF results and targets.',
])
def test_other_professional_and_previously_qualified_queries_keep_original_search(q):
    assert not response_coverage_workflow(q) and response_search_question(q)==q


@pytest.mark.parametrize('targeted',[False,True])
def test_actual_document_search_keeps_filters_counts_government_query_and_original_records(targeted):
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_document_evidence')
    calls=[]
    def search(q,match_count,filter_document_ids):
        calls.append((q,match_count,filter_document_ids))
        return [{'id':filter_document_ids[0]+'-chunk','document_id':filter_document_ids[0],
                 'document_title':'Original report','page_number':8,'section_title':'Annex',
                 'content':'Annual target 100; reported 40 in January–June 2026; not coverage of needs.'}]
    documents=[{'id':'g','title':'Strategy'},{'id':'h','title':'Report'}]
    ns={'time':time,'ThreadPoolExecutor':ThreadPoolExecutor,'submit':lambda ex,fn,*args:ex.submit(fn,*args),
        'get_document_groups':lambda:{'government':['g'],'hnrp':['h'],'documents':documents},
        'named_targets':lambda *args: [('h','Report')] if targeted else [],
        'explicit_title_targets':lambda *args:[], 'search_knowledge_base':search,
        'classify_document_family':lambda item:'Humanitarian planning'}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'coverage-document-path','exec'),ns)
    result=ns[fn.name]('Compare response coverage of needs with government priorities.',hnrp_count=4)
    assert len(calls)==2
    government=next(c for c in calls if c[2]==['g']);response=next(c for c in calls if c[2]==['h'])
    assert government[1]==8 and response[1]==4
    assert 'Retrieve quantitative response evidence' not in government[0]
    assert 'Retrieve quantitative response evidence' in response[0]
    assert len(result['evidence'])==2 and all(e['page']==8 for e in result['evidence'])
    assert all(e['content']=='Annual target 100; reported 40 in January–June 2026; not coverage of needs.' for e in result['evidence'])
