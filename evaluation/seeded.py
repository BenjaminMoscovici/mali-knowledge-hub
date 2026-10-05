"""Blinded controlled factual-error packets plus matched correct controls."""
import argparse,json
from pathlib import Path
from .common import config,write_json,digest,now
from .judge import evaluate

SEEDS=[
 ('wrong_number','INSTAT 2023 hierarchy contains 159 cercles.','Mali has 999 cercles. [E01]','The INSTAT 2023 hierarchy contains 159 cercles. [E01]'),
 ('wrong_date','IOM DTM Round 83 reports September 2025 displacement stocks.','Round 83 measured displacement stocks in September 2026. [E01]','Round 83 reports September 2025 stocks, not a fresh 2026 count. [E01]'),
 ('wrong_place','Socoura commune is under Mopti cercle in Mopti region.','Socoura commune belongs to Gao region. [E01]','Socoura commune belongs to Mopti cercle in Mopti region. [E01]'),
 ('wrong_organisation','Mali 3W Q1 2026 is published by OCHA Mali.','IOM published the OCHA Mali 3W Q1 2026 dataset. [E01]','OCHA Mali published Mali 3W Q1 2026. [E01]'),
 ('wrong_level','Bandiagara REGION has a 2023 DNP population projection of 1,270,224; Bandiagara CERCLE projection is 230,093.','Bandiagara cercle has a 2023 projected population of 1,270,224. [E01]','The 2023 projection is 1,270,224 for Bandiagara region and 230,093 for Bandiagara cercle. [E01]'),
 ('unsupported_causality','FONGIM registry records project presence and sectors in Mopti; no impact evaluation is supplied.','FONGIM projects caused a 50% reduction in poverty in Mopti. [E01]','The registry establishes recorded presence; no poverty impact can be established from this evidence. [E01]'),
 ('fabricated_attribution','The only supplied item E01 describes INSTAT administrative units. No evaluation is supplied.','An IEG evaluation proves all Mali projects succeeded. [E77]','The supplied administrative item does not establish project success or contain an IEG evaluation. [E01]'),
 ('wrong_quotation','Original source quotation: "Recorded presence does not demonstrate delivery."','The source says: "Recorded presence confirms delivery." [E01]','The source says: "Recorded presence does not demonstrate delivery." [E01]'),
 ('wrong_funding_semantics','ECHO HIP 2026 lists EUR32 million as an indicative Mali allocation; disbursements and results are not reported.','ECHO disbursed EUR32 million to beneficiaries in Mopti in 2026. [E01]','EUR32 million is an indicative national allocation; local disbursement is not established. [E01]')]

def run(out,key):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 catalog=[{'type':kind,'source':source,'bad':bad,'control':good} for kind,source,bad,good in SEEDS]
 write_json(out/'seed_catalog.json',{'version':'1.0','frozen_before_evaluation':now(),'sha256':digest(catalog),'cases':catalog})
 results=[]
 for kind,source,bad,good in SEEDS:
  for label,answer in [('seeded',bad),('control',good)]:
   path=out/f'{kind}-{label}.json'
   if path.exists():r=json.loads(path.read_text())
   else:
    p={'question':'Verify this answer against the supplied source, correcting unsupported claims in your findings.',
     'language':'en','answer':answer,'evidence':[{'evidence_id':'E01','content':source}],
     'expected_behavior':['Assess source support; do not assume the claim is either correct or incorrect.']}
    verdict,receipt=evaluate(p,key)
    r={'kind':kind,'label':label,'result':verdict,'receipt':receipt,'packet_hash':digest(p)};write_json(path,r)
   wrong=any(c['verdict'] in {'unsupported','contradicted'} for c in r['result']['claims'])
   results.append({'kind':kind,'label':label,'flagged':wrong})
   print(json.dumps(results[-1]),flush=True)
 seeded=[r for r in results if r['label']=='seeded'];clean=[r for r in results if r['label']=='control']
 summary={'seeded_error_catch_rate':sum(r['flagged'] for r in seeded)/len(seeded),
  'control_false_positive_rate':sum(r['flagged'] for r in clean)/len(clean),
  'seeded_n':len(seeded),'control_n':len(clean),'scope':'Controlled evaluator verification tests, not measured production verifier catch rate.',
  'evaluator_cost_usd':sum(json.loads(p.read_text())['receipt']['estimated_usd'] or 0 for p in out.glob('*-seeded.json'))+sum(json.loads(p.read_text())['receipt']['estimated_usd'] or 0 for p in out.glob('*-control.json')),
  'results':results};write_json(out/'summary.json',summary);return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(run(a.output,config(a.config)['OPENAI_API_KEY'])))
