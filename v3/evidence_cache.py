"""Bounded, read-only caches for immutable packaged evidence, never user threads.

Each deploy gets fresh process state. Keys include snapshot revision and UTC day;
date-sensitive end/status screening cannot bleed into a later query date.
Live providers retain their existing, shorter TTL policies.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import Lock
import json
import time


def snapshot_cached(filename, seconds=900, maxsize=64):
    def decorate(fn):
        entries, lock = OrderedDict(), Lock()
        path = Path(__file__).with_name(filename)
        revision = [None]
        @wraps(fn)
        def cached(*args, **kwargs):
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size, datetime.now(timezone.utc).date().isoformat(),
                   json.dumps((args,kwargs),sort_keys=True,default=str))
            now = time.monotonic()
            with lock:
                current_revision = key[:2]
                if revision[0] != current_revision:
                    entries.clear()
                    package = fn.__globals__.get("package")
                    if package is not None and hasattr(package, "cache_clear"):
                        package.cache_clear()
                    revision[0] = current_revision
                entry = entries.get(key)
                if entry and entry[0] > now:
                    entries.move_to_end(key)
                    return deepcopy(entry[1])
            value = fn(*args, **kwargs)
            with lock:
                entries[key] = (time.monotonic()+seconds,deepcopy(value))
                entries.move_to_end(key)
                while len(entries)>maxsize:
                    entries.popitem(last=False)
            return value
        def clear():
            with lock:
                entries.clear()
        cached.cache_clear = clear
        return cached
    return decorate
