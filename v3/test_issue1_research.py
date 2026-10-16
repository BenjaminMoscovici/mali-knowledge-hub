"""Exercise actual source-worker functions, not a parallel reimplementation."""
import ast
from pathlib import Path
import time,re,unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from metering import submit
from project_dates import select_examples


def fongim_function():
 tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
 fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='research_fongim')
 fn.decorator_list=[]
 projects=[{'fongim_project_id':1,'project_name':'Ongoing A','status':'En cours','start_date':'2025-01-01','end_date':'2026-01-01','last_synced_at':'2026-08-28','last_seen_sync_id':'snapshot-A'},
 {'fongim_project_id':2,'project_name':'Closed B','status':'Clôturé','last_synced_at':'2026-08-28','last_seen_sync_id':'snapshot-A'}]
 tables={'fongim_project_locations':[{'fongim_project_id':1,'region':'Mopti','cercle':'Mopti','commune_raw':'A'}, {'fongim_project_id':1,'region':'Mopti','cercle':'Mopti','commune_raw':'B'}, {'fongim_project_id':2,'region':'Mopti','cercle':'Mopti','commune_raw':'C'}],
 'fongim_projects':projects,'fongim_project_sectors':[{'fongim_project_id':1,'sector':'Health'},{'fongim_project_id':2,'sector':'Education'}],
 'fongim_project_organizations':[{'fongim_project_id':1,'fongim_organization_id':11},{'fongim_project_id':2,'fongim_organization_id':22}]}
 class Query:
  def __getattr__(self,name):return lambda *a,**k:self
 ns={'time':time,'re':re,'defaultdict':defaultdict,'ThreadPoolExecutor':ThreadPoolExecutor,'submit':submit,
     'fetch_all_rows':lambda table,**kw:tables[table],
     'get_rows_for_project_ids':lambda table,cols,ids:[r for r in tables[table] if r['fongim_project_id'] in ids],
     'execute_read':lambda *a:SimpleNamespace(data=[{'fongim_organization_id':11,'organization_name':'Ongoing NGO'},{'fongim_organization_id':22,'organization_name':'Closed NGO'}]),
     'supabase':Query(),'select_examples':select_examples}
 exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-fongim-worker','exec'),ns)
 return ns[fn.name]


def test_actual_fongim_all_aggregate_relationships_use_filtered_projects():
 r=fongim_function()({'region':'Mopti'},active_only=True)
 text=' '.join(e['content'] for e in r['evidence'])
 assert r['project_count']==1 and r['location_count']==2
 assert 'Closed NGO' not in text and 'Closed B' not in text and 'Education' not in text
 assert 'Ongoing NGO' in text and 'Health' in text
 assert all(e['snapshot_ids']==['snapshot-A'] for e in r['evidence'])
 assert all(e['source_record_ids']==['1'] for e in r['evidence'])
 assert '2026-01-01' in text # Past end date retained, never silently made current.


def test_actual_fongim_all_status_query_preserves_closed_records_and_unique_counts():
 r=fongim_function()({'region':'Mopti'})
 assert r['project_count']==2 and r['location_count']==3
 assert any('Closed B' in e['content'] for e in r['evidence'])
 assert all(e['status_selection'] is None for e in r['evidence'])


def research_function(monkeypatch, hapi):
 import geographic_model
 from routing import explicit_source_plan,bounded_fts_source_names,bounded_project_learning_source_names
 from source_wave import retrieve_source_evidence
 from operational_sources import retrieve_operational_evidence
 from analytical_sources import retrieve_analytical_evidence
 tree=ast.parse(Path(__file__).with_name('analysis_core.py').read_text())
 fns=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('run_four_source_research','normalize_text','build_unified_evidence')]
 ns={'time':time,'re':re,'unicodedata':unicodedata,'defaultdict':defaultdict,'ThreadPoolExecutor':ThreadPoolExecutor,'submit':submit,
 'plan_sources_semantically':lambda q:{'source_plan':{'government_docs':False,'hnrp_docs':False,'hapi':True,'fongim':False},'seconds':0,'planner_output':{'method':'test_explicit'}},
 'resolve_geography':lambda q:{'region':'Gao','cercle':None},'build_hapi_evidence':hapi,
 'bounded_fts_source_names':bounded_fts_source_names,'bounded_project_learning_source_names':bounded_project_learning_source_names,
 'retrieve_source_evidence':retrieve_source_evidence,'retrieve_operational_evidence':retrieve_operational_evidence,'retrieve_analytical_evidence':retrieve_analytical_evidence,
 'retrieve_project_learning':lambda q:[],'retrieve_eu_evidence':lambda q:[],
 'enrich_join_evidence':lambda ledger:None,'build_join_context':lambda *a:{},'load_entity_decisions':lambda:({},[]),'OrganizationResolver':lambda *a:None}
 exec(compile(ast.Module(body=fns,type_ignores=[]),'actual-research-worker','exec'),ns)
 return ns['run_four_source_research']

@pytest.mark.parametrize('offline',[False,True])
def test_actual_hapi_empty_and_offline_keep_stored_dated_evidence(monkeypatch,offline):
 def hapi(g):
  if offline:raise TimeoutError('secret provider URL must never be serialized')
  return {'raw_count':0,'evidence':[]}
 r=research_function(monkeypatch,hapi)('Quels besoins sectoriels sont documentés à Gao ?')
 assert r['ledger'] and all(e['evidence_id'] for e in r['ledger'])
 assert any(e['source_family']=='OCHA Global HPC HNO 2026' for e in r['ledger'])
 assert any(e['source_type']=='food_security_classification' for e in r['ledger'])
 status=r['execution_trace']['sources']['hapi']['status']
 assert status==('UNAVAILABLE_STORED_EVIDENCE_RETAINED' if offline else 'SUCCESS_ZERO_RESULTS')
 assert 'secret provider URL' not in str(r)
 if offline:assert any(e['source_type']=='source_availability' for e in r['ledger'])
