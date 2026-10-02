from datetime import date
from project_dates import select_examples


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
