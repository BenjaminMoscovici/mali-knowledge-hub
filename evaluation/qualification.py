"""Whole-milestone qualification with separate pre-deploy and live gates.

Deterministic anchors absent from a split are reported as not applicable there;
the frozen suite must still measure every protected dimension. Unknown evidence
or absent privacy/live receipts never becomes a gate pass.
"""
import argparse
import json
import re
from pathlib import Path
from .common import now,write_json
from .scorecard import PROTECTED


def value(card,path):
    for key in path:
        card=card.get(key) if isinstance(card,dict) else None
    return card


def qualify(baseline,candidate,base_conversation=None,conversation=None,base_grounding=None,grounding=None,privacy=None,live=None):
    reasons=[];comparisons={};new_failures=[]
    commits={c['run_manifest']['hub_commit'] for c in candidate.values()}
    if len(commits)!=1:reasons.append('Mixed candidate commits')
    commit=next(iter(commits)) if len(commits)==1 else None
    for split in ['frozen','rolling','heldout']:
        a=baseline.get(split);b=candidate.get(split)
        if not a or not b:reasons.append(split+' missing');continue
        for field in ['benchmark_manifest_sha256','suite_hash','measurement_protocol']:
            if a['run_manifest'].get(field)!=b['run_manifest'].get(field):reasons.append(split+': '+field+' differs')
        if a['attempt_configuration_hash']!=b['attempt_configuration_hash']:reasons.append(split+': attempt configuration differs')
        if a['evaluator_configuration']!=b['evaluator_configuration']:reasons.append(split+': evaluator configuration differs')
        for label,card in [('baseline',a),('candidate',b)]:
            if not card['run_manifest'].get('completed_at') or card['composition']['unique_cases']!=card['composition']['expected_unique_cases']:
                reasons.append(split+': '+label+' incomplete capture')
            if card['availability']['failures'] or card['judged_attempts']!=card['composition']['attempts']:
                reasons.append(split+': '+label+' failed or unjudged attempts')
        changes={}
        for name,path in PROTECTED.items():
            av,bv=value(a,path),value(b,path)
            if av is None and bv is None and split!='frozen' and path[0]=='deterministic_metrics':
                changes[name]={'status':'NOT_APPLICABLE_IN_THIS_SPLIT','baseline':None,'candidate':None}
                continue
            delta=None if av is None or bv is None else (bv-av if name=='grounding' else av-bv)
            changes[name]={'status':'UNKNOWN' if delta is None else 'FAIL' if delta>1e-12 else 'PASS',
                           'baseline':av,'candidate':bv,'regression':delta}
            if delta is None:reasons.append(split+': '+name+' not measured')
            elif delta>1e-12:reasons.append(split+': '+name+' regressed')
        def failures(c):
            return {(f['case_id'],f.get('rep',0),f['finding']['id']) for f in c.get('findings',[])
                    if f.get('kind')=='deterministic' and f['finding'].get('status')=='fail'
                    and f['finding'].get('dimension') in {'factual_grounding','geographic_discipline','temporal_discipline','citation_validity','currency_preservation'}}
        added=sorted(failures(b)-failures(a));new_failures.extend({'split':split,'attempt':x} for x in added)
        if added:reasons.append(split+': new protected deterministic failures')
        comparisons[split]=changes
    conversation_checks={}
    if not base_conversation or not conversation:reasons.append('Complete paired conversation scorecards missing')
    else:
        if conversation['hub_commit']!=commit:reasons.append('Conversation candidate commit differs')
        for key in ['suite_sha256','measurement_protocol','evaluator_version']:
            if base_conversation.get(key)!=conversation.get(key):reasons.append('Conversation '+key+' differs')
        for label,card in [('baseline',base_conversation),('candidate',conversation)]:
            if card.get('suite_sequences',0)<20 or card.get('completed_sequences')!=card.get('suite_sequences') or card.get('failed_attempts'):
                reasons.append('Conversation '+label+' suite incomplete or failed')
        for key in ['correct_interpretation_rate','factual_grounding_proxy_rate','unnecessary_clarification_rate']:
            av,bv=base_conversation[key],conversation[key]
            loss=bv-av if key=='unnecessary_clarification_rate' else av-bv
            conversation_checks[key]={'baseline':av,'candidate':bv,'regression':loss}
            if loss>1e-12:reasons.append('Conversation '+key+' regressed')
    if not base_grounding or not grounding or not base_grounding.get('complete') or not grounding.get('complete'):
        reasons.append('Independent factual follow-up qualification incomplete')
    else:
        if grounding['hub_commit']!=commit:reasons.append('Factual follow-up commit differs')
        for key in ['suite_sha256','coverage_adjudication_version','evidence_packet_version']:
            if not grounding.get(key) or base_grounding.get(key)!=grounding[key]:reasons.append('Factual follow-up '+key+' missing or different')
        for key in ['unsupported_claim_rate','citation_entailment']:
            av,bv=base_grounding[key],grounding[key]
            loss=None if av is None or bv is None else bv-av if key=='unsupported_claim_rate' else av-bv
            conversation_checks['independent_'+key]={'baseline':av,'candidate':bv,'regression':loss}
            if loss is None or loss>1e-12:reasons.append('Independent follow-up '+key+' unknown or regressed')
    frozen=candidate.get('frozen',{});pack=frozen.get('release_prerequisites',{}).get('calibration_samples_exported') is True
    if not pack:reasons.append('Ten-answer calibration review pack not exported')
    # Fixed material-improvement targets for the next complete qualification.
    targets={};a=baseline.get('frozen',{}).get('performance_cohorts',{}).get('cohorts',{}).get('complex');b=frozen.get('performance_cohorts',{}).get('cohorts',{}).get('complex')
    if not a or not b:reasons.append('Expected-complex performance cohort missing')
    else:
        for key,field,measure,minimum in [('complex_median','server_success_latency_seconds','median',.20),
                                         ('complex_input_tokens','input_tokens','total',.15),
                                         ('complex_estimated_cost','estimated_usd','total',.10)]:
            av,bv=a[field][measure],b[field][measure];gain=1-bv/av if av else None
            targets[key]={'baseline':av,'candidate':bv,'improvement_fraction':gain,'required_fraction':minimum,'pass':gain is not None and gain>=minimum}
            if not targets[key]['pass']:reasons.append(key+' material improvement target not met')
        p95_ok=b['server_success_latency_seconds']['p95']<=a['server_success_latency_seconds']['p95']
        targets['complex_p95']={'baseline':a['server_success_latency_seconds']['p95'],'candidate':b['server_success_latency_seconds']['p95'],'pass':p95_ok}
        if not p95_ok:reasons.append('Complex P95 regressed')
        if b['cost_unknown_attempts']:reasons.append('Complex cost incomplete')
    quality_pass=not reasons
    privacy_pass=bool(privacy and privacy.get('pass') is True and privacy.get('project')=='hofoubbmepacdljeablj'
                      and privacy.get('executed_at') and re.fullmatch(r'[0-9a-f]{64}',str(privacy.get('receipt_sha256',''))))
    live_pass=bool(live and live.get('pass') is True and live.get('hub_commit')==commit
                   and live.get('base')=='https://mali-knowledge-hub-v4-test.onrender.com' and live.get('executed_at'))
    return {'version':'whole-milestone-qualification-1.0','generated_at':now(),'hub_commit':commit,
            'quality_and_performance_pass':quality_pass,'quality_and_performance_reasons':reasons,
            'protected_tolerance':0,'protected_comparisons':comparisons,'new_protected_deterministic_failures':new_failures,
            'conversation_comparisons':conversation_checks,'material_improvement_targets':targets,
            'prerequisites':{'heldout_qualified':quality_pass,'calibration_samples_exported':pack,
                             'privacy_audit_pass':privacy_pass,'live_smoke_pass':live_pass,'human_calibrated':None},
            'pre_deploy_qualified':quality_pass and privacy_pass,'release_accepted':quality_pass and privacy_pass and live_pass,
            'limitations':['Unknown privacy or absent live receipts never passes. Live candidate verification follows gated deployment; the accepted baseline remains the rollback target.',
                           'Independent model judgments remain provisional pending real human calibration; original outputs and proof-bound measurement adjustments remain reviewable.',
                           'Material targets are 20% complex median, 15% input and 10% estimated cost reduction, with no complex P95 increase; provider estimates are not invoices.',
                           'A missing deterministic anchor family in rolling/held-out is not an invented score; that dimension must still be measured by the frozen suite and analytical protected dimensions apply in every split.']}


def read(path):return json.loads(Path(path).read_text()) if path else None


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--candidate',required=True)
    for name in ['base-conversation','conversation','base-grounding','grounding','privacy','live']:
        p.add_argument('--'+name)
    p.add_argument('--output',required=True);a=p.parse_args()
    cards=lambda root:{s:read(Path(root)/s/'scorecard.json') for s in ['frozen','rolling','heldout']}
    result=qualify(cards(a.baseline),cards(a.candidate),*[read(getattr(a,k)) for k in ['base_conversation','conversation','base_grounding','grounding','privacy','live']])
    write_json(a.output,result);print(json.dumps({k:result[k] for k in ['hub_commit','quality_and_performance_pass','quality_and_performance_reasons','pre_deploy_qualified','release_accepted']}))
