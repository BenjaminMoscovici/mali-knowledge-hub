"""Exact study lookup preserves provenance and does not narrow decision joins."""
import ast
from pathlib import Path
import pytest
from routing import explicit_source_plan, bounded_fts_source_names, bounded_project_learning_source_names


@pytest.mark.parametrize('q', [
    'For World Bank P513735, what evaluation findings are available for that exact project? Distinguish the project profile from an evaluation and keep findings about other projects separate.',
    'What lessons are recorded for P144442, with methodology and source dates?',
    'Compare evaluation findings for World Bank P144442 and P513735.',
    'Quels enseignements des évaluations pour le projet P144442 de la Banque mondiale ?',
])
def test_exact_study_lookup_selects_project_identity_and_scope(q):
    plan=explicit_source_plan(q)
    assert plan is not None and not any(plan.values())
    assert bounded_project_learning_source_names(q,plan,{'method':'explicit_source_rules'})=={'project_learning','geographic_model'}
    assert bounded_project_learning_source_names(q,plan,{'method':'model_planner'}) is None


@pytest.mark.parametrize('q', [
    'What evaluation lessons are available for Mali?',
    'How does P144442 evaluation relate to needs in Mopti?',
    'Apply lessons from P144442 to a new programme in Gao.',
    'Which current projects could use P144442 evaluation lessons?',
    'Compare evaluation P144442 with EU funding and FONGIM projects.',
    'What do evaluations say about P144442 delivery and reach?',
    'What did P144442 achieve compared with national priorities?',
    'Which donors funded the evaluation of P144442?',
    'Compare P144442 evaluation findings with UNICEF studies.',
    'What lessons does P144442 have for food-security needs in Konna?',
    'What evaluation lessons are available for projects P144442, P513735 and P164032?',
    'Compare P144442 evaluation with other sources.',
    'What lessons for P144442 and AFD?',
    'What funding is reported for P513735?',
])
def test_professional_decisions_and_other_sources_keep_wide_research(q):
    assert bounded_project_learning_source_names(q,explicit_source_plan(q),{'method':'explicit_source_rules'}) is None


def test_actual_research_skips_unrelated_queries_and_preserves_loaded_study_evidence(monkeypatch):
    import re,time,unicodedata
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from metering import submit
    import geographic_model
    from project_learning_sources import retrieve_project_learning
    source=Path(__file__).with_name('analysis_core.py').read_text();tree=ast.parse(source)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
               {'run_four_source_research','normalize_text','build_unified_evidence','plan_sources_semantically'}]
    called=[]
    def forbidden(*args,**kwargs):
        raise AssertionError('Unrelated query or model planner')
    original_geo=geographic_model.canonical_geography_evidence
    def geography(q):
        called.append('geographic_model');return original_geo(q)
    def learning(q):
        called.append('project_learning');return retrieve_project_learning(q)
    monkeypatch.setattr(geographic_model,'canonical_geography_evidence',geography)
    ns={'re':re,'time':time,'unicodedata':unicodedata,'defaultdict':defaultdict,
        'ThreadPoolExecutor':ThreadPoolExecutor,'submit':submit,
        'explicit_source_plan':explicit_source_plan,'bounded_fts_source_names':bounded_fts_source_names,
        'bounded_project_learning_source_names':bounded_project_learning_source_names,
        'openai_client':None,'get_document_groups':forbidden,'resolve_geography':forbidden,
        'build_hapi_evidence':forbidden,'research_fongim':forbidden,
        'retrieve_source_evidence':forbidden,'retrieve_operational_evidence':forbidden,
        'retrieve_analytical_evidence':forbidden,'retrieve_eu_evidence':forbidden,
        'retrieve_project_learning':learning,'enrich_join_evidence':lambda ledger:None,
        'build_join_context':lambda *args:{},'load_entity_decisions':lambda:({},[]),
        'OrganizationResolver':lambda *args:None}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'exact-learning-research','exec'),ns)
    for project_id in ['P144442','P513735','P999999']:
        called.clear();q=f'What evaluation findings are available for exact World Bank {project_id}?'
        result=ns['run_four_source_research'](q)
        assert set(called)=={'project_learning','geographic_model'}
        expected=retrieve_project_learning(q)
        families={r['source_family'] for r in expected}
        actual=[r for r in result['ledger'] if r['source_family'] in families]
        assert [r['content'] for r in actual]==[r['content'] for r in expected]
        assert [r.get('locator') for r in actual]==[r.get('locator') for r in expected]
        if project_id=='P144442':
            assert len([r for r in actual if r['source_type']=='evaluation_finding'])==3
        else:
            assert not any(r['source_type']=='evaluation_finding' for r in actual)
            assert any(r['source_family']=='Evaluation lookup scope' for r in actual)
