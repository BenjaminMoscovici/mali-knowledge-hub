"""Measured distributions, protected regression gates and calibration export."""
import argparse,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
from .common import digest,load_cases,write_json,now
from .validators import validate, VERSION as VALIDATOR_VERSION
from .telemetry import enriched
from .adjudication import claims_with_coverage,VERSION as ADJUDICATION_VERSION

def percentile(values,p):
 if not values:return None
 values=sorted(values);rank=(len(values)-1)*p/100;lo=math.floor(rank);hi=math.ceil(rank)
 return values[lo]+(values[hi]-values[lo])*(rank-lo)
def distribution(values):
 return {'n':len(values),'median':statistics.median(values) if values else None,
  'p90':percentile(values,90),'p95':percentile(values,95),'max':max(values) if values else None,
  'total':sum(values) if values else None,'quantile_method':'linear interpolation (n-1)*p'}
def rate(checks,dimension):
 group=[c for c in checks if c['dimension']==dimension]
 assessed=[c for c in group if c['status'] in {'pass','fail'}]
 return {'pass':sum(c['status']=='pass' for c in assessed),'fail':sum(c['status']=='fail' for c in assessed),
  'unknown':sum(c['status']=='unknown' for c in group),'denominator':len(assessed),
  'value':sum(c['status']=='pass' for c in assessed)/len(assessed) if assessed else None}

def summarize(directory,split,oracle=None,acceptance=False,live_run=None,conversation=None,label='Current candidate'):
 out=Path(directory);cases={c['id']:c for c in load_cases(split,acceptance)}
 chunks={str(c['id']):c for c in (oracle or {}).get('chunks',[])}
 records=[enriched(out,json.loads(p.read_text())) for p in sorted((out/'raw').glob('*.json'))]
 checks=[];judges=[];by_mode=defaultdict(list);findings=[];adjusted_claims=[];coverage_adjustments=[]
 for r in records:
  c=cases[r['case_id']];validation=validate(c,r,chunks)
  write_json(out/'validation'/f"{r['case_id']}--{r['repetition']}.json",{'response_hash':r['response_hash'],'checks':validation})
  checks.extend(validation);by_mode[c['difficulty']].append(r)
  for v in validation:
   if v['status']=='fail':findings.append({'case_id':c['id'],'rep':r['repetition'],'kind':'deterministic','finding':v})
  jp=out/'judgments'/f"{r['case_id']}--{r['repetition']}.json"
  if jp.exists():
   j=json.loads(jp.read_text())
   if j['response_hash']!=r['response_hash']:raise ValueError('Judgment does not match frozen answer')
   judges.append((c,j))
   packet_path=out/'judge_packets'/f"{r['case_id']}--{r['repetition']}.json"
   packet=json.loads(packet_path.read_text()) if packet_path.exists() else {}
   measured,adjustments=claims_with_coverage(j,packet,r);adjusted_claims.extend(measured)
   coverage_adjustments.extend({'case_id':c['id'],'rep':r['repetition'],**a} for a in adjustments)
   for f in j['result']['findings']:findings.append({'case_id':c['id'],'rep':r['repetition'],'kind':'analytical','finding':f})
 modes={}
 for mode,rows in by_mode.items():
  ok=[r for r in rows if r['ok']]
  costs=[r['telemetry']['estimated_usd'] for r in ok if r['telemetry'].get('estimated_usd') is not None]
  mode_scores=[j['result']['scores']['decision_usefulness'] for c,j in judges if c['difficulty']==mode and j['result']['scores']['decision_usefulness'] is not None]
  modes[mode]={'attempts':len(rows),'successes':len(ok),'failures':len(rows)-len(ok),
   'server_latency_seconds':distribution([r['telemetry']['server_seconds'] for r in ok if r['telemetry'].get('server_seconds') is not None]),
   'client_attempt_latency_seconds':distribution([r['client_seconds'] for r in rows]),
   'cost_usd':distribution(costs),'cost_unknown_attempts':sum(not r['ok'] or bool(r['telemetry'].get('unpriced_calls')) for r in rows),
   'decision_usefulness_mean':statistics.mean(mode_scores) if mode_scores else None,
   'input_tokens':distribution([r['telemetry']['input_tokens'] for r in ok]),
   'output_tokens':distribution([r['telemetry']['output_tokens'] for r in ok]),
   'model_calls':distribution([len([c for c in r['telemetry']['model_calls'] if c.get('endpoint')=='responses']) for r in ok]),
   'embedding_calls':distribution([len([c for c in r['telemetry']['model_calls'] if c.get('endpoint')=='embeddings']) for r in ok]),
   'assembly_prompt_chars':distribution([r['telemetry']['evidence_assembly']['prompt_chars'] for r in ok if 'prompt_chars' in r['telemetry']['evidence_assembly']])}
 dimensions={}
 for dimension in ['question_answering','evidence_completeness','cross_source_synthesis','inference_discipline','evidence_gap_handling','geographic_discipline','temporal_discipline','decision_usefulness','writing_quality']:
  scores=[j['result']['scores'][dimension] for _,j in judges if j['result']['scores'][dimension] is not None]
  dimensions[dimension]={'mean':statistics.mean(scores) if scores else None,'n':len(scores),'acceptable_fraction':sum(v>=3 for v in scores)/len(scores) if scores else None}
 claims=adjusted_claims
 assessed=[c for c in claims if c['verdict']!='unassessable']
 unsupported=[c for c in assessed if c['verdict'] in {'unsupported','contradicted'}]
 cited_claims=[c for c in claims if c['evidence_ids'] and c['citation_supported'] is not None]
 french=[j for c,j in judges if c['language']=='fr']
 result={'generated_at':now(),'split':split,'run_manifest':json.loads((out/'run_manifest.json').read_text()),
  'attempt_configuration_hash':digest(sorted((r['case_id'],r['repetition']) for r in records)),
  'composition':{'unique_cases':len({r['case_id'] for r in records}),'attempts':len(records),'expected_unique_cases':len(cases),
   'categories':dict(Counter(cases[i]['category'] for i in {r['case_id'] for r in records})),
   'french_unique':sum(cases[i]['language']=='fr' for i in {r['case_id'] for r in records})},
  'availability':{'successes':sum(r['ok'] for r in records),'failures':sum(not r['ok'] for r in records)},
  'deterministic_metrics':{d:rate(checks,d) for d in set(c['dimension'] for c in checks)},
  'analytical_dimensions':dimensions,'judged_attempts':len(judges),
  'unsupported_claim_rate':{'value':len(unsupported)/len(assessed) if assessed else None,'unsupported_or_contradicted':len(unsupported),'assessed_material_claims':len(assessed),'unassessable_claims':len(claims)-len(assessed),'judge_method':'independent gpt-5-mini snapshot; uncalibrated pending Publisher review'},
  'citation_entailment':{'value':sum(c['citation_supported'] for c in cited_claims)/len(cited_claims) if cited_claims else None,'assessed_cited_claims':len(cited_claims)},
  'claim_assessment_coverage':{'value':len(assessed)/len(claims) if claims else None,'all_material_claims':len(claims)},
  'evaluator_configuration':{'models':sorted({j['receipt']['returned_model'] for _,j in judges}),
   'evidence_packet_versions':sorted({j['receipt'].get('evidence_packet_version','public-provenance-1.0') for _,j in judges}),
   'deterministic_validator_version':VALIDATOR_VERSION,
   'coverage_adjudication_version':ADJUDICATION_VERSION,
   'prompt_hashes':sorted({j['receipt']['prompt_hash'] for _,j in judges}),
   'schema_hashes':sorted({j['receipt']['schema_hash'] for _,j in judges})},
  'french':{'judged_attempts':len(french),'language_correct_fraction':sum(j['result']['language_correct'] for j in french)/len(french) if french else None,
   'writing_mean':statistics.mean(j['result']['scores']['writing_quality'] for j in french if j['result']['scores']['writing_quality'] is not None) if french else None},
  'by_mode':modes,'hub_estimated_cost_usd':sum(r['telemetry'].get('estimated_usd') or 0 for r in records),
  'hub_cost_is_lower_bound':any(not r['ok'] or r['telemetry'].get('estimated_usd') is None or r['telemetry'].get('unpriced_calls') for r in records),
  'evaluator_estimated_cost_usd':sum(j['receipt'].get('estimated_usd') or 0 for _,j in judges),
  'telemetry_missing':dict(Counter(k for r in records for k in r['telemetry']['telemetry_missing'])),
  'limitations':['Success-only server latency has an explicitly reported availability denominator; all attempted client times are retained.',
   'Required-family presence is a retrieval proxy, not complete queried-family routing accuracy.',
   'External packet scope is versioned in evaluator_configuration. Public-only mode withholds unverified documents; explicitly approved Hub mode uses only the anonymous answer and its normal retrieved evidence. GIZ oracle enrichment remains local only.',
   'Source locator checks report unresolvable dynamic records as unknown, not pass.',
   'Analytical scores and atomic claim labels need human calibration; privacy cross-user testing is a separate live prerequisite.',
   'Reported costs use actual provider tokens and application meter; not invoices. Failure cost can remain unknown.'],
  'coverage_adjustments':coverage_adjustments,'findings':findings}
 from .cohorts import summarize as summarize_cohorts
 result['performance_cohorts'] = summarize_cohorts(records, cases, judges)
 from .judge_integrity import inspect as inspect_judge_integrity
 result['judge_quote_integrity'] = inspect_judge_integrity(out)
 from .calibration import export, SAMPLES
 review_ready=all((out/'raw'/f'{cid}--0.json').exists() and (out/'judgments'/f'{cid}--0.json').exists() for cid in SAMPLES)
 if split=='frozen' and review_ready:export(out)
 result['release_prerequisites']={'calibration_samples_exported':bool(split=='frozen' and review_ready),
   'human_calibrated':None}
 write_json(out/'scorecard.json',result)
 # Every benchmark scorecard emits the six release-summary artifacts. The
 # radar reads the scorecard; it cannot change quality metrics or acceptance.
 from .radar import generate
 generate(out,label=label,live=live_run,conversation=conversation)
 return result

PROTECTED={'factual_checks':('deterministic_metrics','factual_grounding','value'),
 'geographic_checks':('deterministic_metrics','geographic_discipline','value'),
 'temporal_checks':('deterministic_metrics','temporal_discipline','value'),
 'currency_preservation':('deterministic_metrics','currency_preservation','value'),
 'citation_validity':('deterministic_metrics','citation_validity','value'),
 'geography':('analytical_dimensions','geographic_discipline','acceptable_fraction'),
 'evidence_gap':('analytical_dimensions','evidence_gap_handling','acceptable_fraction'),
 'grounding':('unsupported_claim_rate','value'),'citation_entailment':('citation_entailment','value'),
 'claim_coverage':('claim_assessment_coverage','value')}
def compare(live,candidate,tolerance=0):
 changes={};reasons=[]
 if live['run_manifest'].get('measurement_protocol','guest-api-v1')!=candidate['run_manifest'].get('measurement_protocol','guest-api-v1'):
  reasons.append('Measurement protocols differ; latency and cost require a paired run')
 if live['run_manifest']['benchmark_manifest_sha256']!=candidate['run_manifest']['benchmark_manifest_sha256']:
  reasons.append('Benchmark hashes differ; not a valid regression comparison')
 if not live.get('evaluator_configuration') or live.get('evaluator_configuration')!=candidate.get('evaluator_configuration'):
  reasons.append('Missing or different evaluator configuration; paired scoring required')
 if live['composition'].get('attempts')!=candidate['composition'].get('attempts'):
  reasons.append('Attempt counts differ; use matching cases and repetitions')
 for field in ['suite_hash']:
  if live['run_manifest'].get(field)!=candidate['run_manifest'].get(field):
   reasons.append(field+' differs; use matching suite and repetition configuration')
 if live.get('split')!=candidate.get('split'):
  reasons.append('Different benchmark splits; comparison invalid')
 if not live.get('attempt_configuration_hash') or live.get('attempt_configuration_hash')!=candidate.get('attempt_configuration_hash'):
  reasons.append('Missing or different case/repetition configuration; paired attempts required')
 for name,path in PROTECTED.items():
  def get(o):
   for key in path:o=o.get(key) if isinstance(o,dict) else None
   return o
  a,b=get(live),get(candidate)
  loss=None if a is None or b is None else (b-a if name=='grounding' else a-b)
  changes[name]={'live':a,'candidate':b,'regression':loss}
  if loss is None:reasons.append(name+' not measured')
  elif loss>tolerance+1e-12:reasons.append(name+' regressed beyond the protected tolerance')
 def deterministic_failures(card):
  protected={'factual_grounding','geographic_discipline','temporal_discipline','citation_validity','currency_preservation'}
  return {(f['case_id'],f.get('rep',0),f['finding']['id']) for f in card.get('findings',[])
          if f.get('kind')=='deterministic' and f['finding'].get('status')=='fail'
          and f['finding'].get('dimension') in protected}
 new_failures=sorted(deterministic_failures(candidate)-deterministic_failures(live))
 if new_failures:reasons.append('New protected deterministic failures: '+str(new_failures))
 if candidate['composition']['unique_cases']!=candidate['composition']['expected_unique_cases']:reasons.append('Incomplete candidate frozen suite')
 if candidate['judged_attempts']<candidate['availability']['successes']:reasons.append('Incomplete analytical judging')
 if candidate['availability']['failures']:reasons.append('Candidate request failures require review')
 # Acceptance requires attached held-out, smoke and privacy evidence, never inferred from soft scores.
 # ToR §19 requires a representative human-review pack at milestones, not
 # recurring Publisher authorization for normal candidate decisions. The
 # actual calibration status stays explicit; never infer human ratings.
 for required in ['heldout_qualified','live_smoke_pass','privacy_audit_pass','calibration_samples_exported','target_improvement_verified']:
  if candidate.get('release_prerequisites',{}).get(required) is not True:reasons.append(required+' not established')
 return {'decision':'REJECT_OR_EXPERIMENTAL' if reasons else 'ACCEPT','protected_tolerance':tolerance,'changes':changes,'reasons':reasons,
  'human_calibration_status':candidate.get('release_prerequisites',{}).get('human_calibrated'),
  'new_protected_deterministic_failures':new_failures,
  'evaluation_caveat':'Independent analytical ratings remain provisional until real human calibration; review disagreements without inventing ratings.',
  'soft_comparison':{'live_by_mode':live['by_mode'],'candidate_by_mode':candidate['by_mode']}}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run');p.add_argument('--split',default='frozen');p.add_argument('--oracle');p.add_argument('--acceptance',action='store_true');p.add_argument('--live');p.add_argument('--candidate');p.add_argument('--output');p.add_argument('--live-run');p.add_argument('--conversation');p.add_argument('--label',default='Current candidate');a=p.parse_args()
 if a.live and a.candidate:
  result=compare(json.loads(Path(a.live).read_text()),json.loads(Path(a.candidate).read_text()));write_json(a.output,result)
 else:result=summarize(a.run,a.split,json.loads(Path(a.oracle).read_text()) if a.oracle else None,a.acceptance,a.live_run,json.loads(Path(a.conversation).read_text()) if a.conversation else None,a.label)
 print(json.dumps({k:result.get(k) for k in ['composition','availability','unsupported_claim_rate','decision','by_mode']},ensure_ascii=False))
