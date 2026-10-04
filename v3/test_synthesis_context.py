"""Adversarial checks for source identity, exact excerpts and scope preservation."""
import ast
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time
import re
import unicodedata
from synthesis_context import prepare, serialize, extract_spans
from citations import verify
from routing import explicit_source_plan


def row(eid='E01', **extra):
    return {'evidence_id':eid,'source_type':'structured_data','source_family':'Needs',
        'document_title':'Needs release','release_id':'r1','reference_period_start':'2025-09-01',
        'reference_period_end':'2025-12-31','geographic_scope':'Mopti region, older boundaries',
        'section':'Food security','locator':'CSV row 12','content':'13,582 people in need. Not people reached. No approved commune crosswalk.',**extra}


def test_identical_duplicate_only_and_different_period_parent_release_survive():
    rows=[row(),row('E02'),row('E03',release_id='r2'),row('E04',reference_period_end='2026-08-31'),
        row('E05',geographic_scope='Mopti commune'),row('E06',locator='CSV row 13')]
    selected,audit=prepare(rows,'Food security needs in Mopti')
    assert [r['evidence_id'] for r in selected]==['E01','E03','E04','E05','E06']
    assert audit['duplicate_ids']==['E02']
    assert rows[1]['evidence_id']=='E02'


def test_numeric_structured_rows_and_semantic_caveats_not_excerpted():
    text=('13,582 people; female 7,201; male 6,381. Not a regional total, not current 2026. '*200)
    rows=[row(content=text)]
    selected,_=prepare(rows,'Mopti needs')
    assert selected[0]['content']==text
    prompt=serialize(selected)
    for value in ['13,582','7,201','6,381','2025-09-01','2025-12-31','older boundaries','CSV row 12']:
        assert value in prompt


def test_excerpts_are_exact_and_keep_negation_neighbor_and_conflict():
    text='Introductory source scope. '+('Unrelated narrative sentence. '*180)+ \
        'Food security has 42 projects. They do not establish coverage. '+('Other background sentence. '*160)+ \
        'Active status conflicts with the past end date.'
    result,spans=extract_spans(text,{'food','security'},budget=1200)
    assert 'Food security has 42 projects.' in result
    assert 'They do not establish coverage.' in result
    assert 'Active status conflicts with the past end date.' in result
    for a,b in spans:
        assert text[a:b] in result
    assert len(result)<len(text)


def test_document_selection_keeps_each_document_and_original_ids():
    rows=[row(f'E{i:02d}',source_type='knowledge_base_document',document_id='d1' if i<7 else 'd2',
              content=('Food security in Mopti. ' if i%2 else 'Unrelated health. ')*150) for i in range(1,9)]
    original=[r.copy() for r in rows]
    selected,audit=prepare(rows,'Food-security needs Mopti')
    assert {'d1','d2'}=={e['document_id'] for e in selected}
    assert len(selected)<len(rows) and rows==original
    assert not verify('Claim [E02]',[row('E01')])[1]['valid']


def test_transposed_fongim_table_selected_and_excerpts_disclose_partial_roster():
    rows=[row('E01',source_type='fongim_structured',section='Organization-sector relationships',content='Organization orientation.'),
        row('E02',source_type='fongim_structured',section='Sector-organization relationships',
            content='Counts are unique projects, not people reached. '+ '; '.join(f'Sector {i}: Actor {i} ({i} projects)' for i in range(150)))]
    selected,audit=prepare(rows,'Mopti food security actor presence')
    assert audit['omitted_ids']==['E01']
    assert len(selected[0]['content'])<len(rows[1]['content'])
    assert 'not people reached' in selected[0]['content']
    assert 'not a complete roster/table' in selected[0]['content']


def test_explicit_join_removes_only_planning_pass():
    plan=explicit_source_plan('Compare Mopti food-security needs with OCHA 3W presence and DTM stocks')
    assert plan=={'government_docs':False,'hnrp_docs':True,'hapi':True,'fongim':True}
    assert explicit_source_plan('Compare needs with World Bank projects and Mali national priorities')['government_docs']
    assert explicit_source_plan('What explains changing local conditions?') is None


def test_packaged_cache_copy_isolation_bound_and_expiry(tmp_path,monkeypatch):
    import evidence_cache
    path=tmp_path/'snapshot';path.write_text('release')
    monkeypatch.setattr(evidence_cache,'Path',lambda _:path)
    clock=[0]
    monkeypatch.setattr(evidence_cache.time,'monotonic',lambda:clock[0])
    calls=[]
    @evidence_cache.snapshot_cached('snapshot',seconds=10,maxsize=2)
    def lookup(q):
        calls.append(q);return [{'content':q}]
    a=lookup('a');a[0]['content']='mutation'
    assert lookup('a')[0]['content']=='a' and calls==['a']
    lookup('b');lookup('c');lookup('a')
    assert calls==['a','b','c','a']
    clock[0]=11;lookup('a');assert len(calls)==5
    path.write_text('new release');lookup('a');assert len(calls)==6


def test_actual_research_runs_independent_families_concurrently_and_preserves_citations(monkeypatch):
    import geographic_model
    from threading import Barrier
    from collections import defaultdict
    from metering import submit
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in
               {'run_four_source_research','normalize_text','build_unified_evidence'}]
    barrier=Barrier(6,timeout=3)
    calls=[]
    def retriever(family):
        def read(question):
            calls.append(family)
            barrier.wait()
            return [row(source_family=family,content='Scoped evidence for '+family)]
        return read
    ns={'re':re,'time':time,'unicodedata':unicodedata,'defaultdict':defaultdict,
        'ThreadPoolExecutor':ThreadPoolExecutor,'submit':submit,
        'plan_sources_semantically':lambda q:{'source_plan':{'government_docs':False,'hnrp_docs':False,'hapi':False,'fongim':False},'seconds':0},
        'enrich_join_evidence':lambda ledger:None,
        'build_join_context':lambda *args:{},'load_entity_decisions':lambda:({},[]),
        'OrganizationResolver':lambda *args:None}
    for name,family in [('retrieve_source_evidence','foundation'),('retrieve_operational_evidence','operational'),
                        ('retrieve_analytical_evidence','analytical'),('retrieve_project_learning','learning'),('retrieve_eu_evidence','eu')]:
        ns[name]=retriever(family)
    monkeypatch.setattr(geographic_model,'canonical_geography_evidence',retriever('geography'))
    exec(compile(ast.Module(body=functions,type_ignores=[]),'research-flow','exec'),ns)
    result=ns['run_four_source_research']('Compare Mopti evidence')
    assert set(calls)=={'foundation','operational','analytical','learning','eu','geography'}
    assert [r['source_family'] for r in result['ledger']]==['foundation','operational','analytical','learning','eu','geography']
    assert [r['evidence_id'] for r in result['ledger']]==[f'E{i:02d}' for i in range(1,7)]
    assert result['execution_trace']['sources']['eu']['records']==1


def test_real_packaged_mopti_context_preserves_all_required_observations():
    from operational_sources import retrieve_operational_evidence
    from analytical_sources import retrieve_analytical_evidence
    q='Compare Mopti food-security needs, OCHA 3W presence and DTM displacement stocks'
    ledger=retrieve_operational_evidence(q)+retrieve_analytical_evidence(q)
    ledger=[dict(e,evidence_id=f'E{i:02d}') for i,e in enumerate(ledger,1)]
    selected,audit=prepare(ledger,q)
    assert len(selected)==len(ledger)
    assert [e['content'] for e in selected]==[e['content'] for e in ledger]
    prompt=serialize(selected)
    for value in ['13,582','13,002','9,399','5,899','2,576','PRESENCE ONLY','STOCK (not flow)',
                  'not a region/cercle total','projected','not IPC','geography vintage']:
        assert value in prompt


def test_exhaustive_roster_request_preserves_entire_requested_table():
    content='Counts describe presence only. '+ '; '.join(f'Actor {i}: health ({i} projects)' for i in range(150))
    ledger=[row(source_type='fongim_structured',section='Organization-sector relationships',content=content)]
    selected,_=prepare(ledger,'List all organisations and their sectors in Mopti')
    assert selected[0]['content']==content
