from analytical_sources import package,retrieve_analytical_evidence


def test_validated_sources_and_missing_values():
    rows=package()['records']
    assert len(rows)==162
    ch=[r for r in rows if r['dataset_id']=='mli-ch-late2025']
    assert len(ch)==112 and {r['payload']['methodology'] for r in ch}=={'Cadre Harmonise'}
    national=next(r for r in rows if r['dataset_id']=='mli-ch-june2026-bulletin')
    assert national['payload']['phase_populations']['5'] is None
    assert national['payload']['phase35']==1560189


def test_joined_food_funding_and_presence_context_keeps_scope():
    rows=retrieve_analytical_evidence('What are food-security needs in Mopti and Mali humanitarian funding in 2026?')
    assert {r['source_type'] for r in rows}=={'food_security_classification','funding_aggregate'}
    assert all(r['locator'] and r['source_endpoint'].startswith('https://') and r['release_id'] for r in rows)
    ch=next(r for r in rows if r['document_title'].endswith('projected'))
    assert '8 of 8' in ch['content'] and 'not severity rank' in ch['content']
    assert ch['reference_period_start']=='2026-06-01'
    assert 'code_name_or_parent_conflict' in ch['content']
    fts=next(r for r in rows if r['source_type']=='funding_aggregate' and '1511' in r['content'])
    assert '577866412.0' in fts['content'] and '135628821.0' in fts['content']
    assert 'not synonymous with disbursements' in fts['content']


def test_commune_estimates_are_not_manufactured():
    rows=retrieve_analytical_evidence('Food security in commune de Socoura')
    assert rows and 'No commune estimates' in rows[0]['content']
    assert all(r['geographic_precision']!='commune' for r in rows)


def test_explicit_year_funding_never_substitutes_future_usage_year():
    rows=retrieve_analytical_evidence('FTS funding 2026')
    assert len(rows)==2
    assert all(r['reference_period_start']=='2026-01-01' for r in rows)
    assert retrieve_analytical_evidence('What colour is the logo?')==[]
