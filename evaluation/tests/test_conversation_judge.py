import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from evaluation.common import digest,write_json
from evaluation.conversation_judge import selected_records,judge_conversations


def fixture(tmp):
    from evaluation.conversation_judge import ROOT
    suite=json.loads((ROOT/'conversation_v1.json').read_text())
    write_json(tmp/'run_manifest.json',{'suite_sha256':digest(suite),'hub_commit':'a'*40})
    for s in suite['sequences']:
        for turn,expected in enumerate(s['followup_expectations'],1):
            if expected['grounded_answer_required']:
                response={'answer':'Synthetic cited fact [E01]','evidence':[], 'metrics':{'hub_commit':'a'*40}}
                write_json(tmp/'raw'/f'{s["id"]}--{turn}.json',{'ok':True,'sequence_id':s['id'],'turn':turn,
                    'sequence_hash':digest(s),'response':response,'response_hash':digest(response),
                    'started_at':'2026-10-05','request_payload':{'question':s['turns'][turn],'prior_messages':[]}})


def test_only_frozen_anonymous_turns_qualify():
    with tempfile.TemporaryDirectory() as t:
        root=Path(t);fixture(root);_,selected=selected_records(root)
        assert len(selected)==23
        p=root/'raw'/f'{selected[0][0]}.json';record=json.loads(p.read_text())
        record['request_payload']['conversation_id']='private-thread';write_json(p,record)
        with pytest.raises(ValueError):selected_records(root)


def test_scoring_resumes_without_buying_duplicate_calls():
    with tempfile.TemporaryDirectory() as t:
        root=Path(t);fixture(root)
        result={'claims':[{'text':'Synthetic cited fact','verdict':'supported','evidence_ids':['E01'],'citation_supported':True}],
                'scores':{},'findings':[]}
        with patch('evaluation.conversation_judge.evaluate',return_value=(result,{'estimated_usd':.001})) as evaluate:
            a=judge_conversations(root,'dummy',approved_hub_project='https://hofoubbmepacdljeablj.supabase.co')
            b=judge_conversations(root,'dummy',approved_hub_project='https://hofoubbmepacdljeablj.supabase.co')
            assert evaluate.call_count==23
            assert a['complete'] and b['citation_entailment']==1


def test_prior_evidence_ids_are_context_only_and_cannot_shadow_fresh_sources():
    with tempfile.TemporaryDirectory() as t:
        root=Path(t);fixture(root);_,selected=selected_records(root)
        name=selected[0][0];path=root/'raw'/f'{name}.json';r=json.loads(path.read_text())
        r['request_payload']['prior_messages']=[{'role':'assistant','content':'Earlier fact [E01, E09]',
            'evidence_refs':[{'evidence_id':'E09','content':'old source must not be exported'}]}]
        write_json(path,r);packets=[]
        def evaluate(p,key):
            packets.append(p);return {'claims':[],'scores':{},'findings':[]},{'estimated_usd':0}
        with patch('evaluation.conversation_judge.evaluate',side_effect=evaluate):
            judge_conversations(root,'dummy',approved_hub_project='https://hofoubbmepacdljeablj.supabase.co')
        p=next(p for p in packets if p['prior_messages'])
        assert p['prior_messages']==[{'role':'assistant','content':'Earlier fact [prior-turn citations: E01, E09]'}]
        assert p['evidence_packet_version']=='approved-conversation-evidence-1.1'
        assert 'old source must not be exported' not in json.dumps(p)
