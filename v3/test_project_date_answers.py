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
