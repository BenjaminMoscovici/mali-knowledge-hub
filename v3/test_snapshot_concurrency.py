"""Real multiprocess startup must not share a renameable temporary file."""
import gzip
import hashlib
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sqlite3


def extract(paths):
    import source_wave
    source_wave.SNAPSHOT_GZ=Path(paths[0])
    source_wave.SNAPSHOT=Path(paths[1])
    path=source_wave.snapshot_path()
    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
        return str(path),db.execute('select count(*) from fixture').fetchone()[0]


def test_parallel_snapshot_initialization_is_atomic_and_version_scoped(tmp_path):
    import source_wave
    assert hashlib.sha256(source_wave.SNAPSHOT_GZ.read_bytes()).hexdigest() in source_wave.SNAPSHOT.name
    source=tmp_path/'source.sqlite'
    with sqlite3.connect(source) as db:
        db.execute('create table fixture(content text)')
        db.executemany('insert into fixture values(?)',[('public synthetic source '*1000,)]*300)
    compressed=tmp_path/'source.sqlite.gz'
    with gzip.open(compressed,'wb') as out:out.write(source.read_bytes())
    destination=tmp_path/'snapshot.sqlite'
    with ProcessPoolExecutor(max_workers=8,mp_context=multiprocessing.get_context('spawn')) as pool:
        rows=list(pool.map(extract,[(str(compressed),str(destination))]*16))
    assert rows==[(str(destination),300)]*16
    assert destination.read_bytes()==source.read_bytes()
    assert not list(tmp_path.glob('*.part'))
