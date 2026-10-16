import pytest
from integration_policy import integration_intent, reported_active_requested, select_reported_active
from routing import explicit_source_plan
from operational_sources import retrieve_operational_evidence
from source_wave import retrieve_source_evidence

@pytest.mark.parametrize('q',[
 'Quelles ONG de FONGIM interviennent actuellement dans la région de Mopti ?',
 'Which FONGIM projects are currently active in Gao?',
 'Quels projets sont en cours ?', 'Welche Projekte laufen aktuell?',
])
def test_current_status_selection_is_explicit(q):
 assert reported_active_requested(q)

@pytest.mark.parametrize('q',['Compare all FONGIM projects','Quels projets ne sont pas actifs ?','not active projects'])
def test_no_accidental_active_filter(q):
 assert not reported_active_requested(q)


def test_closed_and_unknown_status_never_contaminate_ongoing_counts():
 rows=[{'status':'En cours','fongim_project_id':1},{'status':'Clôturé','fongim_project_id':2},{'status':None,'fongim_project_id':3}]
 selected,trace=select_reported_active(rows,True)
 assert [p['fongim_project_id'] for p in selected]==[1]
 assert trace['excluded_projects']==2 and 'not proof' in trace['limitation']
 assert select_reported_active(rows,False)==(rows,None)

@pytest.mark.parametrize('q',[
 "Quels acteurs figurent dans le 3W d'OCHA au T1 2026 à Mopti ?",
 'Compare la présence rapportée par FONGIM et OCHA 3W à Mopti.',
 'Où existe-t-il des lacunes entre besoins et interventions ?',
 'Which 5W actors are present in Mopti in 2027?',
])
def test_presence_planner_is_inspectable(q):
 assert integration_intent(q)['ocha_3w']


def test_named_3w_does_not_request_fongim_or_live_needs_by_default():
 p=explicit_source_plan("Quels acteurs figurent dans le 3W d'OCHA au T1 2026 à Mopti ?")
 assert p is not None and not any(p.values())
 p=explicit_source_plan('Compare la présence rapportée par FONGIM et OCHA 3W à Mopti.')
 assert p['fongim'] and not p['hapi']


def test_actual_packaged_presence_rows_keep_releases_dates_and_row_locators():
 ev=retrieve_operational_evidence("Quels acteurs figurent dans le 3W d'OCHA au T1 2026 à Mopti ?")
 presence=[e for e in ev if e['source_type']=='operational_presence']
 assert presence and all(e['reference_period_start']=='2026-01-01' for e in presence)
 assert all(e['release_id'] and e['source_record_count']>0 and e['source_record_ids'] and e['locator'] for e in presence)
 assert 'no separate 5W' in presence[0]['content']
 assert 'not beneficiaries or projects' in presence[0]['content']


def test_hno_remains_national_and_distinguishes_indicators():
 p=explicit_source_plan("Combien de personnes avaient besoin d'assistance humanitaire au Mali selon le HNO 2026 ?")
 assert p is not None and not p['hapi']
 e=next(e for e in retrieve_source_evidence('HNO 2026 needs Gao') if e['source_type']=='humanitarian_planning_snapshot')
 assert e['geographic_scope']=='Mali — national only'
 assert all(s in e['content'] for s in ('People in Need','targeted','national population estimate','cannot establish'))


def test_dtm_is_a_stock_not_pin_or_delivery():
 e=retrieve_operational_evidence('DTM displaced people in Mopti')
 assert e and all(r['source_type']=='displacement_stock' for r in e)
 assert all('STOCK (not flow)' in r['content'] and 'not a region/cercle total' in r['content'] for r in e)

@pytest.mark.parametrize('q',[
 'Quelles ONG de FONGIM interviennent actuellement dans la région de Mopti ?',
 "Quels acteurs figurent dans le 3W d'OCHA au T1 2026 à Mopti ?",
 'Compare la présence rapportée par FONGIM et OCHA 3W à Mopti.',
 "Combien de personnes avaient besoin d'assistance humanitaire au Mali selon le HNO 2026 ?",
 'Quels besoins sectoriels sont documentés à Gao ?',
 'Où existe-t-il des lacunes entre besoins et interventions ?',
 'Quels acteurs du 3W sont présents dans la commune de Socoura ?',
 'Quels projets FONGIM sont actifs en 2027 ?',
 'What is the HNO population in need in Gao commune?',
 'Which actors are in OCHA 5W in Mali?',
 'Compare DTM displaced people with HNO people in need.',
 'Show HAPI needs for Unknownville commune.',
 'Which FONGIM projects are closed in Mopti?',
 'Which needs are covered by FONGIM projects in Gao?',
 'Give commune-level HNO 2026 estimates for Mopti.',
])
def test_issue_acceptance_questions_reach_research_instead_of_geography(q):
 from query_router import classify
 assert classify(q)['path']=='complex_research'


def test_unknown_commune_never_becomes_a_national_presence_total():
 e=retrieve_operational_evidence('OCHA 3W actors in commune de Unknownville')
 assert len(e)==1 and 'no matching rows' in e[0]['content']
 assert 'Unmatched requested' in e[0]['geographic_scope']


def test_empty_presence_source_reports_unavailability_not_zero_assistance(monkeypatch):
 import operational_sources as op
 monkeypatch.setattr(op,'package',lambda:{'records':[]})
 # Call the undecorated retrieval so a previous question cache cannot supply data.
 fn=op.retrieve_operational_evidence
 while hasattr(fn,'__wrapped__'):fn=fn.__wrapped__
 e=fn('OCHA 3W actors in empty source')
 assert e[0]['source_type']=='source_availability'
 assert 'does not establish absence' in e[0]['content']
 assert 'release_id' not in e[0]
