import json
import pytest
from operational_sources import package, retrieve_operational_evidence
from operational_import import GeoMatcher
from operational_sources import publish_operational_snapshot


def test_acquired_release_counts_and_blank_delivery_fields():
    data = package()
    presence = [r for r in data['records'] if r['source_type'] == 'operational_presence']
    dtm = [r for r in data['records'] if r['source_type'] == 'displacement_stock']
    assert len(presence) == 5413 and len(dtm) == 467
    assert all(r['payload']['activity_status'] == 'presence_only' and r['payload']['reached'] is None for r in presence)
    assert all('village' not in r['payload']['geography'] for r in data['records'])
    assert sum(r['payload']['value'] for r in dtm if r['payload']['category'] == 'internally_displaced') == 414524
    assert {r['sheet'] for r in dtm} == {'PDIs', 'RETOURNEES_PDIs', 'RAPATRIES'}


def test_code_conflicts_cannot_silently_resolve():
    matcher = GeoMatcher()
    result = matcher.match({'region': 'Mopti', 'region_pcode': 'ML19', 'cercle': 'Bandiagara', 'cercle_pcode': 'ML1901'})
    assert not result['matches']
    assert len(result['issues']) == 2
    matcher.db.close()


def test_joined_retrieval_preserves_period_category_scope_and_locators():
    rows = retrieve_operational_evidence('What needs and displaced populations are documented in Mopti region and which actors and sectors are present?')
    assert {r['source_type'] for r in rows} == {'operational_presence', 'displacement_stock'}
    assert all(r['source_endpoint'].startswith('https://data.humdata.org/') and r['locator'] and r['release_id'] for r in rows)
    presence = next(r for r in rows if r['source_type'] == 'operational_presence')
    assert presence['reference_period_start'] == '2026-01-01'
    assert presence['publication_date'] is None and 'HDX resource creation date' in presence['content']
    assert 'PRESENCE ONLY' in presence['content']
    dtm = next(r for r in rows if r['source_type'] == 'displacement_stock')
    assert dtm['reference_period_end'] == '2025-09-30'
    assert 'STOCK (not flow)' in dtm['content'] and 'not a region/cercle total' in dtm['content']


def test_commune_query_does_not_inherit_regional_records():
    rows = retrieve_operational_evidence('Displaced people in commune de Socoura')
    assert rows and all('Socoura' in r['geographic_scope'] for r in rows)
    assert all('source_label_only_no_approved_commune_crosswalk' in r['content'] for r in rows)


def test_unrelated_query_is_not_polluted():
    assert retrieve_operational_evidence('What colour is the logo?') == []


def test_publication_refuses_other_projects_and_host_prefix_lookalikes(monkeypatch):
    monkeypatch.setenv('SUPABASE_SECRET_KEY','test-only-key')
    for url in ('https://unrelated.supabase.co','https://hofoubbmepacdljeablj.supabase.co.attacker.example'):
        monkeypatch.setenv('SUPABASE_URL',url)
        with pytest.raises(RuntimeError,match='authorized GIZ'):
            publish_operational_snapshot({'tables':{},'records':[],'releases':{}})


def test_release_count_conflict_never_activates_pointer(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','https://hofoubbmepacdljeablj.supabase.co')
    monkeypatch.setenv('SUPABASE_SECRET_KEY','test-only-key')
    class Response:
        headers={'Content-Range':'0-0/1'}
        def raise_for_status(self): pass
    class Session:
        def __init__(self):self.headers={};self.patches=[]
        def get(self,*args,**kwargs):return Response()
        def patch(self,*args,**kwargs):self.patches.append(kwargs);return Response()
    session=Session()
    monkeypatch.setattr('operational_sources.requests.Session',lambda:session)
    with pytest.raises(RuntimeError,match='active pointer unchanged'):
        publish_operational_snapshot({'tables':{},'records':[{'release_id':'test'},{'release_id':'test'}],
                                      'releases':{'test-dataset':'test'}})
    assert session.patches==[]
