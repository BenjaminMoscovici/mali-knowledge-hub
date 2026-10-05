import copy
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from evaluation.common import load_cases,verify_freeze
from evaluation.runner import request_case,capture_telemetry
from evaluation.validators import contains_number,validate
from evaluation.scorecard import percentile,compare

class FrameworkTests(unittest.TestCase):
 def test_frozen_composition_and_legacy_preservation(self):
  cases=load_cases('frozen');self.assertEqual(len(cases),75)
  self.assertEqual(sum(c['language']=='fr' for c in cases),22)
  from evaluation.common import ROOT
  for c in cases:
   if c['legacy_reference']:
    ref=c['legacy_reference'];original=next(x for x in json.loads((ROOT/ref['file']).read_text())['cases'] if x['id']==ref['id'])
    self.assertEqual(c['question'],original['question']);self.assertEqual(c['expected_behavior'],original['checks'])
  verify_freeze()
 def test_heldout_requires_explicit_milestone(self):
  with self.assertRaises(ValueError):load_cases('heldout')
  self.assertEqual(len(load_cases('heldout',True)),18)
 def test_expectations_never_enter_hub_request(self):
  class Response:
   status=200
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self):return b'{"answer":"Hello","evidence":[],"metrics":{}}'
  case=load_cases('frozen')[0]
  with patch('urllib.request.urlopen',return_value=Response()) as call:
   record=request_case(case)
   payload=json.loads(call.call_args.args[0].data)
  self.assertEqual(set(payload),{'question','analysis_mode','prior_messages'})
  self.assertNotIn('expected_behavior',payload);self.assertTrue(record['ok'])
 def test_failed_attempt_retained_and_not_retried(self):
  import urllib.error
  with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('u',503,'x',{},None)) as call:
   record=request_case(load_cases('frozen')[0])
  self.assertFalse(record['ok']);self.assertEqual(record['http_status'],503)
  self.assertTrue(record['cost_unknown']);self.assertEqual(call.call_count,1)
 def test_missing_telemetry_not_zero(self):
  t=capture_telemetry({'response':{'answer':'x','evidence':[],'metrics':{}}})
  self.assertIsNone(t['server_seconds']);self.assertIn('source_plan',t['telemetry_missing'])
 def test_numeric_locales_and_financial_units(self):
  for value in ['1,270,224','1 270 224','1.270.224','1\u202f270\u202f224']:
   self.assertTrue(contains_number(value,1270224),value)
  self.assertTrue(contains_number('EUR151 million',151,True))
  self.assertFalse(contains_number('131,582',13582))
 def test_invalid_citation_and_bad_page_detected(self):
  case={'required_source_families':[],'deterministic_assertions':[]}
  record={'ok':True,'response':{'answer':'Fact [E99]','evidence':[{'evidence_id':'E01','source_type':'knowledge_base_document','chunk_id':7,'document_id':'doc','page':90}], 'metrics':{}}}
  checks=validate(case,record,{'7':{'document_id':'doc','page_number':9}})
  self.assertTrue(any(c['id']=='citation_ids' and c['status']=='fail' for c in checks))
  record['response']['answer']='Fact [E01]'
  checks=validate(case,record,{'7':{'document_id':'doc','page_number':9}})
  self.assertTrue(any(c['id']=='E01:chunk' and c['status']=='fail' for c in checks))
 def test_distribution_quantile(self):
  self.assertEqual(percentile([0,10],95),9.5);self.assertIsNone(percentile([],95))
 def test_regression_cannot_pass_without_quality_prerequisites(self):
  base={'run_manifest':{'benchmark_manifest_sha256':'h'},'deterministic_metrics':{'citation_validity':{'value':1}},
   'analytical_dimensions':{'geographic_discipline':{'acceptable_fraction':1},'evidence_gap_handling':{'acceptable_fraction':1}},
   'unsupported_claim_rate':{'value':.01},'citation_entailment':{'value':1},
   'composition':{'unique_cases':75,'expected_unique_cases':75},'judged_attempts':75,
   'availability':{'successes':75,'failures':0},'by_mode':{}}
  other=copy.deepcopy(base);other['unsupported_claim_rate']['value']=.08
  c=compare(base,other)
  self.assertEqual(c['decision'],'REJECT_OR_EXPERIMENTAL')
  self.assertTrue(any('grounding regressed' in r for r in c['reasons']))
  self.assertTrue(any('heldout_qualified' in r for r in c['reasons']))
 def test_unknown_protected_metric_cannot_pass(self):
  base={'run_manifest':{'benchmark_manifest_sha256':'h'},'composition':{'unique_cases':0,'expected_unique_cases':75},'availability':{'failures':0,'successes':0},'judged_attempts':0,'by_mode':{}}
  result=compare(base,base);self.assertEqual(result['decision'],'REJECT_OR_EXPERIMENTAL')
 def test_external_judge_excludes_unverified_document_and_private_history(self):
  from evaluation.public_packets import sanitize_packet
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'manifest.json';path.write_text('{"documents":[]}')
   record={'request_payload':{},'response':{'saved':False,'evidence':[{'evidence_id':'E01','chunk_id':1,'document_id':'private-unverified','source_family':'Government docs','content':'MUST NOT EXPORT'}]}}
   p=sanitize_packet({'evidence':[],'answer':'Synthetic guest answer'},record,path)
   self.assertNotIn('MUST NOT EXPORT',json.dumps(p));self.assertEqual(p['withheld_evidence_ids'],['E01'])
   record['response']['saved']=True
   with self.assertRaises(ValueError):sanitize_packet({},record,path)
 def test_log_enrichment_requires_answer_hash_and_matching_usage(self):
  from evaluation.telemetry import import_usage,enriched
  from evaluation.common import write_json
  with tempfile.TemporaryDirectory() as d:
   record={'case_id':'X','repetition':0,'response_hash':'h','response':{'metrics':{'request_id':'rid','research_api_usage':{'input_tokens':3}}},'telemetry':{'telemetry_missing':['source_plan']}}
   write_json(Path(d)/'raw'/'X--0.json',record)
   with self.assertRaises(ValueError):import_usage(d,{'records':[{'request_id':'rid','api_usage':{'input_tokens':4},'source_plan':{}}]})
   import_usage(d,{'records':[{'request_id':'rid','api_usage':{'input_tokens':3},'source_plan':{'hapi':True}}]})
   self.assertEqual(enriched(d,record)['telemetry']['source_plan'],{'hapi':True})
   self.assertNotIn('source_plan',record['telemetry'])
   record['response_hash']='changed'
   with self.assertRaises(ValueError):enriched(d,record)
 def test_withheld_evidence_is_unknown_and_original_judgment_is_retained(self):
  from evaluation.adjudication import claims_with_coverage
  j={'result':{'claims':[{'text':'x','verdict':'unsupported','evidence_ids':['E01'],'citation_supported':False}]}}
  measured,adjustments=claims_with_coverage(j,{'withheld_evidence_ids':['E01']})
  self.assertEqual(measured[0]['verdict'],'unassessable');self.assertIsNone(measured[0]['citation_supported'])
  self.assertEqual(j['result']['claims'][0]['verdict'],'unsupported');self.assertEqual(len(adjustments),1)

 def test_omitted_metadata_and_mixed_withheld_claims_remain_unknown(self):
  from evaluation.adjudication import claims_with_coverage
  claims=[{'text':'Retrieved on 5 October 2026','verdict':'unsupported','evidence_ids':['E01'],'citation_supported':False},
   {'text':'x','verdict':'contradicted','evidence_ids':['E01','E02'],'citation_supported':False}]
  j={'result':{'claims':claims}}
  p={'withheld_evidence_ids':['E02'],'evidence':[{'evidence_id':'E01'}]}
  r={'response':{'evidence':[{'evidence_id':'E01','retrieved_at':'2026-10-05'}]}}
  measured,adjustments=claims_with_coverage(j,p,r)
  self.assertEqual([c['verdict'] for c in measured],['unassessable','unassessable'])
  self.assertEqual(len(adjustments),2);self.assertEqual(claims[0]['verdict'],'unsupported')

if __name__=='__main__':unittest.main()
