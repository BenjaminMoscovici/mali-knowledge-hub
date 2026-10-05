import copy
import unittest
from evaluation.radar import AXES, scores, gates, comparable, svg, combine


class RadarTests(unittest.TestCase):
    def metrics(self):
        keys=['grounding','citation_ids','citation_entailment','geography','geographic_quality',
              'family_recall','completeness','usefulness','clarity','inference','route_efficiency',
              'call_efficiency','correct_interpretation_rate','factual_grounding_proxy_rate',
              'joined_cross_source_synthesis','joined_inference_discipline','joined_evidence_gap_handling']
        return dict.fromkeys(keys,1) | {'unsupported_claim_rate':0,'unnecessary_clarification_rate':0,
            'complex_latency':{'median':5,'p95':15},'complex_priced':True,'complex_median_usd':.003,'complex_usefulness':.9}

    def test_fixed_reference_and_missing_components_not_redistributed(self):
        value=self.metrics()
        self.assertEqual(list(scores(value)),AXES)
        self.assertTrue(all(v==100 for v in scores(value).values()))
        value['citation_entailment']=None
        value['unnecessary_clarification_rate']=None
        value['complex_priced']=False
        result=scores(value)
        for axis in ['Evidence accuracy','Conversational ability','Cost efficiency']:
            self.assertIsNone(result[axis])
        self.assertEqual(result['Geographic intelligence'],100)

    def test_radar_cannot_hide_failed_citations_or_unknown_privacy(self):
        card={'deterministic_metrics':{'citation_validity':{'value':.99},'factual_grounding':{'value':.9,'fail':1}}}
        result=gates(card)
        self.assertEqual(result['citation_validity']['status'],'FAIL')
        self.assertEqual(result['factual_grounding_checks']['status'],'FAIL')
        self.assertEqual(result['privacy_audit_pass']['status'],'UNKNOWN')
        self.assertIsNone(result['privacy_audit_pass']['value'])

    def test_incompatible_historical_configuration_not_overlaid(self):
        card={'split':'frozen','attempt_configuration_hash':'a','evaluator_configuration':{'model':'m'},
              'run_manifest':{'benchmark_manifest_sha256':'b','suite_hash':'s'}}
        self.assertTrue(comparable(card,copy.deepcopy(card)))
        different=copy.deepcopy(card);different['evaluator_configuration']['model']='another'
        self.assertFalse(comparable(card,different))
        self.assertFalse(comparable({},{}))

    def test_small_protected_regression_is_not_averaged_away(self):
        live={'split':'frozen','attempt_configuration_hash':'a','evaluator_configuration':{'model':'m'},
              'run_manifest':{'benchmark_manifest_sha256':'b','suite_hash':'s'},
              'citation_entailment':{'value':.99}}
        candidate=copy.deepcopy(live);candidate['citation_entailment']['value']=.98
        self.assertEqual(gates(candidate,live)['citation_entailment']['status'],'REGRESSION')

    def test_missing_axis_breaks_polygon_and_is_explicit(self):
        values=dict.fromkeys(AXES,100);values['Conversational ability']=None
        result=svg([{'label':'V4','scores':values}])
        self.assertIn('unavailable: Conversational ability',result)
        self.assertNotIn('fill-opacity=',result)
        self.assertIn('Missing ≠ zero',result)

    def test_cost_and_latency_degradation_cannot_raise_scores(self):
        value=self.metrics();before=scores(value)
        value['complex_latency']={'median':10,'p95':30};value['complex_median_usd']=.006
        after=scores(value)
        self.assertEqual(after['Cost efficiency'],50)
        self.assertLess(after['Performance'],before['Performance'])
        self.assertIsNone(combine([1,None]))
