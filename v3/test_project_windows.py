"""Professional closure windows: boundary arithmetic and actual source selection."""
from datetime import date
from copy import deepcopy
import pytest
from project_dates import reported_end_window, calendar_end_year, select_examples


@pytest.mark.parametrize('q,asof,wanted',[
 ('Which projects have closing dates in the next 12 months?',date(2026,10,8),('2026-10-08','2027-10-08')),
 ('Quels projets arrivent à échéance dans les 6 prochains mois ?',date(2026,10,8),('2026-10-08','2027-04-08')),
 ('Quels projets ont des dates de fin dans les 12 mois à venir ?',date(2026,10,8),('2026-10-08','2027-10-08')),
 ('Projects ending in the next 1 month',date(2024,1,31),('2024-01-31','2024-02-29')),
 ('Projects ending in the next 12 months',date(2024,2,29),('2024-02-29','2025-02-28')),
 ('Projects ending in the next 2 weeks',date(2026,10,8),('2026-10-08','2026-10-22')),
 ('Which projects have reported end dates this month?',date(2026,10,8),('2026-10-01','2026-10-31')),
 ('Quels projets ont une date de fin ce mois-ci ?',date(2024,2,8),('2024-02-01','2024-02-29')),
 ('Which projects have reported end dates next month?',date(2026,12,8),('2027-01-01','2027-01-31')),
 ('Quels projets ont une date de fin le mois prochain ?',date(2024,1,31),('2024-02-01','2024-02-29')),
 ('Which projects have reported end dates last month?',date(2026,1,8),('2025-12-01','2025-12-31')),
 ('Quels projets ont une date de fin le mois dernier ?',date(2024,3,8),('2024-02-01','2024-02-29')),
 ('Projects closing between 2026-12-01 and 2027-07-01',date(2026,10,8),('2026-12-01','2027-07-01')),
 ('Projets avec date de fin du 2027-01-01 au 2027-12-31',date(2026,10,8),('2027-01-01','2027-12-31')),
])
def test_calendar_months_explicit_bounds_and_french(q,asof,wanted):
 assert reported_end_window(q,asof)==wanted
 assert calendar_end_year(q,asof) is None


@pytest.mark.parametrize('q',[
 'Which projects are ending soon?', 'Funding in the next 12 months',
 'Projects ending in the next 0 months', 'Projects ending in the next 99 months',
 'Projects closing in the next 6 months or next 12 months',
 'Projects closing in the next 12 months and in 2028',
 'Projects closing this month or next year',
 'Projects closing this month or next month',
 'Projects closing last month or next month',
 'Projets avec une date de fin ce mois-ci ou en 2028',
 'Projets avec une date de fin ce mois-ci ou le mois prochain',
 'Projets avec une date de fin le mois dernier ou le mois prochain',
 'Projects ending between 2027-01-01 and 2026-01-01',
 'Projects ending between 2026-02-30 and 2027-01-01',
])
def test_ambiguous_or_invalid_period_is_not_invented(q):
 assert reported_end_window(q,date(2026,10,8)) is None


def test_explicit_window_does_not_include_overdue_or_silently_require_active_status():
 rows=[{'project_name':x,'end_date':d,'status':s} for x,d,s in [
  ('Past','2026-10-07','En cours'),('First','2026-10-08','Clôturé'),
  ('Beyond old window','2027-06-30','En cours'),('Last','2027-10-08','En cours'),
  ('Later','2027-10-09','En cours'),('Unknown',None,'En cours')]]
 selected,audit=select_examples(rows,ending=True,asof=date(2026,10,8),end_window=('2026-10-08','2027-10-08'))
 assert [r['project_name'] for r in selected]==['First','Beyond old window','Last']
 assert audit['matching_records']==3 and audit['missing_valid_end_date']==1
 assert 'successor funding' in audit['limitation']
 selected,_=select_examples(rows,end_window=('2026-10-08','2027-10-08'),active_only=True)
 assert len(selected)==2


def test_world_bank_real_snapshot_retrieves_upcoming_instead_of_overdue_profiles():
 from project_learning_sources import retrieve_project_learning
 from project_dates import parsed_date
 q='Which World Bank projects have reported closing dates in the next 12 months?'
 window=reported_end_window(q)
 rows=retrieve_project_learning(q)
 profiles=[r['project_record'] for r in rows if r.get('project_record')]
 assert len(profiles)==3
 assert {r['source_id'] for r in profiles}=={'P513735','P164032','P166796'}
 assert all(window[0]<=r['end_date'][:10]<=window[1] for r in profiles)
 assert any(f'from {window[0]} through {window[1]}, inclusive' in r['content'] for r in rows)


def test_eu_window_filters_each_publisher_without_rewriting_original_dates():
 import eu_sources as source
 source.retrieve_eu_evidence.cache_clear()
 q='Which EU projects have reported end dates in the next 12 months?'
 window=reported_end_window(q)
 rows=source.retrieve_eu_evidence(q)
 projects=[r['project_record'] for r in rows if r.get('project_record')]
 assert projects
 assert all(window[0]<=p['end_date'][:10]<=window[1] for p in projects)
 assert all('not the default 180-day screen' in r['content'] for r in rows if r.get('project_record'))


def test_fongim_worker_passes_actual_window_to_fresh_lookup():
 import ast,re,time,unicodedata
 from pathlib import Path
 tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
 research=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_four_source_research')
 worker=next(n for n in research.body if isinstance(n,ast.FunctionDef) and n.name=='timed_fongim')
 normalization=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='normalize_text')
 calls=[]
 ns={'question':'Which FONGIM projects are ending in the next 12 months?', 'geography':{},'re':re,'time':time,'unicodedata':unicodedata,
     'research_fongim':lambda geo,**kw:calls.append(kw)}
 exec(compile(ast.Module(body=[normalization,worker],type_ignores=[]),'worker','exec'),ns)
 ns['timed_fongim']()
 assert calls[0]['end_window']==reported_end_window(ns['question'])
