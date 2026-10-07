"""Coverage research preserves source boundaries and retrieves response evidence."""
import ast,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from synthesis_context import response_coverage_workflow
from document_targets import response_report_targets


@pytest.mark.parametrize('q',[
    'What can we establish about coverage of needs across sectors?',
    'Which humanitarian needs remain uncovered by the response?',
    'Quelle couverture des besoins par la réponse humanitaire ?',
    'Quels besoins sont couverts dans ces secteurs ?',
    'What are the response gaps?',
])
def test_coverage_asks_for_measured_evidence_without_assuming_coverage(q):
    assert response_coverage_workflow(q)


@pytest.mark.parametrize('q',[
    'What is mobile network coverage in Mali?', 'Describe government priorities in Mopti.',
    'What needs are documented in Gao?', 'What insurance coverage is available?',
    'Which World Bank projects end in 2027?', 'Compare reported UNICEF results and targets.',
])
def test_other_professional_and_previously_qualified_queries_keep_original_search(q):
    assert not response_coverage_workflow(q)


def test_catalogue_publisher_identity_report_role_and_bounded_scope_control_lookup():
    docs=[{'id':'report','title':'Situation report','organization':'Agency Alpha'},
          {'id':'appeal','title':'Annual humanitarian appeal','organization':'Agency Alpha'},
          {'id':'other','title':'Situation report','organization':'Agency Beta'},
          {'id':'acronym','title':'Rapport de situation','organization':'Organisation Beta (OBE)'}]
    assert response_report_targets('Agency Alpha coverage of needs',docs)==[('report','Situation report')]
    assert response_report_targets('OBE couverture des besoins',docs)==[('acronym','Rapport de situation')]
    assert response_report_targets('Coverage of needs',docs)==[]
    assert response_report_targets('Agency Alphabet coverage of needs',docs)==[]
    assert response_report_targets('Agency Alpha strategy priorities',docs)==[]
    many=[dict(docs[0],id=str(i)) for i in range(4)]
    assert response_report_targets('Agency Alpha coverage of needs',many)==[]


@pytest.mark.parametrize('targeted',[False,True])
@pytest.mark.parametrize('annex_failure',[False,True])
def test_actual_document_search_keeps_filters_counts_government_query_and_original_records(targeted,annex_failure):
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_document_evidence')
    calls=[]
    def search(q,match_count,filter_document_ids):
        calls.append((q,match_count,filter_document_ids))
        if '\nAnnex:' in q:
            if annex_failure:raise RuntimeError('Supplementary provider lookup unavailable')
            return [{'id':'annex','document_id':filter_document_ids[0],
                     'document_title':'Activity report','page_number':9,'section_title':'Annex',
                     'content':'Verified original table with annual targets and period values.'}]
        return [{'id':filter_document_ids[0]+'-chunk','document_id':filter_document_ids[0],
                 'document_title':'Original report','page_number':8,'section_title':'Annex',
                 'content':'Annual target 100; reported 40 in January–June 2026; not coverage of needs.'}]
    documents=[{'id':'g','title':'Government annual report','organization':'Agency Alpha'},
               {'id':'h','title':'Activity report','organization':'Agency Alpha'}]
    ns={'time':time,'ThreadPoolExecutor':ThreadPoolExecutor,'submit':lambda ex,fn,*args:ex.submit(fn,*args),
        'get_document_groups':lambda:{'government':['g'],'hnrp':['h'],'documents':documents},
        'named_targets':lambda *args: [('h','Activity report')] if targeted else [],
        'explicit_title_targets':lambda *args:[], 'search_knowledge_base':search,
        'classify_document_family':lambda item:'Humanitarian planning'}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'coverage-document-path','exec'),ns)
    result=ns[fn.name]('For Agency Alpha, compare response coverage of needs with government priorities.',hnrp_count=4)
    assert len(calls)==3
    government=next(c for c in calls if c[2]==['g']);response=next(c for c in calls if c[2]==['h'] and '\nAnnex:' not in c[0])
    assert government[1]==8 and response[1]==4
    annex=next(c for c in calls if '\nAnnex:' in c[0]);assert annex[1:]==(3,['h'])
    assert 'reporting period, population definitions and footnotes' in annex[0]
    assert result['trace']['hnrp_docs']['annex_lookup']=={'reports':1,'failed':int(annex_failure)}
    assert len(result['evidence'])==(2 if annex_failure else 3)
    if not annex_failure:
        assert {e['page'] for e in result['evidence']}=={8,9}
        assert result['evidence'][-1]['content']=='Verified original table with annual targets and period values.'
    assert all(e['content']=='Annual target 100; reported 40 in January–June 2026; not coverage of needs.' for e in result['evidence'][:2])
