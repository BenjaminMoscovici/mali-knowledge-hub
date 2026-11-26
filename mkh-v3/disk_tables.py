"""Open checksum-pinned analytical tables shipped with a published source."""
from contextlib import closing
from functools import lru_cache
import gzip
import hashlib
from pathlib import Path
import shutil
import sqlite3
import tempfile


@lru_cache(maxsize=1)
def _cache_directory():
    return tempfile.TemporaryDirectory(prefix="mkh-tables-")


@lru_cache(maxsize=32)
def open_snapshot(package: Path, digest: str):
    with package.open("rb") as raw:
        if hashlib.file_digest(raw, "sha256").hexdigest() != digest:
            raise ValueError("Published table checksum mismatch")
        raw.seek(0)
        with gzip.GzipFile(fileobj=raw) as source, tempfile.NamedTemporaryFile(
            dir=_cache_directory().name, suffix=".sqlite", delete=False
        ) as target:
            shutil.copyfileobj(source, target)
    return Path(target.name).as_uri() + "?mode=ro&immutable=1"


def input_records(uri, table, ids):
    if not ids:
        return []
    slots = ",".join("?" for _ in ids)
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute(f'SELECT id, locator FROM "{table}" WHERE id IN ({slots})', tuple(ids)).fetchall()
