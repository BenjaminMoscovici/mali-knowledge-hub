"""A browser rerun must not interrupt a submitted ingestion attempt."""

import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import ingestion_worker


class IngestionWorkerTest(unittest.TestCase):
    def test_duplicate_submission_does_not_start_another_attempt(self):
        entered = threading.Event()
        release = threading.Event()
        attempts = []
        job_id = str(uuid4())

        def work(*args):
            attempts.append(args[3])
            entered.set()
            self.assertTrue(release.wait(5))
            return "ready"

        with patch.object(ingestion_worker, "_process", side_effect=work):
            self.assertTrue(ingestion_worker.schedule_job("url", "secret", "key", job_id))
            self.assertTrue(entered.wait(5))
            self.assertFalse(ingestion_worker.schedule_job("url", "secret", "key", job_id))
            release.set()
            self.assertEqual(ingestion_worker._active[job_id].result(timeout=5), "ready")
        self.assertEqual(attempts, [job_id])


if __name__ == "__main__":
    unittest.main()
