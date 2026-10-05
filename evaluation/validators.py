"""Deterministic, scoped checks. Unknown is never silently converted to pass."""
import gzip
import json
import re
import sqlite3
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from .common import ROOT

sys.path.insert(0,str(ROOT/'v3'))
from citations import verify as verify_citations

@lru_cache(maxsize=1)
def snapshot_path():
 path=Path(tempfile.mkdtemp(prefix='mkh-eval-oracle-'))/'source.sqlite'
 path.write_bytes(gzip.decompress((ROOT/'v3'/'source_wave1.sqlite.gz').read_bytes()))
 return path

def family_key(item):
 s=(item.get('source_family') or '').lower()
 for prefix,key in [('government','government'),('humanitarian response','hnrp'),
 ('humanitarian reports','hnrp'),('ocha humanitarian data','hapi'),('fongim','fongim'),
 ('ocha global hpc','hpc'),('ocha mali 3w','3w'),('iom dtm','dtm'),
 ('cadre','ch'),('ocha fts','fts'),('world bank','world_bank'),('iati','iati'),
 ('ieg','ieg'),('eu /','eu'),('mali geographic','geography'),('instat','geography'),
 ('official','geography'),('ocha cod','geography')]:
  if s.startswith(prefix):return key
 t=item.get('source_type','')
 if t in {'official_population','population_projection','official_geography','official_geography_registry','administrative_geography'}:return 'geography'
 return s

def numbers(text):
 found=[]
 for m in re.finditer(r'(?<!\d)(?:\d{1,3}(?:[,.\u00a0\u202f ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?:\s*(?:million(?:s)?|milliard(?:s)?|billion(?:s)?|m\b))?',str(text),re.I):
  raw=m.group();factor=1
  if re.search(r'milliard|billion',raw,re.I):factor=1e9
  elif re.search(r'million|m\b',raw,re.I):factor=1e6
  numeric=re.sub(r'[^\d.,]','',raw)
  if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+',numeric):numeric=re.sub('[,.]','',numeric)
  elif ',' in numeric and '.' not in numeric:numeric=numeric.replace(',','.')
  elif ',' in numeric:numeric=numeric.replace(',','')
  try:found.append(float(numeric)*factor)
  except ValueError:pass
 return found

def contains_number(text,value,financial=False):
 vals=numbers(text)
 target=float(value)
 return any(abs(v-target)<=max(1e-8,abs(target)*1e-9) or
  (financial and abs(v-target*1e6)<=max(1e-8,abs(target)*1e-3)) for v in vals)

@lru_cache(maxsize=1)
def original_records():
 ids={};releases={}
 for wave in range(2,6):
  p=json.loads(gzip.decompress((ROOT/'v3'/f'source_wave{wave}.json.gz').read_bytes()))
  ids.update({r['id']:r for r in p['records']})
  releases.update({r['id']:r for r in p['tables']['mkh_source_releases']})
 return ids,releases

def check(identifier,dimension,status,detail,severity='major'):
 return {'id':identifier,'dimension':dimension,'status':status,'detail':detail,'severity':severity}

def validate(case,record,chunk_index=None):
 if not record.get('ok'):
  return [check('request_success','availability','fail',f"HTTP {record.get('http_status')} / {record.get('error_type')}"),
          check('grounding','factual_grounding','unknown','No answer; cannot treat failure as factual success')]
 r=record['response'];answer=r.get('answer','');e=r.get('evidence',[]);m=r.get('metrics',{})
 result=[check('request_success','availability','pass','Live response returned')]
 normalized,audit=verify_citations(answer,e)
 result.append(check('citation_ids','citation_validity','pass' if audit['valid'] else 'fail',json.dumps(audit)))
 ids=[i.get('evidence_id') for i in e]
 result.append(check('unique_eids','citation_validity','pass' if len(set(ids))==len(ids) else 'fail','Evidence IDs must be unique'))
 omitted=set(m.get('synthesis_context',{}).get('omitted_ids',[])+m.get('synthesis_context',{}).get('duplicate_ids',[]))
 result.append(check('selected_citations','citation_validity','fail' if omitted&set(audit['cited_ids']) else 'pass','No citations to evidence excluded before synthesis'))
 actual={family_key(i) for i in e}
 for wanted in case['required_source_families']:
  result.append(check('evidence_family:'+wanted,'retrieval_family_coverage','pass' if wanted in actual else 'fail',
    'Required family present in returned evidence; does not prove whether absent families were queried'))
 plan=record.get('telemetry',{}).get('source_plan')
 core={'government':'government_docs','hnrp':'hnrp_docs','hapi':'hapi','fongim':'fongim'}
 for wanted in case['required_source_families']:
  key=core.get(wanted)
  known=bool(plan is not None and key in plan)
  result.append(check('queried_family:'+wanted,'routing',('pass' if plan[key] else 'fail') if known else 'unknown',
   'Core source plan checked against request-ID-matched Render log' if known else 'Query plan unavailable for this family','info'))
 originals,releases=original_records()
 db=sqlite3.connect(snapshot_path());db.row_factory=sqlite3.Row
 cited=set(audit['cited_ids'])
 for item in e:
  if item.get('evidence_id') not in cited:continue
  eid=item['evidence_id'];rid=item.get('record_id');locator=item.get('locator') or item.get('section');page=item.get('page')
  if item.get('chunk_id') is not None:
   original=(chunk_index or {}).get(str(item['chunk_id']))
   if original is None:
    result.append(check(eid+':chunk','source_locator','unknown','Original GIZ chunk not captured'))
   else:
    valid=(original.get('document_id')==item.get('document_id') and
      (page is None or original.get('page_number',original.get('page'))==page))
    result.append(check(eid+':chunk','source_locator','pass' if valid else 'fail','GIZ chunk ID, document ID and page checked against read-only corpus snapshot'))
  elif rid in originals:
   original=originals[rid]
   valid=(item.get('release_id')==original['release_id'] and bool(locator))
   # Aggregates use one record ID plus many row locators: certify anchor, not every aggregated row.
   result.append(check(eid+':record','source_locator','pass' if valid else 'fail','Packaged original record/release anchor exists; aggregate row extent checked separately where available'))
   if original.get('sheet') is not None:
    extent_ok=True
    for part in str(locator).split('; '):
     sheet,sep,extent=part.partition(' rows ')
     known={x['row'] for x in originals.values() if x.get('sheet')==sheet and x['release_id']==original['release_id']}
     if not sep or not known:extent_ok=False;continue
     for interval in extent.split(','):
      match=re.fullmatch(r'(\d+)(?:-(\d+))?',interval.strip())
      if not match:extent_ok=False;continue
      first=int(match[1]);last=int(match[2] or match[1])
      if last<first or last-first>20000 or not set(range(first,last+1))<=known:extent_ok=False
    result.append(check(eid+':row_extent','source_locator','pass' if extent_ok else 'fail','Every cited aggregate spreadsheet row exists in the pinned source release'))
   if page is not None and original.get('page') is not None:
    result.append(check(eid+':page','source_locator','pass' if page==original['page'] else 'fail','Original PDF page matches anchor'))
  elif rid:
   matched=None
   for table in ['mkh_source_releases','mkh_population_observations','mkh_humanitarian_observations','mkh_evidence_spans']:
    row=db.execute(f'select * from {table} where id=?',(rid,)).fetchone()
    if row:matched=dict(row);break
   result.append(check(eid+':stored_anchor','source_locator','pass' if matched and locator else 'unknown',
    'Stored source anchor exists' if matched else 'Aggregated/dynamic source needs independent row validation'))
  elif item.get('source_type') in {'hdx_hapi','fongim_structured'}:
   result.append(check(eid+':dynamic','source_locator','unknown','Dynamic HAPI/FONGIM API evidence has scope/excerpt but no independently exposed exact record locator'))
  else:result.append(check(eid+':locator','source_locator','unknown','No independently resolvable record/chunk anchor'))
  if page is not None:
   result.append(check(eid+':positive_page','source_locator','pass' if isinstance(page,(int,float)) and page>0 else 'fail','Positive source page'))
  start=item.get('reference_period_start');end=item.get('reference_period_end')
  if start and end:result.append(check(eid+':period','temporal_metadata','pass' if start<=end else 'fail','Reference start <= reference end'))
 db.close()
 for a in case.get('deterministic_assertions',[]):
  passed=None;detail=''
  if a['type']=='answer_regex':
   matched=bool(re.search(a['pattern'],answer,re.I|re.S));passed=not matched if a.get('negative') else matched
   detail='Explicit behavior signal; semantic support evaluated independently'
  elif a['type']=='route':passed=m.get('route') in a['allowed'];detail='Observed route: '+str(m.get('route'))
  elif a['type']=='zero_calls':passed=all(m.get(k)==0 for k in ['model_calls','embedding_calls','external_research_calls']);detail='Tracked call counters all zero'
  elif a['type']=='source_number':
   family=[i for i in e if family_key(i)==a['family']]
   financially=a['family'] in {'eu','fts','world_bank','iati'}
   source_has=any(contains_number(i.get('content','') or i.get('source_excerpt',''),a['value'],financially) for i in family)
   answer_has=contains_number(answer,a['value'],financially)
   passed=source_has and answer_has
   detail=f"Expected source value {a['value']}: returned-family evidence={source_has}, answer={answer_has}; presence check does not certify scope/entailment"
  if passed is not None:result.append(check(a['id'],a['dimension'],'pass' if passed else 'fail',detail,a['severity']))
 return result
