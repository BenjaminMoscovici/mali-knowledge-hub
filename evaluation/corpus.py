"""Read-only GIZ source snapshot; never reads account histories or modifies data."""
import argparse,json,urllib.request,urllib.parse
from pathlib import Path
from .common import config,now,write_json,digest

def capture(config_path,out):
 c=config(config_path);headers={'apikey':c['SUPABASE_SECRET_KEY'],'Authorization':'Bearer '+c['SUPABASE_SECRET_KEY']}
 def rows(table):
  result=[]
  for offset in range(0,10000,500):
   params=urllib.parse.urlencode({'select':'*','limit':500,'offset':offset,'order':'id.asc'})
   with urllib.request.urlopen(urllib.request.Request(c['SUPABASE_URL']+'/rest/v1/'+table+'?'+params,headers=headers),timeout=45) as r:page=json.load(r)
   result.extend(page)
   if len(page)<500:return result
  raise ValueError('Corpus pagination bound exceeded; no silently truncated oracle')
 docs=rows('documents');chunks=[{k:v for k,v in row.items() if k!='embedding'} for row in rows('chunks')]
 result={'captured_at':now(),'project_ref':'hofoubbmepacdljeablj','access':'read-only shared source tables; no user tables',
  'documents':docs,'chunks':chunks,'snapshot_hash':digest({'documents':docs,'chunks':chunks})}
 write_json(out,result)
 return {'documents':len(docs),'chunks':len(chunks),'snapshot_hash':result['snapshot_hash']}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(capture(a.config,a.output)))
