"""Narrow closure screening never strips evidence needed for decisions."""
import ast
from pathlib import Path
import pytest
from routing import explicit_source_plan, bounded_fts_source_names, bounded_project_learning_source_names, bounded_project_date_source_names


@pytest.mark.parametrize('q,source',[
 ('Which World Bank projects in Mali have reported closing dates in the next 12 months? Give their project IDs and reported dates.','project_learning'),
 ('Quels projets de la Banque mondiale au Mali ont des dates de clôture déclarées dans les 12 prochains mois ? Donne les identifiants et les dates.','project_learning'),
 ('Which EU projects have reported end dates in 2027?','eu'),
 ('Which EU projects are closing in the next 6 months?','eu'),
 ('Pour EU IATI, identifiants de projets XI-IATI-EC_INTPA-2023-PC-34257, quels dossiers ont une date de fin déclarée entre 2026-10-08 et 2027-10-08 ?', 'eu'),
])
def test_direct_screen_keeps_only_relevant_provider_and_geographic_metadata(q,source):
 plan=explicit_source_plan(q)
 assert plan is not None and not any(plan.values())
 assert bounded_project_date_source_names(q,plan,{'method':'explicit_source_rules'})=={source,'geographic_model'}
 assert bounded_project_date_source_names(q,plan,{'method':'model_planner'}) is None


@pytest.mark.parametrize('q',[
 'What World Bank projects are closing soon?',
 'Which World Bank projects close in the next 12 months in Mopti?',
 'Which EU projects have end dates in 2027 and how do they cover needs?',
 'Which World Bank projects close in the next 12 months and what are their continuity risks?',
 'Which World Bank projects close in the next 12 months and who implements them?',
 'Which World Bank projects close in the next 12 months in the health sector?',
 'Which World Bank projects close in the next 12 months and how much funding remains?',
 'Which World Bank projects close in the next 12 months and what are their results?',
 'Compare EU and World Bank closing dates in 2027.',
 'Which EU projects have end dates in 2027 alongside GIZ and FONGIM?',
 'Which World Bank projects close between 2026 and 2028?',
 'Compare EU IATI and other IATI projects closing in 2027.',
 'Which EU projects have end dates in 2027 and IATI results?',
 'Which EU projects have end dates in 2027 and successor programmes?',
 'Which World Bank projects have end dates in 2027 and sequencing opportunities?',
])
def test_professional_join_questions_keep_full_research(q):
 assert bounded_project_date_source_names(q,explicit_source_plan(q),{'method':'explicit_source_rules'}) is None


def test_actual_research_skips_unrelated_queries_and_preserves_loaded_study_evidence(monkeypatch):
    import re,time,unicodedata
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from metering import submit
    import geographic_model
    from project_learning_sources import retrieve_project_learning
    from eu_sources import retrieve_eu_evidence
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
    def eu(q):
        called.append('eu');return retrieve_eu_evidence(q)
    ns={'re':re,'time':time,'unicodedata':unicodedata,'defaultdict':defaultdict,
        'ThreadPoolExecutor':ThreadPoolExecutor,'submit':submit,
        'explicit_source_plan':explicit_source_plan,'bounded_fts_source_names':bounded_fts_source_names,
        'bounded_project_learning_source_names':bounded_project_learning_source_names,
        'openai_client':None,'get_document_groups':forbidden,'resolve_geography':forbidden,
        'build_hapi_evidence':forbidden,'research_fongim':forbidden,
        'retrieve_source_evidence':forbidden,'retrieve_operational_evidence':forbidden,
        'retrieve_analytical_evidence':forbidden,'retrieve_eu_evidence':eu,
        'retrieve_project_learning':learning,'enrich_join_evidence':lambda ledger:None,
        'build_join_context':lambda *args:{},'load_entity_decisions':lambda:({},[]),
        'OrganizationResolver':lambda *args:None}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'exact-learning-research','exec'),ns)
    for q in [
        'Which World Bank projects in Mali have reported closing dates in the next 12 months?',
        'Quels projets de la Banque mondiale ont une date de clôture dans les 12 prochains mois ?',
        'Which World Bank project records have reported closing dates in 2027?',
        'Pour EU IATI, identifiants de projets XI-IATI-EC_INTPA-2023-PC-34257, quels dossiers ont une date de fin déclarée entre 2026-10-08 et 2027-10-08 ?']:
        called.clear()
        result=ns['run_four_source_research'](q)
        provider='eu' if 'EU IATI' in q else 'project_learning'
        assert set(called)=={provider,'geographic_model'}
        expected=retrieve_eu_evidence(q) if provider=='eu' else retrieve_project_learning(q)
        actual=[r for r in result['ledger'] if r.get('source_family') in {e['source_family'] for e in expected}]
        assert [r['content'] for r in actual]==[r['content'] for r in expected]
        assert [r.get('project_record') for r in actual]==[r.get('project_record') for r in expected]
        from project_date_answers import answer
        text,audit=answer(q,result['ledger'])
        assert len(audit['matching_ids'])==(1 if provider=='eu' else 3)
        if provider!='eu':
            assert 'Bounded source examples' in text or 'Sélection bornée' in text
