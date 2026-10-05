"""Import independent, answer-hash-bound public verification findings."""
import argparse,json
from pathlib import Path
from .common import digest,write_json

CATEGORIES={'Hub wrong','Hub stale','Hub incomplete','web source weaker than Hub source',
 'sources genuinely disagree','not independently verifiable','consistent'}
def validate_import(findings,run):
 root=Path(run);result=[]
 for f in findings:
  if f['classification'] not in CATEGORIES:raise ValueError('Invalid discrepancy classification')
  p=root/'raw'/f"{f['case_id']}--{f.get('repetition',0)}.json"
  record=json.loads(p.read_text())
  if f['response_hash']!=record['response_hash']:raise ValueError('Web check does not match frozen Hub answer')
  if not f.get('checked_at') or not f.get('sources') or not f.get('comparison'):raise ValueError('Missing independent check provenance')
  for s in f['sources']:
   if not s.get('url','').startswith('https://') or not s.get('retrieved_at'):raise ValueError('Source missing URL/retrieval date')
  result.append(f)
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--findings',required=True);a=p.parse_args()
 f=json.loads(Path(a.findings).read_text());validated=validate_import(f['checks'],a.run)
 write_json(Path(a.run)/'web_verification.json',{'method':'Independent research after frozen answer; no repair','checks':validated})
 print(json.dumps({'checks':len(validated),'classifications':{k:sum(x['classification']==k for x in validated) for k in CATEGORIES}}))
