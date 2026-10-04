"""Retry transient transport failures of explicitly read-only Supabase operations.

Never wrap ingestion, mutations or model generation. A retry is bounded and
logged without provider messages, credentials, user queries or source text.
"""
import json
import time
import httpx


def execute_read(query, operation):
    for attempt in range(2):
        try:
            return query.execute()
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout) as error:
            print('MKH_READ_RETRY ' + json.dumps({'operation':operation,
                'error_type':type(error).__name__, 'attempt':attempt+1,
                'retrying':attempt==0}),flush=True)
            if attempt:
                raise
            time.sleep(0.15)
