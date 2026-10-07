"""Onboard reviewed study findings without changing analytical retrieval code."""
import argparse
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re
import pymupdf
from analytical_import import Package


def ingest(base, manifest_path, pdf_path, output):
    manifest=json.loads(Path(manifest_path).read_text())
    pdf_path=Path(pdf_path)
    if manifest.get('schema_version')!=1 or hashlib.sha256(pdf_path.read_bytes()).hexdigest()!=manifest['sha256']:
        raise ValueError('Review manifest or original PDF checksum mismatch')
    project_id=manifest['project_id']
    if not re.fullmatch(r'P\d{6}',project_id):
        raise ValueError('Project-ID adapter requires an exact World Bank project identifier')
    start,end,published=[date.fromisoformat(manifest[k]) for k in ('reference_start','reference_end','publication_date')]
    if start>end or published<end:
        raise ValueError('Study reference period or publication date conflict')
    findings=manifest['findings']
    if not 1<=len(findings)<=10 or len({r['finding_kind'] for r in findings})!=len(findings):
        raise ValueError('Empty, excessive or duplicate finding types')
    records=[]
    with pymupdf.open(pdf_path) as pdf:
        header=pdf[0].get_text()
        if project_id not in header or manifest['report_number'] not in header:
            raise ValueError('Exact project or report identity not present in PDF header')
        for finding in findings:
            pages=finding['pages']
            if not pages or any(not isinstance(p,int) or isinstance(p,bool) or p<1 or p>len(pdf) for p in pages):
                raise ValueError('Finding has an invalid PDF page')
            if not all(isinstance(v,str) and v.strip() for v in
                       [finding['finding'],manifest['methodology'],manifest['transferability'],manifest['document_title']]):
                raise ValueError('Finding, methodology, title and transferability are required')
            records.append({'source_type':'evaluation_finding',
                'reference_start':manifest['reference_start'],'reference_end':manifest['reference_end'],'page':pages[0],
                'locator':f'{manifest["report_number"]} / {project_id} / PDF pages '+', '.join(map(str,pages)),
                'payload':{'project_id':project_id,'finding_kind':finding['finding_kind'],'finding':finding['finding'],
                    'page':pages[0],'methodology':manifest['methodology'],'transferability':manifest['transferability'],
                    'document_title':manifest['document_title'],'geography':{'country':'Mali'},
                    'source_family':manifest['source_family'],'display_label':manifest['display_label']}})
    package=Package()
    with gzip.open(base,'rt',encoding='utf-8') as file:package.data=json.load(file)
    catalogue_path=Path(base).with_name(Path(base).name.replace('.json.gz','_registry.json'))
    catalogue=json.loads(catalogue_path.read_text()) if catalogue_path.exists() else deepcopy_registry(package.data['registry'])
    dataset_id=manifest['dataset_id']
    # Reject duplicate imports and conflicting bytes rather than changing an
    # existing reviewed release or silently duplicating its findings.
    if dataset_id in package.data['releases']:
        release=next(r for r in package.data['tables']['mkh_source_releases'] if r['dataset_id']==dataset_id)
        if release['checksum']!=manifest['sha256']:
            raise ValueError('Dataset already has a different immutable source release')
        raise ValueError('Reviewed source release is already integrated')
    package.add(pdf_path,manifest['source_id'],dataset_id,manifest['provider'],manifest['source_name'],
        manifest['source_url'],'Public factual findings/paraphrases only; full-text reproduction rights not assumed',
        manifest['metadata_url'],manifest['report_number']+'; reviewed '+manifest['publication_date'],records,
        manifest['limitations'],'historical Mali project; source-reported reach only',
        publication=manifest['publication_date'],metadata_url=manifest['metadata_url'])
    release=package.data['tables']['mkh_source_releases'][-1]
    release['transformation']='reviewed-evaluation/1; human-checked short factual paraphrases; exact project/report identity, source checksum and PDF pages verified'
    package.save(Path(output))
    # The external catalogue can contain later reviewed status/maintenance
    # annotations. Preserve them rather than restoring the old import defaults.
    row=dict(package.data['registry'][-1]);row['integration_status']='integrated_with_limitations'
    row['next_action']='refresh reviewed findings on provider updates; retain exact project, pages and methodological limits'
    Path(output).with_name(Path(output).name.replace('.json.gz','_registry.json')).write_text(
        json.dumps(catalogue+[row],ensure_ascii=False,indent=2)+'\n')


def deepcopy_registry(rows):
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('base',type=Path);parser.add_argument('manifest',type=Path)
    parser.add_argument('pdf',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();ingest(args.base,args.manifest,args.pdf,args.output)
