import ast
import gzip
import json
from pathlib import Path
from source_catalogue import entries,answer


def test_actual_loaded_counts_do_not_promote_public_access_or_metadata_to_evidence():
    rows=entries()
    wb=next(r for r in rows if r['source_name'].startswith('World Bank Projects'))
    assert wb['evidence_available'] and wb['records']==215
    eu=next(r for r in rows if r['source_name']=='Mali EU IATI country activity subset')
    assert eu['evidence_available'] and eu['records']==306
    pending=[r for r in rows if not r['evidence_available']]
    assert any('MTR2024' in r['source_name'] for r in pending)
    assert any('AAP 2024' in r['source_name'] for r in pending)
    assert any('5W' in r['source_name'] for r in pending)


def test_new_stream_and_updated_records_use_onboarding_contract_without_code_changes(tmp_path):
    (tmp_path/'source_registry.json').write_text('[]')
    metadata={'provider':'Test donor','source_name':'New study','analytical_use':'historical evaluation findings',
              'integration_status':'metadata_only','limitations':['Old registry limit'],'records':999}
    package={'registry':[metadata],'records':[{'dataset_id':'study'}],
        'tables':{'mkh_datasets':[{'id':'study','title':'New study'}],
          'mkh_source_releases':[{'dataset_id':'study','retrieved_at':'2026-10-07','reference_start':'2024-01-01',
            'reference_end':'2024-12-31','quality_json':{'limitations':['Historical study, not current delivery.']}}]}}
    path=tmp_path/'source_wave6.json.gz'
    def write():
        with gzip.open(path,'wt') as f:json.dump(package,f)
    write(); row=entries(tmp_path)[0]
    assert row['evidence_available'] and row['records']==1
    assert row['historical_coverage']=='2024-01-01 to 2024-12-31'
    assert row['limitations']==['Historical study, not current delivery.']
    package['records'].append({'dataset_id':'study'});write()
    assert entries(tmp_path)[0]['records']==2
    assert '999' not in answer(root=tmp_path)


def test_missing_or_unreadable_snapshot_does_not_reuse_old_imported_counts(tmp_path):
    row={'provider':'Donor','source_name':'Study','records':999,'integration_status':'integrated_with_limitations'}
    (tmp_path/'source_registry.json').write_text(json.dumps([row]))
    (tmp_path/'source_wave6.json.gz').write_bytes(b'broken update')
    result=entries(tmp_path)[0]
    assert result['records'] is None and not result['evidence_available']


def test_document_updates_and_registry_failure_do_not_infer_old_or_absent_documents():
    assert '**Indexed documents: 1**' in answer([{'title':'New local plan'}])
    assert 'New local plan' in answer([{'title':'New local plan'}])
    failed=answer(document_registry_available=False)
    assert 'contents are not inferred' in failed and 'Indexed documents: 0' not in failed


def test_real_inventory_entry_point_uses_current_document_registry_and_preserves_failure_scope():
    for filename in ['analysis_core.py','app.py']:
        tree=ast.parse(Path(__file__).with_name(filename).read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='source_inventory_answer')
        ns={'get_document_groups':lambda:{'documents':[{'title':'Updated document'}]}}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-inventory','exec'),ns)
        assert 'Updated document' in ns[fn.name]()
        def failure():raise RuntimeError('registry unavailable')
        ns['get_document_groups']=failure
        result=ns[fn.name]()
        assert 'could not be checked' in result and 'MALI 3W_Q1_2026' in result
