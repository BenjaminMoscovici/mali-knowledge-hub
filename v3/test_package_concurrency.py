"""Packaged public sources share one cold decode across request/startup workers."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier, Event, Lock

import pytest


SOURCES = ['operational_sources', 'analytical_sources',
           'project_learning_sources', 'eu_sources']


@pytest.mark.parametrize('module_name', SOURCES)
def test_parallel_cold_readers_decode_each_source_once(monkeypatch, module_name):
    module = import_module(module_name)
    module.package.cache_clear()
    start, entered, duplicate, release = Barrier(9), Event(), Event(), Event()
    count_lock = Lock()
    calls = 0

    def decode(_):
        nonlocal calls
        with count_lock:
            calls += 1
            if calls > 1:
                duplicate.set()
        entered.set()
        assert release.wait(5), 'Decoder was never released'
        return {'records': [], 'tables': {}}

    def read():
        start.wait(timeout=5)
        return module.package()

    monkeypatch.setattr(module.json, 'load', decode)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            readers = [pool.submit(read) for _ in range(8)]
            start.wait(timeout=5)
            try:
                assert entered.wait(5)
                duplicate.wait(.2)
            finally:
                release.set()
            results = [f.result(timeout=5) for f in readers]
        assert calls == 1, f'{module_name} decoded {calls} full packages concurrently'
        assert all(value is results[0] for value in results)
        assert module.package() is results[0]
        assert calls == 1
    finally:
        module.package.cache_clear()


def test_different_sources_do_not_block_each_other():
    from evidence_cache import package_cached
    entered, release = Event(), Event()

    @package_cached
    def slow_source():
        entered.set()
        assert release.wait(5)
        return {'source': 'slow'}

    @package_cached
    def other_source():
        return {'source': 'other'}

    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(slow_source)
        try:
            assert entered.wait(5)
            assert pool.submit(other_source).result(timeout=2) == {'source': 'other'}
        finally:
            release.set()
        assert slow.result(timeout=5) == {'source': 'slow'}


def test_clear_during_load_prevents_stale_repopulation():
    from evidence_cache import package_cached
    entered, clearing, cleared, release = Event(), Event(), Event(), Event()
    calls = 0

    @package_cached
    def source():
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(5)
        return {'revision': calls}

    def clear():
        clearing.set()
        source.cache_clear()
        cleared.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(source)
        try:
            assert entered.wait(5)
            invalidation = pool.submit(clear)
            assert clearing.wait(5)
            assert not cleared.wait(.1)
        finally:
            release.set()
        assert first.result(timeout=5) == {'revision': 1}
        invalidation.result(timeout=5)
    assert source() == {'revision': 2}


@pytest.mark.parametrize('module_name', SOURCES)
def test_failed_decode_can_retry_and_clear_reloads(monkeypatch, module_name):
    module = import_module(module_name)
    module.package.cache_clear()
    calls = 0

    def decode(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError('Synthetic malformed source')
        return {'revision': calls}

    monkeypatch.setattr(module.json, 'load', decode)
    try:
        with pytest.raises(ValueError, match='Synthetic malformed source'):
            module.package()
        first = module.package()
        assert module.package() is first
        module.package.cache_clear()
        second = module.package()
        assert first == {'revision': 2}
        assert second == {'revision': 3}
        assert second is not first
    finally:
        module.package.cache_clear()
