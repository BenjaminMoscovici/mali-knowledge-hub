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

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--export',required=True);a=p.parse_args()
 print(json.dumps({'matched_attempts':import_usage(a.run,json.loads(Path(a.export).read_text()))['matched_attempts']}))
