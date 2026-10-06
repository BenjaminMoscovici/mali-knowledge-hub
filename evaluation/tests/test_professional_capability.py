import copy
import unittest
import tempfile
from evaluation.common import digest
from evaluation.radar import AXES
from evaluation.professional_capability import requirements, scores, match, present, professional_inputs, VERSION


class ProfessionalCapabilityTests(unittest.TestCase):
    def extra(self, coverage=1):
        return {'coverage': {'layers': dict.fromkeys(requirements()['layers'], coverage)},
                'conversation_coverage': coverage, 'assessable_fraction': 1, 'availability': 1,
                'performance_cells': {f'{mode}/{state}': {'attempts': 3, 'client_median_seconds': 1,
                                                       'success_rate': 1}
                                      for mode in ['quick','balanced','deep'] for state in ['cold','warm']}}

    def test_frozen_criteria_coverage_and_no_manual_grades(self):
        spec=requirements()
        self.assertEqual(len(spec['evidence_requirements']),20)
        for layer in spec['layers']:
            self.assertEqual(sum(r['layer']==layer for r in spec['evidence_requirements']),2)
        self.assertEqual(set(spec['axes']),set(['Evidence reliability & completeness' if a == 'Evidence accuracy' else a for a in AXES]))
        self.assertFalse(present(False))

    def test_missing_delivery_funding_results_reduce_capability_even_if_correct(self):
        quality=dict.fromkeys(AXES,100);extra=self.extra()
        measured={'route_efficiency':1,'call_efficiency':1}
        before,_=scores(quality,measured,extra)
        for layer in ['delivery','funding','results']:extra['coverage']['layers'][layer]=0
        after,_=scores(quality,measured,extra)
        self.assertEqual(before['Joined analysis'],100)
        self.assertEqual(after['Joined analysis'],70)
        self.assertEqual(after['Source coverage'],70)

    def test_unassessable_claims_and_missing_quality_never_earn_full_credit(self):
        quality=dict.fromkeys(AXES,100);extra=self.extra(.5)
        extra['assessable_fraction']=.8
        result,_=scores(quality,{'route_efficiency':1,'call_efficiency':1},extra)
        self.assertEqual(result['Evidence reliability & completeness'],40)
        quality['Evidence accuracy']=None
        self.assertIsNone(scores(quality,{},extra)[0]['Evidence reliability & completeness'])

    def test_low_cost_cannot_hide_poor_professional_usefulness(self):
        quality=dict.fromkeys(AXES,100);quality['Analytical usefulness']=30
        result,_=scores(quality,{'route_efficiency':1,'call_efficiency':1},self.extra(.5))
        self.assertEqual(result['Cost efficiency'],15)

    def test_missing_cold_warm_measurement_is_unavailable_not_inferred(self):
        extra=self.extra();extra['performance_cells']['quick/cold']['attempts']=0
        self.assertIsNone(scores(dict.fromkeys(AXES,100),{},extra)[0]['Performance'])

    def test_interrupted_run_and_unknown_latency_are_unavailable_even_with_six_cells(self):
        quality=dict.fromkeys(AXES,100);extra=self.extra()
        measured={'route_efficiency':1,'call_efficiency':1,'performance_measurement_complete':False}
        self.assertIsNone(scores(quality,measured,extra)[0]['Performance'])
        measured['performance_measurement_complete']=True
        extra['performance_cells']['deep/cold']['client_median_seconds']=None
        self.assertIsNone(scores(quality,measured,extra)[0]['Performance'])

    def test_programming_prose_and_presence_never_satisfy_delivery(self):
        criterion=next(r for r in requirements()['evidence_requirements'] if r['id']=='delivery.reach')
        selector=criterion['selectors'][0]
        row={'source_type':'operational_presence','id':'a','locator':'row 1',
             'payload':{'reached':None,'limitations':'No verified delivery'}}
        self.assertFalse(match(row,selector))
        row['source_type']='delivery_observation';row['payload']['reached']=True
        self.assertFalse(match(row,selector))

    def test_availability_penalty_and_missing_inventory_are_visible(self):
        extra=self.extra();extra['availability']=.8
        result,_=scores(dict.fromkeys(AXES,100),{'route_efficiency':1,'call_efficiency':1},extra)
        self.assertEqual(result['Evidence reliability & completeness'],80)
        extra['coverage']={'status':'UNAVAILABLE'}
        result,_=scores(dict.fromkeys(AXES,100),{},extra)
        self.assertIsNone(result['Joined analysis'])

    def test_aggregate_only_regeneration_requires_bound_original_provenance(self):
        card={'run_manifest':{'hub_commit':'a'*40}}
        extra=self.extra(.4)
        extra['coverage'].update(version=VERSION,scorecard_sha256=digest(card),
                                 requirements_sha256=digest(requirements()),hub_commit='a'*40)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(professional_inputs(card,tmp,{'professional_capability':extra}),extra)
            corrupted=copy.deepcopy(extra);corrupted['coverage']['scorecard_sha256']='tampered'
            with self.assertRaises(ValueError):professional_inputs(card,tmp,{'professional_capability':corrupted})
            self.assertEqual(professional_inputs(card,tmp,{})['coverage']['status'],'UNAVAILABLE')
