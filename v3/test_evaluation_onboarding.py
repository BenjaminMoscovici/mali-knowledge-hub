"""Study onboarding protects project identity, exact pages and existing evidence."""
from copy import deepcopy
import gzip,hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from evaluation_import import ingest
from project_learning_sources import package,retrieve_project_learning


def test_new_live_package_study_retains_pages_period_method_and_reported_reach():
    rows=retrieve_project_learning('Evaluation and reported reach for exact PADEL-Mali P160641')
    findings=[r for r in rows if r['source_type']=='evaluation_finding']
    assert len(findings)==3 and {r['page'] for r in findings}=={5,12,15}
    assert all('ICRR0024442' in r['locator'] and r['publication_date']=='2025-06-10' for r in findings)
    assert all(r['reference_period_start']=='2018-02-28' and r['reference_period_end']=='2024-06-28' for r in findings)
    reach=next(r for r in findings if 'reported_reach' in r['document_title'])
    assert '346,465' in reach['content'] and '340,000' in reach['content']
    assert 'not current local coverage' in reach['content']
    limits=next(r for r in findings if 'methodology_limits' in r['document_title'])
    assert 'counterfactual' in limits['content'] and 'surveys were implemented' in limits['content']
    assert 'PDF pages 12, 13' in limits['locator']
    assert all('retrospective' in r['content'] and 'no automatic transfer' in r['content'] for r in findings)
    assert not any('P144442' in r['content'] for r in findings)


def test_provider_label_and_family_follow_compatible_review_metadata(monkeypatch):
    import project_learning_sources as source
    data=deepcopy(package())
    r=next(r for r in data['records'] if r['dataset_id']=='mli-ieg-p160641')
    r['payload'].update(display_label='Independent study',source_family='Independent project evaluation')
    monkeypatch.setattr(source,'package',lambda:data)
    rows=source.retrieve_project_learning('What evaluations for exact P160641 with publisher metadata?')
    assert any(r['document_title'].startswith('Independent study P160641')
               and r['source_family']=='Independent project evaluation' for r in rows)


def test_partial_project_set_keeps_missing_study_lookup_separate_from_matching_findings():
    rows=retrieve_project_learning('Compare evaluations for exact World Bank P160641 and P513735')
    assert len([r for r in rows if r['source_type']=='evaluation_finding'])==3
    scope=next(r for r in rows if r['source_family']=='Evaluation lookup scope')
    assert "['P513735']" in scope['content'] and "['P160641', 'P513735']" not in scope['content']
    assert 'no evaluation exists elsewhere' in scope['content']


@pytest.fixture
def import_inputs(tmp_path,monkeypatch):
    import evaluation_import
    pdf=tmp_path/'review.pdf';pdf.write_bytes(b'checked source bytes')
    manifest=json.loads(Path(__file__).with_name('evaluation_padel_2025.json').read_text())
    manifest['sha256']=hashlib.sha256(pdf.read_bytes()).hexdigest()
    mpath=tmp_path/'review.json';mpath.write_text(json.dumps(manifest))
    base=tmp_path/'base.json.gz'
    with gzip.open(base,'wt') as f:json.dump({'tables':{},'records':[],'releases':{},'registry':[]},f)
    class PDF:
        def __enter__(self):return self
        def __exit__(self,*args):return None
        def __len__(self):return 16
        def __getitem__(self,index):return SimpleNamespace(get_text=lambda:'IEG ICRR0024442 PADEL-Mali (P160641)')
    monkeypatch.setattr(evaluation_import.pymupdf,'open',lambda _:PDF())
    return base,mpath,pdf,tmp_path/'output.json.gz',manifest


def test_reviewed_import_records_provenance_and_rejects_duplicate_release(import_inputs):
    base,mpath,pdf,out,m=import_inputs;ingest(base,mpath,pdf,out)
    with gzip.open(out,'rt') as f:data=json.load(f)
    assert len(data['records'])==3
    assert data['tables']['mkh_source_releases'][0]['checksum']==m['sha256']
    assert data['tables']['mkh_source_releases'][0]['publication_date']=='2025-06-10'
    assert data['records'][1]['locator']=='ICRR0024442 / P160641 / PDF pages 12, 13'
    with pytest.raises(ValueError,match='already integrated'):ingest(out,mpath,pdf,out)


def test_import_preserves_later_catalogue_review_annotations(import_inputs):
    base,mpath,pdf,out,_=import_inputs
    existing={'provider':'Existing provider','integration_status':'integrated_with_limitations',
              'next_action':'Preserve reviewed refresh instructions'}
    base.with_name('base_registry.json').write_text(json.dumps([existing]))
    ingest(base,mpath,pdf,out)
    catalogue=json.loads(out.with_name('output_registry.json').read_text())
    assert catalogue[0]==existing and len(catalogue)==2
    assert catalogue[1]['integration_status']=='integrated_with_limitations'


@pytest.mark.parametrize('change,pattern',[
    ({'sha256':'0'*64},'checksum'),({'project_id':'P513735'},'identity'),
    ({'report_number':'ICRR9999999'},'identity'),({'reference_end':'2030-01-01'},'period'),
    ({'methodology':''},'required'),({'findings':[{'finding_kind':'bad','pages':[17],'finding':'reviewed'}]},'page'),
])
def test_invalid_review_cannot_mutate_the_existing_source_package(import_inputs,change,pattern):
    base,mpath,pdf,out,m=import_inputs;m.update(change);mpath.write_text(json.dumps(m))
    original=base.read_bytes()
    with pytest.raises(ValueError,match=pattern):ingest(base,mpath,pdf,out)
    assert base.read_bytes()==original and not out.exists()
