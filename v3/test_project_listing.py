from project_listing import render
from citations import verify


def records():
    screen={'evidence_id':'E01','source_type':'fongim_structured','section':'Reported-date selection; 180-day window',
            'content':'reported-date screening: {"asof":"2026-10-05","window_end":"2027-04-03","upcoming_active_records":2}.'}
    rows=[screen]
    for pid,status,end in [(2,'En cours','2026-11-30'),(3,'Active','2027-01-01'),(4,'En cours','2026-06-30'),(5,'Closed','2026-12-31')]:
        rows.append({'evidence_id':f'E{pid:02d}','source_type':'fongim_structured','section':'Project-ID relationship',
                     'content':f"FONGIM project ID {pid}: Example {pid}. Recorded organization names: ['Actor']. Recorded sectors: ['SAME', 'Nutrition']. Status: {status}; start/end dates: 2024-01-01 / {end}; latest sync: 2026-08-28T15:57:41+00:00."})
    return rows


def test_roster_cites_exact_records_and_preserves_raw_sectors_without_a_model():
    ledger=records();answer=render(ledger,'Which FONGIM projects end in the next 180 days?')
    assert '| 2 | Example 2 | 2026-11-30 | SAME; Nutrition | En cours [E02]' in answer
    assert '| 3 |' in answer and '| 4 |' not in answer and '| 5 |' not in answer
    assert 'agriculture' not in answer and 'complete portfolio' in answer
    assert verify(answer,ledger)[1]['valid']
    assert render(ledger,'Which individually dated FONGIM examples fall in the next 180 days, and what sectors are evidenced for those exact projects?') is not None
    french=render(ledger,'Quelles interventions FONGIM arrivent à échéance dans les 180 prochains jours ?','French')
    assert 'Date de fin déclarée' in french and '[E03]' in french


def test_joined_or_ambiguous_or_incomplete_queries_retain_synthesis():
    ledger=records()
    for q in ['Which FONGIM projects end in the next 180 days and align with humanitarian needs?',
              'Which of those FONGIM projects end in the next 180 days?',
              'Which FONGIM projects end in the next 30 days?',
              'Which World Bank projects end in the next 180 days?',
              'Which FONGIM projects end in the next 180 days as of 2027-01-01?']:
        assert render(ledger,q) is None
    duplicate=dict(ledger[1],content=ledger[1]['content'].replace('2026-11-30','2026-11-01'))
    assert render(ledger+[duplicate],'Which FONGIM projects end in the next 180 days?') is None
    assert render(ledger[1:],'Which FONGIM projects end in the next 180 days?') is None
    ledger[1]['content']=ledger[1]['content'].replace("['SAME', 'Nutrition']",'missing')
    assert render(ledger,'Which FONGIM projects end in the next 180 days?') is None
