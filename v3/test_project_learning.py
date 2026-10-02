from project_learning_sources import package,retrieve_project_learning


def test_project_country_subset_and_iati_deduplication():
    rows=package()['records']
    assert len(rows)==254
    wb=[r for r in rows if r['source_type']=='development_project']
    iati=[r for r in rows if r['source_type']=='aid_activity']
    assert len(wb)==215 and len(iati)==36
    assert sum(r['payload']['source_sector_rows'] for r in iati)==136
    assert all(r['payload']['country']=='Mali' for r in wb+iati)
    assert all('latitude' not in r['payload'] for r in rows)


def test_exact_project_join_keeps_evaluation_limitations_and_page_citations():
    rows=retrieve_project_learning('For P144442 compare World Bank and IATI project records with IEG learning, results and constraints')
    assert {r['source_type'] for r in rows}=={'development_project','aid_activity','evaluation_finding'}
    evaluation=[r for r in rows if r['source_type']=='evaluation_finding']
    assert {r['page'] for r in evaluation}=={9,11,17}
    assert all('Transferability' in r['content'] and 'current FONGIM/OCHA' in r['content'] for r in evaluation)
    assert all(r['locator'] and r['release_id'] for r in rows)
    activity=next(r for r in rows if r['source_type']=='aid_activity')
    assert 'Exact project-ID identity link' in activity['content']
    assert 'not interpreted as verified disbursements' in activity['content']


def test_future_pipeline_is_not_approved_or_active_delivery():
    rows=retrieve_project_learning('World Bank P518603')
    profile=next(r for r in rows if r['document_title'].startswith('World Bank —'))
    assert 'source status Pipeline' in profile['content']
    assert 'future_board_date_planned_not_approved' in profile['content']
    assert 'not verified activity/reach' in profile['content']
    assert retrieve_project_learning('What colour is the logo?')==[]
