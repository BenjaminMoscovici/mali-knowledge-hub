import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import re
import time
import pytest
from citations import verify
from project_date_answers import answer
from eu_sources import retrieve_eu_evidence
from project_learning_sources import retrieve_project_learning


def record(pid,end,eid,status='En cours'):
    return {'evidence_id':eid,'content':f'Fresh source {pid} reported end {end}, status {status}. Not actual completion.',
            'project_record':{'source_namespace':'FONGIM','source_id':str(pid),'end_date':end,
                              'status':status,'source_updated_at':'2026-08-28T15:57:41Z'}}


def test_known_roster_counts_three_of_four_from_fresh_dates_and_cites_every_row():
    rows=[record(32,'2027-01-01','E01'),record(434,'2026-12-31','E02'),
          record(664,'2026-11-30','E03'),record(696,'2026-12-31','E04')]
    text,audit=answer('For FONGIM project IDs 664, 434, 696 and 32, which records have a reported end date in 2026?',rows,asof=date(2026,10,7))
    assert '**3 of 4 requested records**' in text
    assert audit['matching_ids']==['664','434','696']
    assert '32 — 2027-01-01 [E01]' in text
    assert 'Source update/sync: 2026-08-28' in text
    from followup_context import resolve_slots
    next_turn=resolve_slots('Which of those projects have a reported end date in 2027?', [{'role':'assistant','content':text}])
    assert next_turn['state']['lookup_ids']==[434,664,696]
    assert 'do not establish actual completion' in text
    assert verify(text,rows)[1]['valid']


def test_missing_and_invalid_dates_are_unknown_not_zero_or_completed():
    rows=[record(664,None,'E01'),{'evidence_id':'E02','section':'Exact requested identifiers','content':'Requested ID 696 not returned in this selection.'}]
    text,audit=answer('For FONGIM project IDs 664 and 696, which records have a reported end date in 2026?',rows)
    assert 'not reported [E01]' in text
    assert 'Identifiers not returned in this selection: 696. [E02]' in text
    assert audit['missing_ids']==['696'] and not audit['matching_ids']
    assert 'Selected source identifiers for this filter: none.' in text
    assert verify(text,rows)[1]['valid']


def test_real_eu_snapshot_computes_three_past_active_conflicts_with_direct_citations():
    rows=retrieve_eu_evidence('Which EU activity records mention Mopti and have reported end dates in 2026?')
    rows=[dict(row,evidence_id=f'E{i:02d}') for i,row in enumerate(rows,1)]
    text,audit=answer('Which EU activity records mention Mopti and have reported end dates in 2026?',rows,asof=date(2026,10,7))
    assert '**4 of 4 returned examples**' in text
    assert '3 record(s) combine an active status with a past reported end date' in text
    assert len(audit['matching_ids'])==4 and verify(text,rows)[1]['valid']


def test_real_world_bank_snapshot_selects_three_2027_profiles_without_new_money_claims():
    q='Which World Bank project records have reported closing dates in 2027?'
    rows=[dict(row,evidence_id=f'E{i:02d}') for i,row in enumerate(retrieve_project_learning(q),1)]
    text,audit=answer(q,rows,asof=date(2026,10,7))
    assert '**3 of 3 returned examples**' in text
    assert len(audit['matching_ids'])==3
    assert 'Bounded source examples, not a complete portfolio.' in text
    assert 'USD' not in text and verify(text,rows)[1]['valid']


@pytest.mark.parametrize('question',[
    'Compare FONGIM project IDs 664 and 32 with needs and priorities in 2026.',
    'For FONGIM project ID 664, does the reported end date in 2026 establish delivery?',
    'What funding gap remains against needs in 2026?',
    'Which EU projects have reported end dates in 2026 and who is their donor?',
    'For FONGIM projects and World Bank projects, which have reported end dates in 2026?',
    'For FONGIM project ID 664, which records have reported end dates in 2026 or 2027?',
])
def test_broader_professional_analysis_keeps_existing_synthesis(question):
    assert answer(question,[record(664,'2026-11-30','E01')]) is None


def test_actual_answer_engine_retrieves_fresh_records_and_skips_only_date_synthesis():
    tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_generate_grounded_answer')
    calls=[]
    ledger=[record(664,'2026-11-30','E01')]
    def research(q,**kw):
        calls.append(q)
        return {'ledger':ledger,'execution_trace':{},'research_seconds':1.2}
    ns={'time':time,'re':re,'PHASE':SimpleNamespace(set=lambda p:None),
        'get_mode':lambda d:{'document_count':1},'run_four_source_research':research}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'real-answer-engine','exec'),ns)
    result=ns[fn.name]('For FONGIM project ID 664, which records have a reported end date in 2026?')
    assert len(calls)==1 and result['evidence']==ledger
    assert result['synthesis_seconds']==0 and '**1 of 1 requested records**' in result['answer']
    assert result['execution_trace']['verified_calculation']['method']=='verified_project_date_filter'


def test_rolling_window_uses_fresh_dates_and_query_date_not_sync_or_old_answer():
    rows=[record(32,'2027-01-01','E01'),record(434,'2026-12-31','E02'),
          record(664,'2026-11-30','E03'),record(696,'2026-12-31','E04'),
          record(9,None,'E05'),record(10,'2026-10-07','E06')]
    q='For FONGIM project IDs 664, 434, 696, 32, 9 and 10, which have reported end dates in the next 3 months?'
    text,audit=answer(q,rows,asof=date(2026,10,8))
    assert '**4 of 6 requested records**' in text
    assert 'from 2026-10-08 through 2027-01-08 (inclusive)' in text
    assert audit['matching_ids']==['664','434','696','32']
    assert audit['window_end']=='2027-01-08' and audit['query_date']=='2026-10-08'
    assert 'independently of source publication or sync dates' in text
    assert '9 — not reported [E05]' in text
    assert '10 — 2026-10-07 [E06]' in text and verify(text,rows)[1]['valid']


def test_french_cloture_is_a_supported_window_and_cites_original_profiles():
    q='Quels projets de la Banque mondiale au Mali ont des dates de clôture déclarées dans les 12 prochains mois ? Donne les identifiants et les dates.'
    rows=[dict(row,evidence_id=f'E{i:02d}') for i,row in enumerate(retrieve_project_learning(q),1)]
    text,audit=answer(q,rows,'French',asof=date(2026,10,8))
    assert '**3 sur 3 exemples retournés**' in text
    assert 'entre le 2026-10-08 et le 2027-10-08 (bornes incluses)' in text
    assert set(audit['matching_ids'])=={'P513735','P164032','P166796'}
    assert 'distincte de la date de publication' in text
    assert verify(text,rows)[1]['valid']


def test_explicit_same_year_date_interval_is_not_expanded_to_calendar_year():
    q='For FONGIM project IDs 664 and 434, which have reported end dates between 2026-11-01 and 2026-12-01?'
    text,audit=answer(q,[record(664,'2026-11-30','E01'),record(434,'2026-12-31','E02')])
    assert '**1 of 2 requested records**' in text and audit['matching_ids']==['664']
    assert audit['window_start']=='2026-11-01' and audit['window_end']=='2026-12-01'


@pytest.mark.parametrize('q',[
    'Which World Bank projects close in the next 12 months and what are their handover risks?',
    'Which World Bank projects close in the next 12 months in Mopti?',
    'Which World Bank projects close in the next 12 months and who implements them?',
    'Which World Bank projects close in the next 12 months and what sectors do they cover?',
    'Which World Bank and EU projects close in the next 12 months?',
    'What funding is available for World Bank projects closing in the next 12 months?',
])
def test_window_shortcut_preserves_professional_analysis_and_geographic_limits(q):
    assert answer(q,[dict(record(664,'2026-11-30','E01'),project_record={
        'source_namespace':'World Bank','source_id':'P513735','end_date':'2027-05-01'})]) is None


@pytest.mark.parametrize('namespace,ids,question', [
    ('FONGIM',['32','664','696'],'For FONGIM project IDs 32, 664 and 696, which active records have reported end dates in the next 12 months?'),
    ('World Bank',['P513735','P164032','P166796'],'For World Bank project IDs P513735, P164032 and P166796, which active records have reported closing dates in 2027?'),
    ('EU IATI',['XI-IATI-EC_INTPA-2023-PC-34257','XI-IATI-EC_ECHO-ECHO/-AF/BUD/2026/91003','XI-IATI-EC_ECHO-ECHO/-AF/BUD/2026/91032'],
     'Pour EU IATI, identifiants de projets XI-IATI-EC_INTPA-2023-PC-34257, XI-IATI-EC_ECHO-ECHO/-AF/BUD/2026/91003 et XI-IATI-EC_ECHO-ECHO/-AF/BUD/2026/91032, quels projets en cours ont une date de fin déclarée entre 2026-10-08 et 2027-10-08 ?'),
])
def test_active_only_exact_ids_use_fresh_status_and_do_not_treat_unknown_as_active(namespace,ids,question):
    rows=[dict(record(pid,'2027-05-01',f'E{i:02d}',status),project_record={
        'source_namespace':namespace,'source_id':pid,'end_date':'2027-05-01','status':status})
        for i,(pid,status) in enumerate(zip(ids,['Implementation','Closed',None]),1)]
    text,audit=answer(question,rows,asof=date(2026,10,8))
    assert audit['active_only'] and audit['matching_ids']==[ids[0]]
    assert audit['returned_ids']==sorted(ids)
    assert 'Closed' in text
    assert '**1 of 3 requested records**' in text or '**1 sur 3 dossiers demandés**' in text
    assert 'not classified as active' in text or 'ne sont pas classés actifs' in text
    assert verify(text,rows)[1]['valid']


def test_date_only_question_retains_closed_records_when_no_active_constraint():
    rows=[record(664,'2026-11-30','E01','Closed')]
    text,audit=answer('For FONGIM project ID 664, which records have reported end dates in 2026?',rows)
    assert not audit['active_only'] and audit['matching_ids']==['664']


@pytest.mark.parametrize('q', [
    'For FONGIM project ID 664, which records are not active and have reported end dates in 2026?',
    'Pour FONGIM, identifiant de projet 664, quels projets non actifs ont une date de fin en 2026 ?',
])
def test_negated_active_constraint_defers(q):
    assert answer(q,[record(664,'2026-11-30','E01','Closed')]) is None
