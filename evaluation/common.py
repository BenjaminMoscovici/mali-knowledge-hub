import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / 'evaluation' / 'benchmarks'

def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def write_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.partial');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,path)
def verify_freeze():
 manifest=json.loads((BENCH/'freeze_manifest.json').read_text())
 for name,wanted in manifest['files'].items():
  if hashlib.sha256((BENCH/name).read_bytes()).hexdigest()!=wanted:
   raise ValueError('Frozen benchmark changed: '+name)
 return manifest
def load_cases(split,acceptance=False):
 verify_freeze()
 if split=='heldout' and not acceptance:raise ValueError('Held-out cases require explicit --acceptance milestone evaluation')
 name='rolling_v2.json' if split=='rolling' and (BENCH/'rolling_v2.json').exists() else f'{split}_v1.json'
 return json.loads((BENCH/name).read_text())['cases']
def config(path=None):
 c=json.loads(Path(path).read_text()) if path else {}
 for k in ['OPENAI_API_KEY','SUPABASE_URL','SUPABASE_SECRET_KEY']:
  if os.environ.get(k):c[k]=os.environ[k]
 if c.get('SUPABASE_URL') and c['SUPABASE_URL'].rstrip('/')!='https://hofoubbmepacdljeablj.supabase.co':
  raise ValueError('Only the configured GIZ project is permitted')
 return c
