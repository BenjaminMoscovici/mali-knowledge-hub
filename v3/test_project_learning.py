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


def test_explicit_closing_year_does_not_return_overdue_or_next_year_examples():
    rows=retrieve_project_learning('Which World Bank projects have reported closing dates in 2027?')
    profiles=[r for r in rows if r['source_type']=='development_project' and r['document_title'].startswith('World Bank —')]
    assert profiles
    assert all('reported closing date 2027-' in r['content'] for r in profiles)
    scope=next(r for r in rows if r['document_title']=='World Bank Mali project profile scope')
    assert 'calendar year 2027, not a rolling 180-day window' in scope['content']
    assert all('closing date does not prove completion' in r['content'] for r in profiles)


def test_exact_project_evaluation_lookup_does_not_import_another_projects_findings():
    rows=retrieve_project_learning('Evaluation findings for exact World Bank P513735; no unrelated studies please')
    assert not any(r['source_type']=='evaluation_finding' for r in rows)
    scope=next(r for r in rows if r['source_family']=='Evaluation lookup scope')
    assert "['P513735']" in scope['content'] and '3 findings for 1 project IDs' in scope['content']
    assert 'no evaluation exists elsewhere' in scope['content']
    assert any('World Bank — P513735' in r['document_title'] for r in rows)


def test_new_compatible_study_is_browsed_and_identified_from_loaded_metadata(monkeypatch):
    from copy import deepcopy
    import project_learning_sources as source
    data=deepcopy(package())
    finding=deepcopy(next(r for r in data['records'] if r['source_type']=='evaluation_finding'))
    finding.update(id='synthetic-new-study',locator='Synthetic IEG review / P513735 / PDF page 10')
    finding['payload'].update(project_id='P513735',page=10,document_title='Synthetic newly loaded evaluation',
                              finding='A documented lesson with its own project identifier.')
    data['records'].append(finding)
    monkeypatch.setattr(source,'package',lambda:data)
    rows=source.retrieve_project_learning('What lessons are in newly available evaluations?')
    evaluations=[r for r in rows if r['source_type']=='evaluation_finding']
    assert any('IEG P513735' in r['document_title'] and 'Synthetic newly loaded evaluation' in r['content']
               and 'Synthetic IEG review / P513735' in r['content'] for r in evaluations)
    assert len(evaluations)==4
    assert all('Transferability:' in r['content'] for r in evaluations)


def test_empty_evaluation_collection_has_scoped_gap_instead_of_project_examples(monkeypatch):
    from copy import deepcopy
    import project_learning_sources as source
    data=deepcopy(package());data['records']=[r for r in data['records'] if r['source_type']!='evaluation_finding']
    monkeypatch.setattr(source,'package',lambda:data)
    rows=source.retrieve_project_learning('What lessons are available in the refreshed evaluation collection?')
    assert len(rows)==1 and rows[0]['source_family']=='Evaluation lookup scope'
    assert '0 findings for 0 project IDs' in rows[0]['content']
