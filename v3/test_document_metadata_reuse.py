"""Registry reuse removes redundant reads without losing source provenance."""
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
import knowledge_hub_runtime as runtime


def clients():
    db=MagicMock()
    db.rpc.return_value.execute.return_value=SimpleNamespace(data=[{'document_id':'d1','content':'Fact','similarity':.9}])
    ai=MagicMock()
    ai.embeddings.create.return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[.1,.2])])
    return db,ai


def metadata():
    return {'id':'d1','title':'Plan','organization':'Government','publication_date':'2024-12-01',
            'valid_from':None,'valid_until':None,'document_type':'Strategy','language':'fr',
            'geographic_scope':'Mali','status':'active','version':'2024'}


def test_complete_registry_snapshot_preserves_provenance_without_another_read():
    db,ai=clients();doc=metadata()
    with patch.object(runtime,'supabase',db),patch.object(runtime,'openai_client',ai):
        rows=runtime.search_knowledge_base('priorities',filter_document_ids=['d1'],document_metadata=[doc])
    db.table.assert_not_called()
    assert rows[0]['publication_date']=='2024-12-01'
    assert rows[0]['version']=='2024' and rows[0]['document_title']=='Plan'
    assert db.rpc.call_args.args[1]['filter_document_ids']==['d1']
    assert doc==metadata()  # never mutate the shared registry


def test_partial_registry_falls_back_to_full_metadata_read():
    db,ai=clients()
    db.table.return_value.select.return_value.in_.return_value.execute.return_value=SimpleNamespace(data=[metadata()])
    with patch.object(runtime,'supabase',db),patch.object(runtime,'openai_client',ai):
        rows=runtime.search_knowledge_base('priorities',document_metadata=[{'id':'d1','title':'Partial'}])
    db.table.assert_called_once_with('documents')
    db.table.return_value.select.return_value.in_.assert_called_once_with('id',['d1'])
    assert rows[0]['document_title']=='Plan' and rows[0]['publication_date']=='2024-12-01'
