from datetime import date
from project_dates import select_examples, calendar_end_year
import pytest


@pytest.mark.parametrize('question,year', [
    ('Which projects have reported end dates in 2027?',2027),
    ('Quels projets ont une date de fin en 2026 ?',2026),
    ('Which projects are ending this year?',2026),
    ('Quels projets arrivent à échéance cette année ?',2026),
    ('What financing was reported in 2026?',None),
    ('Compare end dates in 2026 and 2027',None),
])
def test_calendar_end_year_preserves_single_period(question,year):
    assert calendar_end_year(question,date(2026,10,7)) == year


def test_calendar_dates_include_closed_and_early_year_records_without_window_leak():
    rows=[{'project_name':'Early closed','status':'Clôturé','end_date':'2026-01-01'},
          {'project_name':'Overdue active','status':'En cours','end_date':'2026-08-31'},
          {'project_name':'Next year','status':'En cours','end_date':'2027-01-01'}]
    selected,summary=select_examples(rows,ending=True,end_year=2026,asof=date(2026,10,7))
    assert [p['project_name'] for p in selected] == ['Early closed','Overdue active']
    assert summary['matching_records']==2 and summary['selected_records']==2
    assert 'not a rolling 180-day window' in summary['limitation']
    selected,_=select_examples(rows,end_year=2026,active_only=True)
    assert [p['project_name'] for p in selected] == ['Overdue active']


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
