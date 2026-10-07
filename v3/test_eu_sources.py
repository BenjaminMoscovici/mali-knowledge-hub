import ast
import pytest
from collections import Counter
from pathlib import Path
from eu_sources import package,retrieve_eu_evidence
from operational_sources import retrieve_operational_evidence
from analytical_sources import retrieve_analytical_evidence


@pytest.mark.parametrize('name', [
    'European Commission', 'Commission européenne', 'Europäische Union',
    'Europäische Kommission', 'NDICI', 'Global Gateway', 'EUTF',
    'Fonds européen de développement', 'DUE', 'T05-EUTF',
])
def test_institutional_names_and_instruments_reach_existing_eu_evidence(name):
    rows = retrieve_eu_evidence(f'What can be established about {name} in Mali?')
    assert any(r['source_type'] == 'eu_programming' and
               '151000000' in r['content'] for r in rows)
    assert all(r['locator'] and r['release_id'] and r['record_id'] for r in rows)
    assert all('financial_raw' not in r['content'] for r in rows)


@pytest.mark.parametrize('question', [
    'What is due in Mopti?', 'Which fees are due in Mali?',
    'European weather forecasts', 'What colour is the logo?',
])
def test_ambiguous_english_due_and_unrelated_europe_do_not_select_eu(question):
    assert retrieve_eu_evidence(question) == []


def test_identifier_country_deduplication_and_raw_money_exclusion():
    rows=[r for r in package()['records'] if r['source_type']=='eu_activity']
    assert len(rows)==306
    assert Counter(r['payload']['facts']['publisher_ref'] for r in rows)=={'XI-IATI-EC_INTPA':134,'XI-IATI-EC_ECHO':172}
    assert len({r['payload']['facts']['activity_id'] for r in rows})==306
    assert all(r['payload']['facts']['country_percent_reported']==100 for r in rows)
    for r in retrieve_eu_evidence('Compare EU INTPA and ECHO funding in Mopti'):
        assert 'financial_raw' not in r['content']
        assert r['valid_from'] is None and r['valid_until'] is None
        assert r['retrieved_at'] and r['locator'] and r['release_id'] and r['source_endpoint']


def test_money_stages_country_scope_and_page_citations():
    rows=retrieve_eu_evidence('What are current EU Team Europe priorities and ECHO funding?')
    original=next(r for r in rows if r['page']==94)
    current=next(r for r in rows if '151000000' in r['content'])
    echo=next(r for r in rows if r['source_type']=='echo_programming' and r['page']==5)
    assert '373' in original['content'] and 'indicative_programming' in original['content']
    assert 'provider_reported_commitment' in current['content']
    assert '32000000' in echo['content'] and 'indicative_country_allocation' in echo['content']
    assert '276000000' in echo['content'] and 'not Mali' in echo['content']
    assert echo['publication_date']=='2026-09-16'
    assert any('design/proposal as of January 2022' in r['content'] for r in rows)


def test_ending_source_status_never_promoted_to_verified_delivery():
    rows=retrieve_eu_evidence('Which EU ECHO interventions are ending in Mopti?')
    acts=[r for r in rows if r['source_type']=='eu_activity']
    assert acts
    assert all('planned/actual' in r['content'] and 'Self-reported' in r['content'] for r in acts)
    assert all('Names in titles are geographical mentions only' in r['content'] for r in acts)
    assert retrieve_eu_evidence('What colour is the logo?')==[]


def test_real_cross_source_retrieval_keeps_mopti_precision_and_periods():
    q='In Mopti, how do EU ECHO food-security priorities align with documented needs, displaced populations and operational actors?'
    rows=retrieve_eu_evidence(q)+retrieve_operational_evidence(q)+retrieve_analytical_evidence(q)
    assert {'echo_programming','eu_activity','operational_presence','displacement_stock','food_security_classification'}<=set(r['source_type'] for r in rows)
    assert any('PRESENCE ONLY' in r['content'] for r in rows)
    assert any('STOCK (not flow)' in r['content'] for r in rows)
    assert any('projected' in r['content'] for r in rows)
    assert all(r['locator'] and r['source_endpoint'] for r in rows)
    eu=[r for r in rows if r['source_type'].startswith('eu_') or r['source_type']=='echo_programming']
    assert all('no approved commune/cercle coverage' in r['geographic_precision'] for r in eu)


def test_eu_retrieval_is_wired_into_real_research_and_publisher():
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_four_source_research')
    assert any(isinstance(n,ast.Name) and n.id=='retrieve_eu_evidence' for n in ast.walk(function))
    # Runtime invocation and concurrent source isolation are exercised in test_synthesis_context.
    assert 'asyncio.to_thread(publish_eu_logged)' in Path(__file__).with_name('web_api.py').read_text()


def test_historical_health_activity_and_source_sector_remain_explicit():
    rows=retrieve_eu_evidence('In Mopti compare EU ECHO food security health nutrition activities and national priorities')
    old=next(r for r in rows if '2017/91029' in r['content'])
    assert '2018-04-30' in old['content'] and 'Historical reported end date' in old['content']
    assert 'mention its dates and status explicitly' in old['content']
    wash=next(r for r in rows if '2023-PC-34274' in r['content'])
    assert 'Democratic participation and civil society' in wash['content']
    assert 'does not change a reported governance sector code' in wash['content']
