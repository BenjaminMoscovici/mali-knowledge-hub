import json
from evaluation.adjudication import claims_with_coverage


def packet(answer):
 path=[{'name':'Mali','level':'country'},{'name':'Mopti','level':'region'},
       {'name':'Konna','level':'cercle'},{'name':'Konna','level':'commune'}]
 return {'answer':answer,'evidence':[{'evidence_id':'E01','source_type':'official_geography_registry',
         'content':json.dumps({'records':[{'id':'synthetic-registry-row','version':'test-vintage','path':path}]})}]}


def test_absent_false_role_quote_requires_the_actual_cited_fresh_path():
 claim={'text':'Konna (region)','verdict':'contradicted','evidence_ids':['E01'],'citation_supported':False}
 j={'result':{'claims':[claim]}}
 answer='Mali (country) → Mopti (region) → Konna (cercle) → Konna (commune). [E01]'
 claims,changes=claims_with_coverage(j,packet(answer))
 assert claims==[] and changes[0]['measurement_verdict']=='excluded_non_candidate_claim'
 assert changes[0]['witnesses'][0]['version']=='test-vintage'
 assert j['result']['claims']==[claim]
 for wrong in [answer.replace('Mopti (region)','Konna (region)'), answer.replace('[E01]','[E02]'),
               answer.replace('Konna (cercle)','Mopti (cercle)'), answer+' Konna is a region.']:
  assert claims_with_coverage(j,packet(wrong))==([claim],[])
 p=packet(answer);p['evidence'][0]['source_type']='unverified_geography'
 assert claims_with_coverage(j,p)==([claim],[])


def test_paraphrases_and_other_facts_are_never_excluded():
 answer='Mali (country) → Mopti (region) → Konna (cercle) → Konna (commune). [E01]'
 for text in ['Konna is in the region of Konna','Konna (region) has 99 communes','Mopti (region)']:
  c={'text':text,'verdict':'unsupported','evidence_ids':['E01'],'citation_supported':False}
  assert claims_with_coverage({'result':{'claims':[c]}},packet(answer))==([c],[])
