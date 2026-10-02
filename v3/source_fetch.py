"""Bounded official-file retrieval with immutable copies and safe failed refreshes."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse
import urllib.request

OFFICIAL_HOSTS = {"data.humdata.org", "www.instat-mali.org", "finances.ml", "www.finances.ml",
                  "data.source.coop"}
MAX_BYTES = 40_000_000


def official_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname not in OFFICIAL_HOSTS or p.username or p.password or p.port not in (None, 443):
        raise ValueError("URL is outside the reviewed official source allowlist")


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_official(url, destination, kind, *, opener=None):
    """Two transient attempts maximum; malformed data never replaces a good file."""
    official_url(url)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    opener = opener or urllib.request.build_opener(OfficialRedirects())
    if kind not in {"json", "pdf", "zip", "parquet"}: raise ValueError("Unreviewed file format")
    for attempt in range(2):
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "MaliKnowledgeHub-source-import/1"}), timeout=25) as response:
                official_url(response.geturl())
                data = response.read(MAX_BYTES + 1)
                etag, modified = response.headers.get("ETag"), response.headers.get("Last-Modified")
            break
        except urllib.error.HTTPError as error:
            if attempt or error.code not in {429, 500, 502, 503, 504}: raise
        except (TimeoutError, urllib.error.URLError):
            if attempt: raise
    if not data or len(data) > MAX_BYTES: raise ValueError("Empty or oversized source resource")
    if kind == "json": json.loads(data)
    elif kind == "pdf" and not data.startswith(b"%PDF"): raise ValueError("Expected PDF")
    elif kind == "zip" and not data.startswith(b"PK\x03\x04"): raise ValueError("Expected ZIP")
    elif kind == "parquet" and not (data.startswith(b"PAR1") and data.endswith(b"PAR1")):
        raise ValueError("Expected Parquet")
    digest = hashlib.sha256(data).hexdigest()
    copies = destination.parent / "releases"
    copies.mkdir(exist_ok=True)
    immutable = copies / f"{digest}{destination.suffix}"
    if not immutable.exists(): immutable.write_bytes(data)
    unchanged = destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest
    if not unchanged:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name); output.write(data)
        os.replace(temporary, destination)
    receipt = {"url": url, "file": destination.name, "sha256": digest, "bytes": len(data),
        "retrieved_at": datetime.fromtimestamp(destination.stat().st_mtime, timezone.utc).isoformat(),
        "checked_at": datetime.now(timezone.utc).isoformat(), "etag": etag,
        "upstream_last_modified": modified, "status": "unchanged" if unchanged else "downloaded",
        "immutable_copy": immutable.name}
    destination.with_suffix(destination.suffix + ".receipt.json").write_text(json.dumps(receipt, indent=2))
    return receipt
