"""FTS shortcuts never apply to allocation, operational or cross-source joins."""
import ast
from pathlib import Path
import pytest
from routing import explicit_source_plan, bounded_fts_source_names, bounded_project_learning_source_names


@pytest.mark.parametrize('q', [
    'Compare Mali 2026 FTS requirements, reported funding and percentage funded, with the snapshot date and units.',
    'What FTS funding is reported for Mali in 2026?',
    'Comparez les montants FTS 2026 au Mali et les devises.',
    'Compare FTS requirements and funding in Mali for 2025 and 2026.',
])
def test_bounded_fields_skip_planner_and_keep_financial_and_geographic_evidence(q):
    plan = explicit_source_plan(q)
    assert plan is not None and not any(plan.values())
    assert bounded_fts_source_names(q, plan, {'method':'explicit_source_rules'}) == {'analytical','geographic_model'}
    assert bounded_fts_source_names(q, plan, {'method':'model_planner'}) is None


@pytest.mark.parametrize('q', [
    'Compare FTS funding with HNRP needs in Mopti.',
    'Does FTS funding cover needs?', 'Which donors provide FTS funding?',
    'How much FTS funding reaches Gao?', 'What FTS funding is allocated to Mopti?',
    'What FTS funding is allocated to Konna?', 'FTS funding for women?',
    'Compare FTS funding and FONGIM projects.', 'Why is FTS funding low?',
    'Compare national FTS requirements and EU funding.',
    'Does FTS funding prove delivery?', 'FTS funding by sector?',
    'Compare FTS and DTM in Mopti.', 'FTS funding in Kayes region?',
    'What do IATI transactions show alongside FTS funding?',
])
def test_wider_questions_keep_existing_retrievals(q):
    assert bounded_fts_source_names(q, explicit_source_plan(q), {'method':'explicit_source_rules'}) is None


def test_packaged_retrieval_is_filtered_only_after_explicit_bounded_decision():
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    research=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_four_source_research')
    code=ast.get_source_segment(Path(__file__).with_name('analysis_core.py').read_text(),research)
    assert 'bounded_fts_source_names(question, source_plan, planner_result.get("planner_output"))' in code
    assert code.index('if bounded is not None:') < code.index('for family, retriever in packaged_retrievers.items():')


def test_exact_financial_rows_currency_date_and_scope_are_preserved():
    from analytical_sources import retrieve_analytical_evidence
    q='Compare Mali 2026 FTS requirements, reported funding and percentage funded, with the snapshot date and units.'
    rows=retrieve_analytical_evidence(q)
    funding=[r for r in rows if r['source_type']=='funding_aggregate']
    assert funding
    text=' '.join(r['content'] for r in funding)
    for marker in ['577866412', '135628821', 'USD', '2026-10-02', 'national', 'No actor/project/sector/subnational breakdown']:
        assert marker in text


def test_actual_bounded_research_runs_only_two_families_without_planner_or_live_sources(monkeypatch):
    import re,time,unicodedata
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from metering import submit
    import geographic_model
    from analytical_sources import retrieve_analytical_evidence
    source=Path(__file__).with_name('analysis_core.py').read_text();tree=ast.parse(source)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
        {'run_four_source_research','normalize_text','build_unified_evidence','plan_sources_semantically'}]
    called=[]
    def forbidden(*args,**kwargs):
        raise AssertionError('Unrelated retrieval or model planner')
    def geography(q):
        called.append('geographic_model')
        return original_geo(q)
    def financial(q):
        called.append('analytical')
        return retrieve_analytical_evidence(q)
    original_geo=geographic_model.canonical_geography_evidence
    monkeypatch.setattr(geographic_model,'canonical_geography_evidence',geography)
    ns={'re':re,'time':time,'unicodedata':unicodedata,'defaultdict':defaultdict,
        'ThreadPoolExecutor':ThreadPoolExecutor,'submit':submit,
        'explicit_source_plan':explicit_source_plan,'bounded_fts_source_names':bounded_fts_source_names,
        'bounded_project_learning_source_names':bounded_project_learning_source_names,
        'openai_client':None,'get_document_groups':forbidden,'resolve_geography':forbidden,
        'build_hapi_evidence':forbidden,'research_fongim':forbidden,
        'retrieve_source_evidence':forbidden,'retrieve_operational_evidence':forbidden,
        'retrieve_project_learning':forbidden,'retrieve_eu_evidence':forbidden,
        'retrieve_analytical_evidence':financial,'enrich_join_evidence':lambda ledger:None,
        'build_join_context':lambda *args:{},'load_entity_decisions':lambda:({},[]),
        'OrganizationResolver':lambda *args:None}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'bounded-research','exec'),ns)
    q='Compare Mali 2026 FTS requirements, reported funding and percentage funded, with the snapshot date and units.'
    result=ns['run_four_source_research'](q)
    assert set(called)=={'analytical','geographic_model'}
    expected=[r['content'] for r in retrieve_analytical_evidence(q)]
    assert [r['content'] for r in result['ledger'] if r['source_type']=='funding_aggregate']==expected
    assert result['execution_trace']['routing']['planner_output']['method']=='explicit_source_rules'
