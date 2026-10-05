from datetime import date
from project_dates import select_examples, ending_intent


def test_ending_records_and_past_active_conflicts():
    rows=[{'project_name':'A far later','status':'En cours','end_date':'2030-01-01'},
          {'project_name':'Z soon','status':'En cours','end_date':'2026-12-31'},
          {'project_name':'Past active','status':'En cours','end_date':'2025-01-01'},
          {'project_name':'Already closed','status':'Clôturé','end_date':'2026-12-01'},
          {'project_name':'Missing','status':'En cours','end_date':None}]
    selected,summary=select_examples(rows,ending=True,asof=date(2026,10,2))
    assert [r['project_name'] for r in selected]==['Z soon','Past active']
    assert summary['upcoming_active_records']==1 and summary['active_with_past_end_date']==1
    assert summary['active_missing_valid_end_date']==1
    assert summary['window_end']=='2027-03-31'
    normal,summary=select_examples(rows)
    assert normal[0]['project_name']=='A far later' and summary is None


def test_relative_project_window_keeps_inclusive_boundaries_and_rejects_far_future():
    rows=[{'project_name':name,'status':'En cours','end_date':end} for name,end in
          [('Start','2026-10-05'),('Last day','2027-04-03'),('Too late','2027-04-04'),
           ('Registry active, far later','2027-12-31')]]
    selected,summary=select_examples(rows,ending=ending_intent('Which dated project examples fall in the next 180 days?'),asof=date(2026,10,5))
    assert [r['project_name'] for r in selected]==['Start','Last day']
    assert summary['asof']=='2026-10-05' and summary['window_end']=='2027-04-03'
    assert summary['upcoming_active_records']==2
    assert not ending_intent('What humanitarian needs are forecast for the next 180 days?')
