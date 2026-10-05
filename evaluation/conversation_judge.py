"""Independent claim qualification of frozen anonymous factual follow-ups."""
import concurrent.futures
import json
import re
from pathlib import Path
from .common import digest,now,write_json
from .judge import packet,evaluate
from .public_packets import approved_hub_packet,sanitize_packet
from .adjudication import claims_with_coverage

ROOT=Path(__file__).parent/'benchmarks'

def selected_records(directory):
    root=Path(directory);suite=json.loads((ROOT/'conversation_v1.json').read_text())
    freeze=json.loads((ROOT/'conversation_freeze_manifest.json').read_text())
    manifest=json.loads((root/'run_manifest.json').read_text())
    if digest(suite)!=freeze['suite_sha256'] or manifest['suite_sha256']!=freeze['suite_sha256']:
        raise ValueError('Conversation qualification requires the unchanged frozen suite')
    selected=[]
    for sequence in suite['sequences']:
        for turn,expected in enumerate(sequence['followup_expectations'],1):
            if not expected['grounded_answer_required']:continue
            name=f'{sequence["id"]}--{turn}'
            record=json.loads((root/'raw'/f'{name}.json').read_text())
            if record.get('sequence_hash')!=digest(sequence) or record.get('turn')!=turn or record.get('sequence_id')!=sequence['id']:
                raise ValueError('Conversation turn identity mismatch')
            if digest(record['response'])!=record['response_hash']:
                raise ValueError('Conversation response hash mismatch')
            observed=(record.get('response') or {}).get('metrics',{}).get('hub_commit')
            if record['ok'] and observed and observed!=manifest['hub_commit']:
                raise ValueError('Conversation deployment mismatch')
            if record['request_payload'].get('conversation_id') or record['response'].get('saved'):
                raise ValueError('Only frozen anonymous synthetic conversations may be scored')
            if record['request_payload'].get('question')!=sequence['turns'][turn]:
                raise ValueError('Conversation question differs from the frozen turn')
            case={'id':name,'question':sequence['turns'][turn],
                  'language':sequence['language'],
                  'difficulty':sequence['difficulty'],
                  'prior_messages':[{'role':m['role'],'content':re.sub(r'\[(E\d+(?:[, ]+E\d+)*)\]',
                      r'[prior-turn citations: \1]',m.get('content',''))}
                      for m in record['request_payload'].get('prior_messages',[])
                      if m.get('role') in {'user','assistant'}],
                  'expected_behavior':json.dumps(expected,ensure_ascii=False),
                  'required_source_families':[]}
            selected.append((name,record,case))
    return manifest,selected

def judge_conversations(directory,key,approved_hub_project=None,public_provenance=None,workers=2,on_progress=None):
    root=Path(directory);manifest,selected=selected_records(root)
    def work(item):
        name,record,case=item;target=root/'judgments'/f'{name}.json'
        if not record['ok']:return
        p=packet(case,record)
        if approved_hub_project:p=approved_hub_packet(p,record,approved_hub_project)
        elif public_provenance:p=sanitize_packet(p,record,public_provenance)
        else:raise ValueError('Independent conversation scoring requires explicitly scoped evidence')
        p['evidence_packet_version']=('approved' if approved_hub_project else 'public')+'-conversation-evidence-1.1'
        p['context_policy']='Prior messages are anonymous frozen context only; prior evidence objects are excluded and historical citation identifiers are explicitly namespaced. Only current fresh evidence establishes factual support.'
        if target.exists():
            j=json.loads(target.read_text())
            if j['response_hash']!=record['response_hash'] or j['packet_hash']!=digest(p):
                raise ValueError('Existing conversation judgment does not match immutable inputs')
            return
        write_json(root/'judge_packets'/f'{name}.json',p)
        try:
            result,receipt=evaluate(p,key)
            receipt['evidence_packet_version']=p['evidence_packet_version']
            write_json(root/'judge_receipts'/f'{name}.json',receipt)
            write_json(target,{'case_id':name,'repetition':0,'response_hash':record['response_hash'],
                'packet_hash':digest(p),'result':result,'receipt':receipt})
            return {'case':name,'judge_ok':True}
        except Exception as exc:
            write_json(root/'judge_errors'/f'{name}.json',{'case_id':name,'error_type':type(exc).__name__,'at':now()})
            return {'case':name,'judge_ok':False,'error_type':type(exc).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for value in pool.map(work,selected):
            if value and on_progress:on_progress(value)
    claims=[];judgments=[]
    for name,record,_ in selected:
        path=root/'judgments'/f'{name}.json'
        if not path.exists():continue
        j=json.loads(path.read_text());p=json.loads((root/'judge_packets'/f'{name}.json').read_text())
        adjusted,_=claims_with_coverage(j,p,record);claims.extend(adjusted);judgments.append(j)
    assessed=[c for c in claims if c['verdict']!='unassessable']
    cited=[c for c in claims if c['evidence_ids'] and c['citation_supported'] is not None]
    result={'method':'Independent pinned analytical judge of frozen factual follow-ups; prior AI answers remain context, not evidence.',
        'suite_sha256':manifest['suite_sha256'],'hub_commit':manifest['hub_commit'],
        'expected_followups':len(selected),'judged_followups':len(judgments),
        'failed_hub_attempts':sum(not r['ok'] for _,r,_ in selected),
        'complete':len(judgments)==len(selected),
        'assessed_claims':len(assessed),'unassessable_claims':len(claims)-len(assessed),
        'unsupported_claim_rate':sum(c['verdict'] in {'unsupported','contradicted'} for c in assessed)/len(assessed) if assessed else None,
        'citation_entailment':sum(c['citation_supported'] for c in cited)/len(cited) if cited else None,
        'assessed_cited_claims':len(cited),
        'evaluator_estimated_cost_usd':sum(j['receipt'].get('estimated_usd') or 0 for j in judgments),
        'human_calibrated':None}
    write_json(root/'conversation_quality.json',result);return result
