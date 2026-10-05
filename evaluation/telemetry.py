"""Enrich immutable attempts from existing MKH_USAGE logs, by request ID only."""
import argparse,json
from pathlib import Path
from .common import digest,now,write_json

def import_usage(run,export):
 root=Path(run);by_id={r['request_id']:r for r in export['records'] if r.get('request_id')}
 matches={}
 for p in (root/'raw').glob('*.json'):
  r=json.loads(p.read_text());rid=(r.get('response') or {}).get('metrics',{}).get('request_id')
  if rid not in by_id:continue
  log=by_id[rid];usage=(r['response']['metrics'].get('research_api_usage') or {})
  if 'api_usage' in log and digest(usage)!=digest(log['api_usage']):
   raise ValueError('Request-ID match has different measured usage; cannot enrich')
  matches[p.stem]={'response_hash':r['response_hash'],'request_id':rid,
   'source_plan':log['source_plan'],'source_plan_scope':'Four core retrieval families; other source-wave queries not exposed by this log',
   'observed_at':now(),'log_hash':digest(log)}
 result={'export_hash':digest(export),'captured_at':now(),'matched_attempts':len(matches),'attempts':matches}
 write_json(root/'telemetry_enrichment.json',result);return result

def enriched(run,record):
 failure=Path(run)/'failure_telemetry.json'
 if failure.exists():
  observed=json.loads(failure.read_text())
  if digest(record)!=observed['raw_record_hash']:
   raise ValueError('Failure telemetry does not match immutable attempt')
  copy=dict(record);copy['telemetry']=dict(record['telemetry'])
  usage=observed['api_usage'];calls=usage.get('calls',[])
  copy['telemetry'].update(model_calls=calls,
   input_tokens=sum(c.get('input_tokens',0) for c in calls),
   output_tokens=sum(c.get('output_tokens',0) for c in calls),
   external_calls=usage.get('external_calls',[]),
   estimated_usd=sum(c.get('estimated_usd') or 0 for c in calls),
   cost_observation='Measured completed-call lower bound from matched isolated failure log; in-flight cost remains unknown')
  return copy
 path=Path(run)/'telemetry_enrichment.json'
 if not path.exists():return record
 rows=json.loads(path.read_text())['attempts'];key=f"{record['case_id']}--{record['repetition']}"
 if key not in rows:return record
 observed=rows[key]
 if observed['response_hash']!=record['response_hash']:raise ValueError('Telemetry answer hash mismatch')
 copy=dict(record);copy['telemetry']=dict(record['telemetry'])
 copy['telemetry']['source_plan']=observed['source_plan']
 copy['telemetry']['source_plan_observation']=observed['source_plan_scope']
 copy['telemetry']['telemetry_missing']=[k for k in copy['telemetry']['telemetry_missing'] if k!='source_plan']
 copy['telemetry']['telemetry_missing'].append('source_wave_query_plan')
 return copy

def import_isolated_failure(run, log_file):
 """Bind a single failed isolated request to its sanitized usage log.

 Never infer a request match from timing or inspect account logs. Multi-request
 logs and successful attempts are deliberately excluded from this narrow route.
 """
 root=Path(run);manifest=json.loads((root/'run_manifest.json').read_text())
 if manifest.get('measurement_protocol')!='isolated-asgi-guest-v1':
  raise ValueError('Failure import requires the isolated synthetic protocol')
 raws=list((root/'raw').glob('*.json'))
 if len(raws)!=1:raise ValueError('Failure import requires exactly one attempted request')
 record=json.loads(raws[0].read_text())
 if record.get('ok'):raise ValueError('A successful request cannot use failure telemetry')
 text=Path(log_file).read_text();health=[];attempts=[];failures=[]
 for line in text.splitlines():
  if line.startswith('MKH_FAILURE '):failures.append(json.loads(line.split(' ',1)[1]))
  elif line.startswith('{'):
   item=json.loads(line)
   if 'isolated_health' in item:health.append(item)
   if 'case' in item:attempts.append(item)
 if len(health)!=1 or health[0].get('commit')!=manifest['hub_commit']:
  raise ValueError('Failure log commit mismatch')
 if len(attempts)!=1 or attempts[0].get('case')!=record['case_id'] or attempts[0].get('repetition')!=record['repetition'] or attempts[0].get('ok') is not False:
  raise ValueError('Failure log attempt mismatch')
 if len(failures)!=1 or failures[0].get('depth')!=record['request_payload']['analysis_mode']:
  raise ValueError('Failure log must contain one matching usage receipt')
 event=failures[0]
 # Existing MKH_FAILURE emits metering fields only, never prompts, source
 # passages or auth credentials. Preserve the exact receipt and log hash.
 result={'raw_record_hash':digest(record),'source_log_hash':digest(text),
  'request_id':event['request_id'],'error_type':event['error_type'],
  'api_usage':event['api_usage'],'observed_at':now(),
  'scope':'Single frozen anonymous isolated request; completed-call cost lower bound only'}
 write_json(root/'failure_telemetry.json',result)
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--export',required=True);a=p.parse_args()
 print(json.dumps({'matched_attempts':import_usage(a.run,json.loads(Path(a.export).read_text()))['matched_attempts']}))
