"""Public, allowlisted catalogue. Never reads accounts, admin requests or originals."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import time
from urllib.parse import urlsplit

from provider_reads import execute_read
from source_catalogue import entries

_ROOT = Path(__file__).parent
_lock = Lock()
_catalogue = None
_documents = None


def public_url(value):
    """Only public source references; never signed storage URLs or credentials."""
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or '/storage/v1/' in url.path
                or url.hostname.endswith(('.supabase.co', '.supabase.in'))):
            return None
        return value
    except ValueError:
        return None


def catalogue(root=None):
    global _catalogue
    root = Path(root) if root else _ROOT
    paths = [root/'source_registry.json', *sorted(root.glob('source_wave*.json.gz'))]
    if (root/'country_indicators.json.gz').exists():paths.append(root/'country_indicators.json.gz')
    revision = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
    with _lock:
        if _catalogue and _catalogue[0] == revision:
            return deepcopy(_catalogue[1])
        result = []
        for row in entries(root):
            # Loaded row counts come from decoded packages. Legacy connected
            # sources retain their declared integration, without a live claim.
            state = ('loaded' if row['evidence_available'] and row.get('records') is not None
                     else 'connected' if row['evidence_available'] else 'pending')
            result.append({
                'title': row['source_name'], 'provider': row['provider'], 'kind': 'dataset',
                'state': state, 'status': str(row.get('integration_status') or 'not integrated').replace('_', ' '),
                'use': row.get('analytical_use'), 'period': row.get('historical_coverage'),
                'retrieved_at': row.get('last_successful_retrieval'),
                'update_frequency': row.get('update_frequency'),
                'records': row.get('records') if state == 'loaded' else None,
                'limitations': row.get('limitations') or [],
                'url': public_url(row.get('access_route')),
            })
        _catalogue = (revision, result)
        return deepcopy(result)


def indexed_documents(db):
    """Paginate active, indexed documents; no content, IDs or file paths returned."""
    result = []
    for start in range(0, 5000, 250):
        query = (db.table('documents').select(
            'title,organization,publication_date,valid_from,valid_until,document_type,'
            'language,source_url,created_at,chunks(count)')
            .eq('status', 'active').order('id').range(start, start+249))
        rows = execute_read(query, 'public_source_inventory').data
        if not isinstance(rows, list):
            raise ValueError('Document registry unavailable')
        for row in rows:
            chunks = row.get('chunks')
            if not isinstance(chunks, list) or len(chunks) != 1 or not isinstance(chunks[0].get('count'), int):
                raise ValueError('Index coverage unavailable')
            if chunks[0]['count'] <= 0:
                continue
            result.append({
                'title': row.get('title') or 'Untitled document',
                'provider': row.get('organization') or 'Publisher not reported',
                'kind': 'document', 'state': 'indexed',
                'publication_date': row.get('publication_date'),
                'valid_from': row.get('valid_from'), 'valid_until': row.get('valid_until'),
                'added_at': row.get('created_at'), 'document_type': row.get('document_type'),
                'language': row.get('language'), 'url': public_url(row.get('source_url')),
            })
        if len(rows) < 250:
            return result
    # Do not present a truncated list as the complete corpus.
    raise ValueError('Document catalogue exceeds current listing limit')


def inventory(db_factory):
    global _documents
    data = {'datasets': [], 'documents': [], 'catalogue_available': False,
            'documents_available': False, 'documents_checked_at': None}
    try:
        data['datasets'] = catalogue()
        data['catalogue_available'] = True
    except Exception:
        pass
    # Single-flight, bounded metadata cache. Failed reads are never cached or
    # shown as an empty corpus. No client, credentials or caller state retained.
    with _lock:
        try:
            if _documents is None or time.monotonic() >= _documents[0]:
                rows = indexed_documents(db_factory())
                _documents = (time.monotonic()+60, rows, datetime.now(timezone.utc).isoformat())
            data['documents'] = deepcopy(_documents[1])
            data['documents_checked_at'] = _documents[2]
            data['documents_available'] = True
        except Exception:
            pass
    return data
