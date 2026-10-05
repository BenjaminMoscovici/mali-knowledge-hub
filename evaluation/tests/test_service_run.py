import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from evaluation.common import digest
from evaluation.radar import VERSION, inputs
from evaluation.service_run import SERVICE, PROJECT, authorized, archive, private_storage, provenance
from evaluation.service_run import checkpoint, approved_evidence_project
from evaluation.runner import deployed_commit_matches
from evaluation.ui_capture import import_conversation


class ServiceBenchmarkTests(unittest.TestCase):
    def test_judge_progress_follows_persisted_receipts_and_resume_skips_completed_calls(self):
        from evaluation.judge import judge_run
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'raw').mkdir()
            (root/'raw/ADV01--0.json').write_text(json.dumps({'case_id':'ADV01','repetition':0,
                'response_hash':'original-answer-hash','ok':True,'response':{'answer':'synthetic'}}))
            result={'scores':{'decision_usefulness':4},'findings':[],'claims':[]}
            receipt={'estimated_usd':.001}
            observed=[]
            def progress(value):
                self.assertTrue((root/'judgments/ADV01--0.json').exists())
                self.assertTrue((root/'judge_receipts/ADV01--0.json').exists())
                self.assertEqual(set(value),{'case','rep','judge_ok','usefulness','usd'})
                observed.append(value)
            with patch('evaluation.judge.packet',return_value={}), \
                 patch('evaluation.public_packets.sanitize_packet',return_value={}), \
                 patch('evaluation.judge.evaluate',return_value=(result,receipt)) as call:
                judge_run(root,'frozen','dummy',public_provenance='synthetic',on_progress=progress)
                judge_run(root,'frozen','dummy',public_provenance='synthetic',on_progress=progress)
                self.assertEqual(call.call_count,1)
            self.assertEqual(len(observed),1)

    def test_worker_is_opt_in_and_rejects_wrong_deployment_or_project(self):
        self.assertFalse(authorized({}))
        good = {'MKH_EVALUATION_RUN': 'candidate-20261005', 'RENDER_SERVICE_ID': SERVICE,
                'SUPABASE_URL': PROJECT, 'RENDER_GIT_COMMIT': 'a' * 40}
        self.assertTrue(authorized(good))
        for field, value in [('RENDER_SERVICE_ID', 'original-public-hub'),
                             ('SUPABASE_URL', 'https://wrong-project.supabase.co'),
                             ('MKH_EVALUATION_RUN', '../other'), ('RENDER_GIT_COMMIT', 'branch')]:
            with self.assertRaises(ValueError):
                authorized(good | {field: value})

    def test_approved_normal_hub_evidence_requires_exact_project_service_and_scope(self):
        self.assertIsNone(approved_evidence_project({}))
        good={'MKH_EVALUATION_RUN':'candidate-qualification','RENDER_SERVICE_ID':SERVICE,
              'SUPABASE_URL':PROJECT,'RENDER_GIT_COMMIT':'a'*40,
              'MKH_EVALUATION_EVIDENCE_SCOPE':'approved-anonymous-synthesis-v1'}
        self.assertEqual(approved_evidence_project(good),PROJECT)
        for changes in [{'SUPABASE_URL':'https://wrong.supabase.co'},
                        {'RENDER_SERVICE_ID':'other-service'},{'MKH_EVALUATION_RUN':''},
                        {'MKH_EVALUATION_EVIDENCE_SCOPE':'export-private-history'}]:
            with self.assertRaises(ValueError):approved_evidence_project(good|changes)

    def test_public_artifact_bucket_is_rejected_without_permission_changes(self):
        client = Mock(); client.storage.list_buckets.return_value = [SimpleNamespace(id='mkh-evaluations', public=True)]
        with self.assertRaises(ValueError):
            private_storage(client)
        client.storage.create_bucket.assert_not_called()
        client.storage.from_.assert_not_called()

    def test_mixed_or_missing_live_commit_stops_required_measurement(self):
        answer={'response':{'metrics':{'hub_commit':'a'*40}}}
        self.assertTrue(deployed_commit_matches(answer,'a'*40,True))
        self.assertFalse(deployed_commit_matches(answer,'b'*40,True))
        self.assertFalse(deployed_commit_matches({'response':{}},'a'*40,True))
        # Earlier immutable baseline captures explicitly lacked this field.
        self.assertTrue(deployed_commit_matches({'response':{}},'a'*40,False))

    def test_resumed_conversation_rejects_mixed_commit_and_retains_failed_attempt(self):
        from evaluation.conversations import run
        from evaluation.common import write_json
        for ok in [True,False]:
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'raw/C01--0.json'
                record={'ok':ok,'response':{'metrics':{'hub_commit':'b'*40}},
                        'response_hash':'immutable','telemetry':{'server_seconds':1}}
                write_json(path,record)
                args=SimpleNamespace(output=tmp,base='https://synthetic.invalid',
                    hub_commit='a'*40,ids='C01',require_commit=True)
                with patch('evaluation.conversations.request_case') as request:
                    if ok:
                        with self.assertRaises(ValueError):run(args)
                    else:
                        run(args)
                    request.assert_not_called()
                self.assertEqual(json.loads(path.read_text()),record)

    def test_ui_import_rejects_a_turn_from_another_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'capture.json'
            path.write_text(json.dumps([{'sequence_id':'C01','turn':0,'answer':'815',
                'metrics':{'hub_commit':'a'*40}}]))
            with self.assertRaises(ValueError):import_conversation(path,Path(tmp)/'run','b'*40)
            self.assertFalse((Path(tmp)/'run/raw/C01--0.json').exists())

    def test_anonymously_readable_artifact_fails_even_when_storage_says_uploaded(self):
        storage=Mock();storage.list.side_effect=[[],[{'name':'captured.zip'}]]
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock()
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen',return_value=response):
            with self.assertRaises(ValueError):checkpoint(storage,tmp,'commit/milestone','captured',[])

    def test_archive_allowlist_excludes_configuration_and_detects_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); (p / 'frozen/raw').mkdir(parents=True)
            (p / 'frozen/raw/answer.json').write_text('{"answer":"synthetic"}')
            (p / 'runtime.json').write_text('secret-marker')
            data = archive(p, ['secret-marker'])
            with zipfile.ZipFile(io.BytesIO(data)) as zipped:
                self.assertEqual(zipped.namelist(), ['frozen/raw/answer.json'])
            (p / 'frozen/raw/answer.json').write_text('secret-marker')
            with self.assertRaises(ValueError): archive(p, ['secret-marker'])

    def test_archive_preserves_verification_calibration_and_failed_attempt_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            wanted={'web_verification.json','calibration_samples.json','capture_interruptions.json',
                    'failure_telemetry.json','paired_comparison.json','conversation_quality.json',
                    'publication_equivalence.json'}
            for name in wanted:(p/name).write_text('{"scope":"synthetic benchmark"}')
            (p/'unrelated-account-history.json').write_text('{"private":"excluded"}')
            with zipfile.ZipFile(io.BytesIO(archive(p,[]))) as zipped:
                self.assertEqual(set(zipped.namelist()),wanted)

    def test_changed_public_pdf_is_withheld_from_judge(self):
        response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock()
        response.read.return_value = b'changed bytes'
        with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen', return_value=response):
            result = json.loads(provenance(tmp).read_text())
        self.assertTrue(all(d['status'] == 'unverified' for d in result['documents']))
        self.assertTrue(all('pages_file' not in d for d in result['documents']))

    def test_aggregate_radar_checkpoint_is_bound_to_card_and_formula(self):
        card = {'split': 'frozen'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'radar_inputs.json'
            path.write_text(json.dumps({'scorecard_sha256': digest(card), 'formula_version': VERSION,
                                       'input_metrics': {'grounding': .8}}))
            self.assertEqual(inputs(card, tmp)['grounding'], .8)
            with self.assertRaises(ValueError): inputs(card | {'split': 'rolling'}, tmp)
            saved = json.loads(path.read_text()); saved['formula_version'] = 'different'
            path.write_text(json.dumps(saved))
            with self.assertRaises(ValueError): inputs(card, tmp)
