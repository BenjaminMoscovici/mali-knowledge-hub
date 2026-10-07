"""Source-compatible arithmetic is exact, scoped, and protected from fake units."""
from copy import deepcopy
import ast,re,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from analytical_sources import retrieve_analytical_evidence
from citations import verify
from funding_answers import answer


QUESTION='Compare Mali 2026 FTS requirements, reported funding and percentage funded, with the snapshot date and units.'


def ledger(q=QUESTION):
    return [dict(e,evidence_id=f'E{i:02d}') for i,e in enumerate(retrieve_analytical_evidence(q),1)]


def test_actual_money_gap_percent_and_source_rounding_keep_distinct_stages_and_citations():
    rows=ledger();text,audit=answer(QUESTION,rows)
    assert '577,866,412' in text and '135,628,821' in text and '442,237,591' in text
    assert '| 23.47% | 23% | [E01]' in text
    assert 'outside/unspecified plan' in text and '21,002,020' in text
    assert '| not reported | not reported | not reported | [E02]' in text
    assert '2026-10-02T05:04:57.108364' in text and 'USD' in text
    assert 'contributions, commitments and carry-over' in text and 'not establish disbursement, delivery or local needs coverage' in text
    assert audit['method']=='verified_funding_arithmetic'
    assert audit['records'][0]['requirements_minus_funding']=='442,237,591'
    assert verify(text,rows)[1]['valid']


def test_multiple_years_and_missing_requirements_never_become_a_combined_total():
    q='Compare Mali FTS requirements and reported funding in 2025 and 2026.'
    rows=ledger(q);text,audit=answer(q,rows)
    assert len(audit['records'])==4 and '| 2025 / HMLI25 |' in text and '| 2026 / HMLI26 |' in text
    assert '46,785,595' in text and 'No cross-plan/year total' in text
    assert verify(text,rows)[1]['valid']


def test_french_money_comparison_is_still_cited_and_not_local_coverage():
    text,audit=answer('Comparez les montants FTS 2026 au Mali et les devises.',ledger(),language='French')
    assert '442,237,591' in text and 'déficit arithmétique' in text and 'couverture de besoins locaux' in text


@pytest.mark.parametrize('q',[
    'Compare FTS funding with needs in Mopti.', 'Which donors funded the FTS gap?',
    'How much FTS funding was actually disbursed in 2026?',
    'What explains low FTS funding in 2026?', 'Will FTS funding be sufficient in 2027?',
    'What changed between FTS funding in 2025 and 2026?', 'Convert FTS funding in 2026 to EUR.',
    'Compare World Bank and FTS financing.', 'What is the budget for the projects in Gao?',
])
def test_wider_analysis_and_unverified_stages_keep_normal_synthesis(q):
    assert answer(q,ledger()) is None


@pytest.mark.parametrize('key,value',[
    ('amount_unit','millions'),('comparable_within_record',False),('currency','unknown'),
    ('requirements','NaN'),('reported_funding',-1),('scope','Mopti'),('publisher_percent',float('inf')),
])
def test_conflicts_unverified_units_and_invalid_values_are_not_calculated(key,value):
    rows=deepcopy(ledger());rows[0]['funding_record'][key]=value
    assert answer(QUESTION,rows) is None


def test_duplicates_missing_contracts_and_unreturned_years_defer_to_synthesis():
    rows=ledger();assert answer(QUESTION,rows+[deepcopy(rows[0])]) is None
    del rows[0]['funding_record']['year'];assert answer(QUESTION,rows) is None
    assert answer('Compare FTS funding in Mali in 1999 and 2026.',ledger()) is None


def test_zero_requirements_do_not_divide_and_surplus_remains_signed_and_source_currency():
    rows=deepcopy(ledger())[:1];p=rows[0]['funding_record']
    p.update(requirements=0,reported_funding='2.50',currency='EUR',publisher_percent=None)
    text,audit=answer(QUESTION,rows)
    assert '| EUR | 0 | 2.5 | -2.5 | not reported | not reported |' in text
    assert 'negative balance means reported funding exceeds requirements' in text


def test_actual_answer_engine_uses_fresh_records_and_skips_only_qualified_financing_synthesis():
    source=Path(__file__).with_name('analysis_core.py').read_text();tree=ast.parse(source)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate_grounded_answer')
    rows=ledger();calls=[]
    def research(q,**kwargs):
        calls.append(q);return {'ledger':rows,'execution_trace':{},'research_seconds':1.2}
    ns={'time':time,'re':re,'PHASE':SimpleNamespace(set=lambda p:None),
        'get_mode':lambda d:{'document_count':1},'run_four_source_research':research}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'funding-answer-engine','exec'),ns)
    result=ns[fn.name](QUESTION)
    assert calls==[QUESTION] and result['evidence']==rows and result['synthesis_seconds']==0
    assert result['execution_trace']['verified_calculation']['method']=='verified_funding_arithmetic'
