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


class ServiceBenchmarkTests(unittest.TestCase):
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

    def test_public_artifact_bucket_is_rejected_without_permission_changes(self):
        client = Mock(); client.storage.list_buckets.return_value = [SimpleNamespace(id='mkh-evaluations', public=True)]
        with self.assertRaises(ValueError):
            private_storage(client)
        client.storage.create_bucket.assert_not_called()
        client.storage.from_.assert_not_called()

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
