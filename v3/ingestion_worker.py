"""Run document processing independently of a Streamlit browser session.

The worker never calls Streamlit APIs. The database claim RPC remains the
cross-process guard; this small executor only prevents duplicate submissions
inside one app process and survives ordinary page reruns/reconnections.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI
from supabase import create_client

from ingestion import process_job


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mkh-ingestion")
_active = {}
_lock = threading.Lock()


def _process(url, secret, openai_key, job_id, corrections):
    try:
        return process_job(create_client(url, secret), OpenAI(api_key=openai_key),
                           job_id, corrections=corrections)
    except Exception as exc:
        # process_job records its stage and safe error on the job. Never log
        # provider exception text, uploaded content, keys, or token material.
        print(f"MKH_INGESTION_WORKER_FAILURE class={type(exc).__name__}", flush=True)
        raise


def schedule_job(url, secret, openai_key, job_id, corrections=None):
    """Submit one attempt per job within this process; return False if active."""
    with _lock:
        previous = _active.get(job_id)
        if previous is not None and not previous.done():
            return False
        _active[job_id] = _executor.submit(
            _process, url, secret, openai_key, job_id, corrections)
        return True
