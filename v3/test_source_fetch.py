from pathlib import Path
import tempfile
import unittest
from source_fetch import fetch_official, official_url


class Response:
    def __init__(self, data): self.data, self.headers = data, {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return "https://www.instat-mali.org/test.pdf"
    def read(self, maximum): return self.data


class Opener:
    def __init__(self, data): self.data = data
    def open(self, *args, **kwargs): return Response(self.data)


class FetchTests(unittest.TestCase):
    def test_failed_download_retains_good_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.pdf"
            path.write_bytes(b"%PDF-good")
            with self.assertRaises(ValueError):
                fetch_official("https://www.instat-mali.org/test.pdf", path, "pdf", opener=Opener(b"<html>error</html>"))
            self.assertEqual(b"%PDF-good", path.read_bytes())

    def test_new_version_retains_immutable_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.pdf"
            first = fetch_official("https://www.instat-mali.org/test.pdf", path, "pdf", opener=Opener(b"%PDF-first"))
            fetch_official("https://www.instat-mali.org/test.pdf", path, "pdf", opener=Opener(b"%PDF-second"))
            self.assertEqual(b"%PDF-first", (Path(folder) / "releases" / first["immutable_copy"]).read_bytes())

    def test_unchanged_content_preserves_retrieval_date(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.pdf"
            first = fetch_official("https://www.instat-mali.org/test.pdf", path, "pdf", opener=Opener(b"%PDF-same"))
            second = fetch_official("https://www.instat-mali.org/test.pdf", path, "pdf", opener=Opener(b"%PDF-same"))
            self.assertEqual(first["retrieved_at"], second["retrieved_at"])
            self.assertEqual("unchanged", second["status"])

    def test_unreviewed_destination_rejected(self):
        for url in ("http://www.instat-mali.org/file", "https://evil.example/file",
                    "https://www.instat-mali.org.evil.example/file", "https://user:pass@www.instat-mali.org/file"):
            with self.assertRaises(ValueError): official_url(url)


if __name__ == "__main__": unittest.main()
