"""Conservative measurement guard for evaluator evidence withheld by privacy policy.

Never turn missing evaluator material into a Hub hallucination. Original judge
outputs remain immutable and reviewable; scoring keeps a separate adjustment log.
"""
VERSION='evaluator-coverage-1.1'
def claims_with_coverage(judgment,packet,record=None):
 withheld=set(packet.get('withheld_evidence_ids',[]));claims=[];adjustments=[]
 for index,original in enumerate(judgment['result']['claims']):
  c=dict(original);refs=set(c['evidence_ids'])
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
