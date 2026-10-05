"""Export Publisher review samples; import real human ratings without inventing them."""
import argparse,csv,json,statistics
from pathlib import Path
from .common import now,write_json
from .judge import DIMENSIONS

SAMPLES=['JOIN01','JOIN02','FUND04','FUND09','GEO05','GEO11','LEGACY-J04','NEED03','LEARN01','ADV02']
def export(run):
 root=Path(run);samples=[]
 for cid in SAMPLES:
  r=json.loads((root/'raw'/f'{cid}--0.json').read_text());jp=root/'judgments'/f'{cid}--0.json'
  if not jp.exists():raise ValueError('Wait for all ten sampled judgments before export')
  j=json.loads(jp.read_text());samples.append({'case_id':cid,'response_hash':r['response_hash'],
   'question':r['request_payload']['question'],'answer':r['response']['answer'],
   'evidence':r['response'].get('evidence',[]),'judge_scores':j['result']['scores'],
   'judge_claims':j['result']['claims'],'judge_findings':j['result']['findings']})
 write_json(root/'calibration_samples.json',{'created_at':now(),'status':'AWAITING_REAL_PUBLISHER_REVIEW','samples':samples})
 with (root/'publisher_ratings.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['case_id','response_hash']+DIMENSIONS+['notes']);w.writeheader()
  for s in samples:w.writerow({'case_id':s['case_id'],'response_hash':s['response_hash']})
 return {'samples':len(samples),'human_calibrated':False}

def import_ratings(run,ratings):
 root=Path(run);samples={s['case_id']:s for s in json.loads((root/'calibration_samples.json').read_text())['samples']}
 errors={d:[] for d in DIMENSIONS};seen=set()
 with Path(ratings).open(newline='') as f:
  for row in csv.DictReader(f):
   s=samples[row['case_id']]
   if row['case_id'] in seen:raise ValueError('Duplicate review case')
   seen.add(row['case_id'])
   if row['response_hash']!=s['response_hash']:raise ValueError('Human rating answer hash mismatch')
   for d in DIMENSIONS:
    if row[d] not in {'1','2','3','4','5','NA'}:raise ValueError('Complete each human score 1–5 or NA')
    if row[d]!='NA' and s['judge_scores'][d] is not None:errors[d].append(abs(int(row[d])-s['judge_scores'][d]))
 if seen!=set(samples):raise ValueError('All ten Publisher cases must be reviewed')
 result={'at':now(),'human_review_received':True,'samples':len(seen),
  'dimensions':{d:{'n':len(v),'mean_absolute_error':statistics.mean(v) if v else None,
   'within_one_point_fraction':sum(x<=1 for x in v)/len(v) if v else None} for d,v in errors.items()},
  'human_calibrated':None,'policy':'Publisher must review disagreement patterns and explicitly qualify evaluator. Received ratings alone do not establish calibrated release acceptance.'}
 write_json(root/'calibration_result.json',result);return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--ratings');a=p.parse_args()
 print(json.dumps(import_ratings(a.run,a.ratings) if a.ratings else export(a.run)))
