"""New-Source Challenge through the guest chat API without external providers."""
import json

from starlette.testclient import TestClient

import registry_observations
from web_api import app

ORIGIN = 'https://mali-knowledge-hub.onrender.com'


def chat(client, question):
    response = client.post('/api/chat', json={'question': question}, headers={'Origin': ORIGIN})
    assert response.status_code == 200
    return response.json()


def test_real_preliminary_census_is_cited_and_projection_keeps_existing_route():
    client = TestClient(app, base_url=ORIGIN)
    result = chat(client, 'Quelle était la population du Mali au recensement de 2022 ?')
    assert '22\u202f395\u202f489 habitants' in result['answer']
    assert result['evidence'][0]['page'] == 12
    assert result['metrics']['model_calls'] == result['metrics']['embedding_calls'] == 0
    assert result['metrics']['estimated_usd'] == 0
    projection = chat(client, 'Quelle était la population du Mali en 2023 ?')
    assert '23,143,456' in projection['answer']
    assert projection['metrics']['route'] == 'country_fact'


def test_unfamiliar_releases_need_only_registry_data(tmp_path, monkeypatch):
    registry = tmp_path / 'registry.json'
    capability = {
        'measure': 'functional_boreholes', 'definition': 'physical site inspection',
        'geography_id': 'toy:district:a', 'place': 'Dara District', 'place_aliases': ['Dara District'],
        'aliases': ['functional boreholes in {place}', 'forages fonctionnels à {place}'], 'unit': 'site',
        'labels': {'en': 'Functional boreholes', 'fr': 'Forages fonctionnels'},
        'unit_labels': {'en': 'sites', 'fr': 'sites'},
        'notes': {'en': 'Inspected sites only.', 'fr': 'Sites inspectés uniquement.'},
        'version': '1',
    }
    entries = []
    for year, value in ((2021, 41), (2022, 58)):
        source = f'Unfamiliar monitoring release {year}'
        entries.append({
            'source_name': source, 'provider': 'Synthetic audit provider',
            'access_route': f'https://example.org/inspections/{year}',
            'integration_status': 'integrated_with_limitations',
            'annual_observations': [dict(capability, release_id=f'release-{year}', records=[
                dict(year=year, value=value, id=f'row-{year}', locator='Sheet Results row 3',
                     excerpt=f'Functional boreholes: {value}')
            ])],
        })
    registry.write_text(json.dumps(entries))
    monkeypatch.setattr(registry_observations, 'REGISTRY', registry)
    client = TestClient(app, base_url=ORIGIN)
    result = chat(client, 'Compare functional boreholes in Dara District in 2021 and 2022')
    assert '**41 sites**' in result['answer'] and '**58 sites**' in result['answer']
    assert '**+17 sites**. [E01, E02]' in result['answer']
    assert [row['record_id'] for row in result['evidence']] == ['row-2021', 'row-2022']
    assert all(row['locator'] == 'Sheet Results row 3' for row in result['evidence'])
    count = chat(client, 'How many functional boreholes in Dara District in 2021?')
    assert '**41 sites**' in count['answer']
    result = chat(client, 'Donnez les forages fonctionnels à Dara District en 2021 ?')
    assert result['metrics']['route'] == 'registry_observation'
    assert "Sites inspectés uniquement." in result["answer"]
    missing = chat(client, 'Comparez les forages fonctionnels à Dara District en 2021 et 2023')
    assert 'Année sans observation dans ce registre : 2023' in missing['answer']
    assert len(missing['evidence']) == 1

    entries[1]['annual_observations'][0]['definition'] = 'operator estimates'
    registry.write_text(json.dumps(entries))
    assert registry_observations.answer(
        'Compare functional boreholes in Dara District in 2021 and 2022', 'English') is None
    assert registry_observations.answer(
        'Functional boreholes in Dara District in 2021 adjusted for population', 'English') is None


def test_unavailable_registry_leaves_existing_geography_path(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_observations, 'REGISTRY', tmp_path / 'missing.json')
    result = chat(TestClient(app, base_url=ORIGIN), 'Quelle était la population du Mali en 2023 ?')
    assert '23,143,456' in result['answer']
    assert result['metrics']['route'] == 'country_fact'
