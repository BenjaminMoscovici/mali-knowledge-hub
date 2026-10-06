from copy import deepcopy
from evaluation.qualification import qualify
from evaluation.scorecard import PROTECTED


def inputs():
    def card(commit):
        c={'run_manifest':{'hub_commit':commit,'completed_at':'2026-10-05','benchmark_manifest_sha256':'fixed','suite_hash':'fixed','measurement_protocol':'paired'},
           'attempt_configuration_hash':'fixed','evaluator_configuration':{'version':'fixed'},
           'composition':{'unique_cases':1,'expected_unique_cases':1,'attempts':1},'availability':{'failures':0},'judged_attempts':1,
           'release_prerequisites':{'calibration_samples_exported':True},'findings':[],
           'analytical_dimensions':{'decision_usefulness':{'mean':5},'question_answering':{'mean':5}}}
        for name,path in PROTECTED.items():
            d=c
            for key in path[:-1]:d=d.setdefault(key,{})
            d[path[-1]]=0 if name=='grounding' else 1
        cohort={'server_success_latency_seconds':{'median':100,'p95':100},'input_tokens':{'total':100},'estimated_usd':{'total':100},'cost_unknown_attempts':0}
        c['performance_cohorts']={'cohorts':{'complex':cohort}}
        return c
    base={s:card('baseline') for s in ['frozen','rolling','heldout']};candidate={s:card('candidate') for s in base}
    co=candidate['frozen']['performance_cohorts']['cohorts']['complex']
    co['server_success_latency_seconds']={'median':70,'p95':80};co['input_tokens']['total']=70;co['estimated_usd']['total']=70
    conv={'hub_commit':'baseline','suite_sha256':'fixed','measurement_protocol':'paired','evaluator_version':'fixed','suite_sequences':24,'completed_sequences':24,'failed_attempts':0,'correct_interpretation_rate':1,'factual_grounding_proxy_rate':1,'unnecessary_clarification_rate':0}
    cc=deepcopy(conv);cc['hub_commit']='candidate'
    ground={'hub_commit':'baseline','complete':True,'suite_sha256':'fixed','coverage_adjudication_version':'1.2','evidence_packet_version':'1.1','unsupported_claim_rate':0,'citation_entailment':1}
    cg=deepcopy(ground);cg['hub_commit']='candidate'
    return base,candidate,conv,cc,ground,cg


def test_unknown_privacy_and_live_never_pass_even_with_quality_gains():
    q=qualify(*inputs())
    assert q['quality_and_performance_pass']
    assert not q['pre_deploy_qualified'] and not q['release_accepted']
    q=qualify(*inputs(),privacy={'pass':True,'project':'hofoubbmepacdljeablj','executed_at':'now','receipt_sha256':'not-a-digest'})
    assert not q['pre_deploy_qualified']


def test_unmeasured_interruption_cannot_pass_despite_complete_successful_saved_answers():
    args=inputs()
    args[1]['frozen']['run_manifest']['capture_interruption_cost_unknown']=True
    q=qualify(*args)
    assert not q['quality_and_performance_pass']
    assert 'frozen: candidate interrupted capture has unmeasured latency/cost' in q['quality_and_performance_reasons']


def test_split_missing_anchors_are_na_but_frozen_missing_measurement_rejects():
    args=inputs()
    for cards in args[:2]:
        for split in ['rolling','heldout']:
            cards[split]['deterministic_metrics']['factual_grounding']['value']=None
    q=qualify(*args)
    assert q['quality_and_performance_pass']
    assert q['protected_comparisons']['heldout']['factual_checks']['status']=='NOT_APPLICABLE_IN_THIS_SPLIT'
    args[1]['frozen']['deterministic_metrics']['factual_grounding']['value']=None
    assert not qualify(*args)['quality_and_performance_pass']


def test_same_aggregate_with_new_individual_failure_rejects():
    args=inputs();args[1]['rolling']['findings']=[{'kind':'deterministic','case_id':'X','rep':0,'finding':{'id':'money','status':'fail','dimension':'currency_preservation'}}]
    q=qualify(*args)
    assert not q['quality_and_performance_pass'] and q['new_protected_deterministic_failures']


def test_incomplete_baseline_and_changed_evaluator_reject():
    args=inputs();args[0]['frozen']['judged_attempts']=0
    assert not qualify(*args)['quality_and_performance_pass']
    args=inputs();args[1]['heldout']['evaluator_configuration']['version']='other'
    assert not qualify(*args)['quality_and_performance_pass']


def test_predeploy_and_live_acceptance_are_separate():
    privacy={'pass':True,'project':'hofoubbmepacdljeablj','executed_at':'now','receipt_sha256':'a'*64}
    q=qualify(*inputs(),privacy=privacy)
    assert q['pre_deploy_qualified'] and not q['release_accepted']
    live={'pass':True,'hub_commit':'candidate','base':'https://mali-knowledge-hub-v4-test.onrender.com','executed_at':'now'}
    assert qualify(*inputs(),privacy=privacy,live=live)['release_accepted']
    live['hub_commit']='other'
    assert not qualify(*inputs(),privacy=privacy,live=live)['release_accepted']


def test_lower_usefulness_cannot_be_averaged_away_by_protected_quality_gains():
    args=inputs();args[1]['frozen']['analytical_dimensions']['decision_usefulness']['mean']=4.99
    q=qualify(*args)
    assert not q['quality_and_performance_pass']
    assert 'frozen: decision_usefulness unknown or regressed' in q['quality_and_performance_reasons']


def test_browser_published_identity_requires_verified_source_bytes(monkeypatch):
    args=inputs()
    privacy={'pass':True,'project':'hofoubbmepacdljeablj','executed_at':'now','receipt_sha256':'a'*64}
    live={'pass':True,'hub_commit':'published','base':'https://mali-knowledge-hub-v4-test.onrender.com','executed_at':'now'}
    receipt={'synthetic_receipt_for_test':True}
    calls=[]
    def verify(measured,published,proof):
        calls.append((measured,published,proof))
        return False
    monkeypatch.setattr('evaluation.publication.verified',verify)
    assert not qualify(*args,privacy=privacy,live=live,publication=receipt)['release_accepted']
    assert calls==[('candidate','published',receipt)]
    monkeypatch.setattr('evaluation.publication.verified',lambda *a: True)
    result=qualify(*args,privacy=privacy,live=live,publication=receipt)
    assert result['release_accepted'] and result['hub_commit']=='candidate'
    assert result['live_observed_commit']=='published'
