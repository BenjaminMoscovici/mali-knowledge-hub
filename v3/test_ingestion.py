"""Behavioral acceptance checks for PDF, OCR, failure exclusion and retry."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import fitz

sys.path.insert(0, str(Path(__file__).parent))
from ingestion import DuplicateDocumentError, create_job, extract_pdf, process_job  # noqa: E402


def fixture_pdf(scanned=False):
    document = fitz.open()
    page = document.new_page()
    content = "Mali development priorities and projects in the 2026 reporting period."
    for y in (70, 100, 130, 160):
        page.insert_text((40, y), content)
    if scanned:
        png = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
        document.close()
        document = fitz.open()
        page = document.new_page()
        page.insert_image(page.rect, stream=png)
    raw = document.tobytes()
    document.close()
    return raw


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.operation, self.value, self.key = db, table, None, None, None

    def insert(self, value):
        self.operation, self.value = "insert", value
        return self

    def update(self, value):
        self.operation, self.value = "update", value
        return self

    def select(self, columns):
        self.operation = "select"
        return self

    def eq(self, key, value):
        self.key, self.match = key, value
        return self

    def in_(self, key, values):
        self.allowed_statuses = set(values)
        return self

    def limit(self, count):
        return self

    def single(self):
        return self

    def execute(self):
        if self.operation == "insert":
            row = dict(self.value, id=f"job-{len(self.db.jobs)+1}")
            self.db.jobs[row["id"]] = row
            return SimpleNamespace(data=[row])
        if self.operation == "select" and self.key == "sha256":
            matches = [row for row in self.db.jobs.values()
                       if row["sha256"] == self.match and row["status"] in self.allowed_statuses]
            return SimpleNamespace(data=matches[:1])
        row = self.db.jobs[self.match]
        if self.operation == "update":
            row.update(self.value)
        return SimpleNamespace(data=row)


class Storage:
    def __init__(self, db):
        self.db = db

    def from_(self, bucket):
        self.bucket = bucket
        return self

    def upload(self, path, raw, options):
        self.db.originals[path] = raw

    def download(self, path):
        return self.db.originals[path]


class Database:
    def __init__(self):
        self.jobs, self.originals, self.published = {}, {}, {}
        self.storage = Storage(self)

    def table(self, name):
        assert name == "ingestion_jobs"
        return Query(self, name)

    def rpc(self, name, arguments):
        db = self

        if name == "claim_ingestion_job":
            class Claim:
                def execute(self):
                    job = db.jobs[arguments["p_job_id"]]
                    if job["status"] not in ("queued", "failed", "partially processed", "ready"):
                        raise ValueError("Job is already processing or cannot be processed")
                    job.update(status="processing", error=None)
                    return SimpleNamespace(data=job)

            return Claim()

        assert name == "publish_ingestion"

        class RPC:
            def execute(self):
                job = db.jobs[arguments["p_job_id"]]
                assert job["status"] == "processing"
                assert len(arguments["p_chunks"]) == arguments["p_quality"]["embeddings"]
                doc_id = "published-" + job["id"]
                db.published[doc_id] = arguments["p_chunks"]
                job.update(status="ready", document_id=doc_id,
                           metadata=arguments["p_metadata"], quality=arguments["p_quality"])
                return SimpleNamespace(data=doc_id)

        return RPC()


class Embeddings:
    def __init__(self):
        self.fail = False

    def create(self, model, input):
        if self.fail:
            raise RuntimeError("provider failure")
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[0.001] * 1536)
                                     for i in range(len(input))],
                               usage=SimpleNamespace(total_tokens=100))


class VisionResponses:
    def __init__(self):
        self.fail = False
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs["model"] == "gpt-4.1-mini"
        assert kwargs["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        if self.fail:
            raise RuntimeError("private request details must not appear in job errors")
        return SimpleNamespace(status="completed",
                               output_text="Mali development priorities and projects in the 2026 reporting period. " * 4,
                               usage=SimpleNamespace(input_tokens=200, output_tokens=40))


class IngestionAcceptance(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.embeddings = Embeddings()
        self.responses = VisionResponses()
        self.client = SimpleNamespace(embeddings=self.embeddings, responses=self.responses)

    def test_normal_pdf_becomes_searchable(self):
        job = create_job(self.db, "normal.pdf", fixture_pdf(), "admin")
        doc_id = process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["status"], "ready")
        self.assertTrue(self.db.published[doc_id])
        self.assertEqual(self.db.published[doc_id][0]["page_number"], 1)

    def test_scanned_pdf_uses_ocr_and_becomes_searchable(self):
        job = create_job(self.db, "scan.pdf", fixture_pdf(scanned=True), "admin")
        doc_id = process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["quality"]["ocr_pages"], [1])
        self.assertEqual(self.db.jobs[job]["quality"]["ocr_provider"], "openai")
        self.assertEqual(self.db.jobs[job]["quality"]["ocr_input_tokens"], 200)
        self.assertTrue(self.db.published[doc_id])

    def test_vision_provider_error_does_not_publish_or_leak_request_details(self):
        job = create_job(self.db, "scan.pdf", fixture_pdf(scanned=True), "admin")
        self.responses.fail = True
        with self.assertRaisesRegex(ValueError, "Vision OCR request failed"):
            process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["status"], "failed")
        self.assertNotIn("private request details", self.db.jobs[job]["error"])
        self.assertFalse(self.db.published)

    def test_broken_document_is_excluded_and_error_visible(self):
        job = create_job(self.db, "broken.pdf", b"not a PDF", "admin")
        with self.assertRaises(ValueError):
            process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["status"], "failed")
        self.assertIn("PDF", self.db.jobs[job]["error"])
        self.assertEqual(self.db.published, {})

    def test_duplicate_ready_document_is_not_ingested_twice(self):
        raw = fixture_pdf()
        job = create_job(self.db, "first.pdf", raw, "admin")
        process_job(self.db, self.client, job)
        with self.assertRaisesRegex(ValueError, "already has a ready job"):
            create_job(self.db, "same-file.pdf", raw, "admin")
        self.assertEqual(len(self.db.jobs), 1)
        self.assertEqual(len(self.db.published), 1)

    def test_already_processing_job_cannot_be_claimed_twice(self):
        job = create_job(self.db, "first.pdf", fixture_pdf(), "admin")
        self.db.rpc("claim_ingestion_job", {"p_job_id": job}).execute()
        with self.assertRaisesRegex(ValueError, "already processing"):
            process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["status"], "processing")
        self.assertEqual(self.db.published, {})

    def test_duplicate_while_original_is_still_uploading(self):
        raw = fixture_pdf()
        job = create_job(self.db, "first.pdf", raw, "admin")
        self.db.jobs[job]["status"] = "uploaded"
        with self.assertRaises(DuplicateDocumentError):
            create_job(self.db, "second.pdf", raw, "admin")

    def test_embedding_failure_then_retry(self):
        job = create_job(self.db, "retry.pdf", fixture_pdf(), "admin")
        self.embeddings.fail = True
        with self.assertRaises(RuntimeError):
            process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["status"], "partially processed")
        self.assertEqual(self.db.published, {})
        self.embeddings.fail = False
        process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["status"], "ready")

    def test_reviewed_metadata_survives_retry_and_preserves_prior_publication(self):
        job = create_job(self.db, "review.pdf", fixture_pdf(), "admin")
        doc_id = process_job(self.db, self.client, job)
        original_chunks = self.db.published[doc_id]
        with self.assertRaisesRegex(ValueError, "Publication date"):
            process_job(self.db, self.client, job,
                        corrections={"publication_date": "2026-13-88"})
        self.assertEqual(self.db.jobs[job]["status"], "ready")

        self.embeddings.fail = True
        with self.assertRaises(RuntimeError):
            process_job(self.db, self.client, job,
                        corrections={"title": "Reviewed title"})
        self.assertEqual(self.db.jobs[job]["status"], "partially processed")
        self.assertEqual(self.db.published[doc_id], original_chunks)

        self.embeddings.fail = False
        process_job(self.db, self.client, job,
                    corrections={"title": "Reviewed title", "publication_date": "2026-09-28"})
        self.assertEqual(self.db.jobs[job]["metadata"]["title"], "Reviewed title")
        self.assertEqual(self.db.jobs[job]["quality"]["metadata_confidence"]["title"],
                         "confirmed_by_admin")
        process_job(self.db, self.client, job)
        self.assertEqual(self.db.jobs[job]["metadata"]["title"], "Reviewed title")
        self.assertEqual(self.db.jobs[job]["metadata"]["publication_date"], "2026-09-28")


if __name__ == "__main__":
    unittest.main()
