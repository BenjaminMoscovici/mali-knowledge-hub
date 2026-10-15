from types import SimpleNamespace
from unittest.mock import Mock, patch
from starlette.testclient import TestClient
import pytest
import source_inventory as inventory
import web_api

@pytest.fixture(autouse=True)
def clear_cache():
    inventory._documents = None
    inventory._catalogue = None

def db_with(pages):
    db=Mock()
    db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect=[SimpleNamespace(data=p) for p in pages]
    return db

def document(**extra):
    return dict(title='National plan',organization='Publisher',chunks=[{'count':5}],status='active',file_path='private/original.pdf',email='private@example.org',**extra)

def test_only_indexed_documents_and_allowlisted_metadata_are_public():
    db=db_with([[document(source_url='https://example.org/plan.pdf'),{'title':'Not indexed yet','chunks':[{'count':0}]}]])
    rows=inventory.indexed_documents(db)
    assert len(rows)==1 and rows[0]['state']=='indexed'
    assert not {'file_path','email','chunks','status','id'} & rows[0].keys()
    assert rows[0]['url']=='https://example.org/plan.pdf'
    db.table.assert_called_once_with('documents')
    db.table.return_value.select.return_value.eq.assert_called_once_with('status','active')

def test_document_pagination_does_not_silently_truncate_at_first_page():
    db=db_with([[document() for _ in range(250)],[document()]])
    assert len(inventory.indexed_documents(db))==251
    query=db.table.return_value.select.return_value.eq.return_value.order.return_value
    assert [c.args for c in query.range.call_args_list]==[(0,249),(250,499)]

@pytest.mark.parametrize('row',[{'title':'Unverified'}, {'chunks':[]}, {'chunks':[{'count':'5'}]}])
def test_unknown_index_coverage_is_failure_not_verified_empty(row):
    with pytest.raises(ValueError):inventory.indexed_documents(db_with([[row]]))

@pytest.mark.parametrize('url',['javascript:alert(1)','http://example.org/a','https://secret@example.org/a','https://example.org/a?token=private','https://example.org/a#private','https://example.org/storage/v1/object/sign/originals/doc','https://project.supabase.co/storage/v1/object/public/doc','https://example.org/\nprivate','https://[invalid',None])
def test_private_or_unsafe_links_are_not_published(url):
    assert inventory.public_url(url) is None

def test_failed_document_check_is_unknown_and_retries_without_leaking_exception():
    with patch.object(inventory,'catalogue',return_value=[]):
        result=inventory.inventory(lambda: (_ for _ in ()).throw(RuntimeError('secret password')))
        assert not result['documents_available'] and result['documents_checked_at'] is None
        assert 'secret' not in str(result)
        result=inventory.inventory(lambda:db_with([[document()]]))
        assert result['documents_available'] and len(result['documents'])==1

def test_dataset_failure_keeps_document_results_and_expired_failure_does_not_reuse_old_count():
    with patch.object(inventory,'catalogue',side_effect=ValueError('private')):
        first=inventory.inventory(lambda:db_with([[document()]]))
        assert first['documents_available'] and not first['catalogue_available']
        inventory._documents=(0,first['documents'],first['documents_checked_at'])
        second=inventory.inventory(lambda:db_with([None]))
        assert not second['documents_available'] and not second['documents']

def test_catalogue_separates_loaded_connected_and_pending_and_recounts_actual_evidence():
    rows=inventory.catalogue()
    wb=next(r for r in rows if r['title'].startswith('World Bank Projects'))
    assert wb['state']=='loaded' and wb['records']==215
    assert next(r for r in rows if 'MTR2024' in r['title'])['state']=='pending'
    connected=next(r for r in rows if r['title']=='Existing synchronized project mirror')
    assert connected['state']=='connected' and connected['records'] is None
    assert not {'authentication','responsible_party','checksum','next_action','file_path'} & wb.keys()

def test_public_page_and_api_have_security_headers_and_no_auth_dependency():
    client=TestClient(web_api.app,base_url='https://example.org')
    with patch.object(inventory,'inventory',return_value={'documents_available':False}),patch.object(web_api,'actor') as actor:
        response=client.get('/api/sources')
        assert response.status_code==200 and response.json()=={'documents_available':False}
        assert response.headers['cache-control']=='no-store'
        assert "script-src 'self'" in response.headers['content-security-policy']
        assert client.get('/sources').status_code==200
        assert 'What the Hub knows' in client.get('/').text
        actor.assert_not_called()
    client.close()
