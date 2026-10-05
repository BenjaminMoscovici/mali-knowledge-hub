"""Resumable live guest runner; expectations are never transmitted to the Hub."""
import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from .common import ROOT, digest, load_cases, now, verify_freeze, write_json

BASE='https://mali-knowledge-hub-v4-test.onrender.com'

def request_case(case,base=BASE):
 payload={'question':case['question'],'analysis_mode':case['difficulty'],
          'prior_messages':case.get('prior_messages',[])}
 # Deliberately whitelist request fields: no expected answers/rubrics/tags.
 started=time.perf_counter(); stamp=now()
 request=urllib.request.Request(base+'/api/chat',data=json.dumps(payload).encode(),
  headers={'Content-Type':'application/json','Origin':base})
 try:
  with urllib.request.urlopen(request,timeout=240) as r:
   body=json.load(r);status=r.status
  return {'ok':True,'http_status':status,'started_at':stamp,
   'client_seconds':time.perf_counter()-started,'response':body,'request_payload':payload}
 except (urllib.error.URLError,TimeoutError,ValueError) as exc:
  # Failure bodies/credentials are never dumped. Preserve each attempted failure.
  return {'ok':False,'http_status':getattr(exc,'code',None),'started_at':stamp,
   'client_seconds':time.perf_counter()-started,'error_type':type(exc).__name__,
   'response':None,'request_payload':payload,'cost_unknown':True}

def capture_telemetry(record):
 r=record.get('response') or {};m=r.get('metrics') or {};e=r.get('evidence') or []
 families={}
 for item in e:families[item.get('source_family','unknown')]=families.get(item.get('source_family','unknown'),0)+1
 calls=m.get('context_api_usage',{}).get('calls',[])+m.get('research_api_usage',{}).get('calls',[])
 missing=[]
 for key in ['source_plan','per_family_retrieval_seconds','retrieval_ranks']:
  if key not in m:missing.append(key)
 audit=m.get('synthesis_context') or {}
 return {'hub_commit':m.get('hub_commit'),'route':m.get('route'),'depth':m.get('depth'),'routing_seconds':m.get('routing_seconds'),
  'source_plan':m.get('source_plan'),'source_plan_observation':'not returned by baseline API; evidence families do not prove all queried families',
  'retrieval_seconds':m.get('research_seconds'),'evidence_count':len(e),'family_counts':families,
  'rankings':[{k:i.get(k) for k in ['evidence_id','source_family','similarity','score','rank']} for i in e],
  'evidence_assembly':audit,'input_tokens':sum(c.get('input_tokens',0) for c in calls),
  'cached_input_tokens':sum(c.get('cached_input_tokens',0) for c in calls),
  'output_tokens':sum(c.get('output_tokens',0) for c in calls),'model_calls':calls,
  'external_calls':m.get('research_api_usage',{}).get('external_calls',[]),
  'synthesis_seconds':m.get('synthesis_seconds'),'server_seconds':m.get('server_seconds'),
  'estimated_usd':m.get('estimated_usd'),'unpriced_calls':m.get('unpriced_calls'),
  'answer_chars':len(r.get('answer','')),'telemetry_missing':missing}

def persist(out,record):
 name=f"{record['case_id']}--{record['repetition']}.json"
 write_json(out/'raw'/name,record)
 db=sqlite3.connect(out/'results.sqlite')
 db.execute('create table if not exists attempts(case_id text,repetition integer,split text,ok integer,payload text,primary key(case_id,repetition))')
 db.execute('insert or replace into attempts values(?,?,?,?,?)',(record['case_id'],record['repetition'],record['split'],record['ok'],json.dumps(record,ensure_ascii=False)))
 db.commit();db.close()

def deployed_commit_matches(record,expected,required=False):
 observed=(record.get('response') or {}).get('metrics',{}).get('hub_commit')
 if observed is None:return not required
 return observed==expected

def run(args):
 manifest=verify_freeze();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 meta=out/'run_manifest.json'
 configuration={'benchmark_manifest_sha256':digest(manifest),'hub_commit':args.hub_commit,
  'endpoint':args.base,'split':args.split,'client_concurrency':1,'started_at':now(),
  'giz_project_ref':manifest['giz_project_ref'],'frozen_commit':'b298353',
  'timeout_seconds':240,'automatic_retries':0,'latency_policy':'Each attempt retained; no resampling failed calls; server and client latency separate.',
  'web_verification':'Separate, after immutable answer capture; never supplied to Hub.'}
 if meta.exists():
  old=json.loads(meta.read_text())
  for key in ['hub_commit','endpoint','split','benchmark_manifest_sha256']:
   if old[key]!=configuration[key]:raise ValueError('Cannot resume a different run configuration')
 else:write_json(meta,configuration)
 cases=load_cases(args.split,args.acceptance)
 if meta.exists():
  old=json.loads(meta.read_text())
  if old.get('suite_hash') and old['suite_hash']!=digest(cases):raise ValueError('Run suite changed; cannot resume')
  old['suite_hash']=digest(cases);write_json(meta,old)
 if args.ids:cases=[c for c in cases if c['id'] in args.ids.split(',')]
 for case in cases:
  count=args.repetitions if not args.repeat_ids or case['id'] in args.repeat_ids.split(',') else 1
  for repeat in range(count):
   path=out/'raw'/f"{case['id']}--{repeat}.json"
   if path.exists():continue
   record=request_case(case,args.base)
   record.update(case_id=case['id'],repetition=repeat,split=args.split,case_hash=digest(case),
    response_hash=digest(record['response']),run_hub_commit=args.hub_commit)
   record['telemetry']=capture_telemetry(record);persist(out,record)
   if record['ok'] and not deployed_commit_matches(record,args.hub_commit,getattr(args,'require_commit',False)):
    # Preserve the actual answer and cost before stopping a mixed/unknown build.
    record['ok']=False;record['error_type']='DeployedCommitMismatch'
    persist(out,record)
    raise ValueError('Live answer did not come from the immutable benchmarked commit')
   print(json.dumps({'case':case['id'],'repetition':repeat,'ok':record['ok'],
    'server_seconds':record['telemetry']['server_seconds'],'client_seconds':round(record['client_seconds'],2),
    'usd':record['telemetry']['estimated_usd']}),flush=True)
 configuration=json.loads(meta.read_text());configuration['completed_at']=now()
 configuration['attempts']=len(list((out/'raw').glob('*.json')));write_json(meta,configuration)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--split',choices=['frozen','rolling','heldout'],default='frozen')
 p.add_argument('--output',required=True);p.add_argument('--base',default=BASE)
 p.add_argument('--hub-commit',required=True);p.add_argument('--acceptance',action='store_true')
 p.add_argument('--require-commit',action='store_true')
 p.add_argument('--ids');p.add_argument('--repetitions',type=int,default=1);p.add_argument('--repeat-ids')
 args=p.parse_args()
 if args.repetitions<1:raise SystemExit('At least one repetition required')
 run(args)
