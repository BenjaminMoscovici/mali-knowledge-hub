"""Conservative guards for incomplete evidence and fabricated evaluator quotes.

Never turn missing evaluator material into a Hub hallucination. Original judge
outputs remain immutable and reviewable; scoring keeps a separate adjustment log.
"""
import json
import re
import unicodedata

VERSION='evaluator-coverage-1.2'


def _norm(text):
 return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(text)).replace('**','').replace('`','')).strip().casefold()


def non_candidate_geography_quote(claim,packet):
 """Exclude a fabricated role quotation only with an exact fresh path witness.

 No semantic rating is overridden. A real wrong path, an uncited correct path,
 a changed name/level, or a non-registry source cannot satisfy this proof.
 """
 if claim['verdict'] not in {'unsupported','contradicted'}:return None
 answer=packet.get('answer','');text=claim['text'];quoted=_norm(text)
 if quoted in _norm(answer):return None
 unit=r'([^\n→>]+?)\s*\((country|region|cercle|commune|locality|district|arrondissement)\)'
 # Only literal administrative-unit quotations or arrow paths are in scope;
 # ordinary paraphrased factual claims retain their original judgment.
 quote_units=re.findall(unit,text,re.I)
 clean=re.sub(unit,'',text,flags=re.I)
 if not quote_units or re.sub(r'[\s→>\-.,\[\]"\']','',clean):return None
 refs=set(claim['evidence_ids']);witnesses=[]
 for e in packet.get('evidence',[]):
  if e.get('evidence_id') not in refs or e.get('source_type')!='official_geography_registry':continue
  try:data=json.loads(e.get('content',''))
  except (ValueError,TypeError):continue
  for record in data.get('records',[]):
   path=record.get('path',[])
   expected=[(_norm(p.get('name','')),str(p.get('level','')).casefold()) for p in path]
   if len(expected)<3:continue
   for line in answer.splitlines():
    if '['+e['evidence_id']+']' not in line:continue
    observed=[(_norm(name).lstrip('- '),level.casefold()) for name,level in re.findall(unit,line,re.I)]
    if observed!=expected:continue
    # A contradictory role phrase elsewhere in the answer is still a Hub
    # failure. Only the demonstrably absent quotation can be excluded.
    if any(re.search(r'\b'+re.escape(name.strip())+r'\s+(?:is|est)\s+(?:an?\s+|une?\s+)?'+re.escape(level)+r'\b',answer,re.I)
           for name,level in quote_units):continue
    if all((_norm(name).lstrip('- '),level.casefold()) in expected for name,level in quote_units):continue
    witnesses.append({'evidence_id':e['evidence_id'],'record_id':record.get('id'),
                      'version':record.get('version') or e.get('version'),
                      'correct_candidate_path':expected})
 return witnesses or None


def claims_with_coverage(judgment,packet,record=None):
 withheld=set(packet.get('withheld_evidence_ids',[]));claims=[];adjustments=[]
 for index,original in enumerate(judgment['result']['claims']):
  c=dict(original);refs=set(c['evidence_ids'])
  witnesses=non_candidate_geography_quote(c,packet)
  if witnesses:
   adjustments.append({'claim_index':index,'original_verdict':original['verdict'],
    'measurement_verdict':'excluded_non_candidate_claim',
    'reason':'The returned administrative-role quotation is absent from the candidate answer; its actual cited path exactly matches the current official registry evidence.',
    'witnesses':witnesses})
   continue
  missing=bool(refs and refs<=withheld)
  if refs&withheld and c['verdict'] in {'unsupported','contradicted'}:missing=True
  reason='Cited evidence withheld from evaluator; this is unknown, not a measured Hub error.'
  # The initial public adapter omitted retrieval metadata. A judge cannot
  # adjudicate specific retrieval dates against content alone. Preserve its
  # original verdict and expose the measurement gap separately.
  if record and c['verdict']=='unsupported' and any(w in c['text'].lower() for w in ['retriev','consult']):
   originals={e['evidence_id']:e for e in record['response'].get('evidence',[])}
   exported={e['evidence_id']:e for e in packet.get('evidence',[])}
   if any(originals.get(i,{}).get('retrieved_at') and not exported.get(i,{}).get('retrieved_at') for i in refs):
    missing=True;reason='Retrieval metadata available in Hub evidence but omitted from evaluator packet; date claim unassessable by this judge.'
  if missing:
   c['verdict']='unassessable';c['citation_supported']=None
   if c!=original:adjustments.append({'claim_index':index,'original_verdict':original['verdict'],
    'measurement_verdict':'unassessable','reason':reason})
  claims.append(c)
 return claims,adjustments
