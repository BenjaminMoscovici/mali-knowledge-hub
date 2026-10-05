"""External judge packets contain public guest results and public source material only.

The GIZ corpus oracle is reserved for LOCAL validation. It is never exported by
this adapter. Unknown document provenance is withheld, rather than assumed public.
"""
import json,re
from pathlib import Path
from .common import ROOT
from .validators import family_key

PUBLIC_FAMILIES={'government','hnrp','hapi','hpc','fongim','3w','dtm','ch','fts',
 'world_bank','iati','ieg','eu','geography','knowledge hub corpus inventory','knowledge hub v2 normalization method'}
FIELDS={'evidence_id','source_type','source_family','document_title','organization','version',
 'page','section','source_endpoint','reference_period_start','reference_period_end','geographic_scope','locator',
 'retrieved_at','valid_from','valid_until','publication_date','document_type'}

def approved_hub_packet(packet, record, project_url):
 """User-authorized normal synthesis evidence; never enrich from the oracle.

 This explicit mode requires the correct project and an anonymous synthetic
 record. The public-only adapter remains the default. Account histories,
 credentials and unrelated corpus material are never copied into this packet.
 """
 if project_url.rstrip('/') != 'https://hofoubbmepacdljeablj.supabase.co':
  raise ValueError('Approved evidence scope is restricted to the GIZ MKH project')
 if record['request_payload'].get('conversation_id') or record['response'].get('saved'):
  raise ValueError('Approved scoring requires anonymous synthetic benchmark records')
 result={k:v for k,v in packet.items() if k not in {'evidence','source_inventory','synthesis_selection'}}
 evidence=[]
 for item in record['response'].get('evidence',[]):
  if family_key(item) not in PUBLIC_FAMILIES:
   raise ValueError('Unregistered source family is outside approved evaluation scope')
  entry={k:v for k,v in item.items() if k in FIELDS}
  entry['content']=item.get('content') or item.get('source_excerpt','')
  entry['public_excerpt_may_be_truncated']=len(entry['content'])>=6000
  entry['evidence_provenance']='Exact evidence returned for this frozen anonymous Hub request; no oracle enrichment.'
  evidence.append(entry)
 result.update(evidence=evidence,withheld_evidence_ids=[],evidence_packet_version='approved-hub-evidence-1.0',
  privacy_scope='User-approved transfer to api.openai.com for MKH independent scoring: synthetic question, anonymous answer and its normal retrieved synthesis evidence only.')
 if re.search(r'sk-[A-Za-z0-9_-]{20,}|sb_secret_[A-Za-z0-9_-]{20,}',json.dumps(result)):
  raise ValueError('Credential-like content blocked')
 return result

def sanitize_packet(packet,record,provenance):
 if record['request_payload'].get('conversation_id') or record['response'].get('saved'):
  raise ValueError('External judge requires synthetic guest evaluation, never private conversations')
 manifest=json.loads(Path(provenance).read_text())
 public={d['document_id']:d for d in manifest['documents'] if d['status']=='verified_public_download'}
 result={k:v for k,v in packet.items() if k not in {'evidence','source_inventory','synthesis_selection'}}
 result['evidence_packet_version']='public-provenance-1.1'
 result['privacy_scope']='Synthetic benchmark; anonymous guest answers; verified public pages or registered public aggregate evidence. No GIZ oracle chunks, private conversations, credentials or account metadata.'
 evidence=[];withheld=[]
 for item in record['response'].get('evidence',[]):
  if family_key(item) not in PUBLIC_FAMILIES:raise ValueError('Unknown source family; external scoring prohibited')
  entry={k:v for k,v in item.items() if k in FIELDS}
  if item.get('chunk_id') is not None:
   did=item.get('document_id');d=public.get(did)
   if d:
    pages=Path(d['pages_file']).read_text().split('\f');n=int(item.get('page') or 1)
    entry['content']='\n'.join(pages[max(0,n-2):min(len(pages),n+1)])
    entry['source_endpoint']=d['public_url'];entry['public_pdf_sha256']=d['sha256']
    entry['public_evidence_provenance']='Downloaded anonymously from official publisher; indicated page and adjacent pages. GIZ chunk content excluded.'
   else:
    entry['content']='[Withheld: this document is not independently downloaded as public. Claims needing this evidence are unassessable.]'
    entry['public_excerpt_may_be_truncated']=True;withheld.append(item['evidence_id'])
  else:
   # These families are registered public aggregate/official sources and returned
   # by the unchanged, anonymous Hub API. No authenticated research is requested.
   entry['content']=item.get('content') or item.get('source_excerpt','')
   entry['public_evidence_provenance']='Registered public official/aggregate source, returned to anonymous guest.'
   entry['public_excerpt_may_be_truncated']=len(entry['content'])>=6000
  evidence.append(entry)
 result['evidence']=evidence;result['withheld_evidence_ids']=withheld
 serialized=json.dumps(result)
 if re.search(r'sk-[A-Za-z0-9_-]{20,}|sb_secret_[A-Za-z0-9_-]{20,}',serialized):raise ValueError('Credential-like content blocked')
 return result
