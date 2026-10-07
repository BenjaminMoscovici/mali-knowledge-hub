"""User-facing source inventory from versioned onboarding metadata and records."""
from collections import Counter
import gzip
import json
from pathlib import Path


def entries(root=None):
    root=Path(root) if root else Path(__file__).parent
    base=json.loads((root/'source_registry.json').read_text())
    by_name={(r['provider'],r['source_name']):dict(r) for r in base}
    # The same onboarding format supplies catalogue descriptions and actual
    # imported record counts. A metadata-only source never becomes evidence.
    loaded={}
    for path in sorted(root.glob('source_wave*.json.gz')):
        try:
            with gzip.open(path,'rt',encoding='utf-8') as file:
                package=json.load(file)
            if not all(key in package for key in ('registry','records','tables')):
                continue
            counts=Counter(r['dataset_id'] for r in package['records'])
            datasets={d['title']:d for d in package['tables'].get('mkh_datasets',[])}
        except (OSError,ValueError,TypeError,KeyError):
            continue
        releases=package['tables'].get('mkh_source_releases',[])
        for source in package['registry']:
            row=dict(source); key=(row['provider'],row['source_name'])
            dataset=datasets.get(row['source_name'])
            if dataset:
                row['records']=counts[dataset['id']]
                source_releases=[r for r in releases if r['dataset_id']==dataset['id']]
                if source_releases:
                    release=max(source_releases,key=lambda r:r.get('retrieved_at') or '')
                    row['last_successful_retrieval']=release.get('retrieved_at')
                    row['historical_coverage']=f"{release.get('reference_start') or 'unknown'} to {release.get('reference_end') or 'unknown'}"
                    quality=release.get('quality_json') or {}
                    if isinstance(quality,str):
                        try:quality=json.loads(quality)
                        except ValueError:quality={}
                    if isinstance(quality,dict) and quality.get('limitations'):row['limitations']=quality['limitations']
                loaded[key]=row['records']>0
            by_name[key]=row
    result=[]
    for key,row in by_name.items():
        row['evidence_available']=loaded.get(key, row.get('records') is None and
            row.get('integration_status')=='integrated_with_limitations')
        if row.get('records') is not None and key not in loaded:
            row['records']=None
            row['evidence_available']=False
        result.append(row)
    return sorted(result,key=lambda r:(not r['evidence_available'],r['provider'],r['source_name']))


def answer(documents=(), root=None, document_registry_available=True):
    rows=entries(root)
    available=[r for r in rows if r['evidence_available']]
    pending=[r for r in rows if not r['evidence_available']]
    cell=lambda value:str(value or 'not reported').replace('|','\\|').replace('\n',' ')
    lines=['The Hub combines source streams with different purposes and reference periods. The catalogue below comes from their onboarding metadata and loaded evidence; retrieval dates do not make historical observations current.', '']
    if document_registry_available:
        titles=sorted({str(d['title']) for d in documents if d.get('title')})
        lines += [f'**Indexed documents: {len(titles)}**', *['- '+cell(title) for title in titles], '']
    else:
        lines += ['The indexed-document registry could not be checked for this request; its contents are not inferred.', '']
    lines += ['**Available evidence streams**', '', '| Source | Reference period / retrieval | Useful for | Limits |', '|---|---|---|---|']
    for row in available:
        count=f"; {row['records']:,} evidence records" if row.get('records') is not None else ''
        period=row.get('historical_coverage') or row.get('temporal_granularity') or 'query-dependent / not specified'
        retrieved=str(row.get('last_successful_retrieval') or 'not reported')[:10]
        use=str(row.get('analytical_use') or 'see source description').replace('_',' ')
        limitations=' '.join(row.get('limitations') or []) or 'No additional limit recorded in this catalogue; this does not prove unrestricted analytical use.'
        lines.append(f"| {cell(row['source_name'])}{count} | {cell(period)}; retrieved {cell(retrieved)} | {cell(use)} | {cell(limitations)} |")
    if pending:
        lines += ['', '**Catalogued sources awaiting evidence, access or qualification**', '', '| Source | Current status | Constraint |', '|---|---|---|']
        for row in pending:
            lines.append(f"| {cell(row['source_name'])} | {cell(str(row.get('integration_status') or 'not integrated').replace('_',' '))} | {cell(' '.join(row.get('limitations') or []) or row.get('next_action') or 'No usable evidence confirmed in this catalogue')} |")
    lines += ['', 'Evidence-record counts are source rows or extracted facts, not counts of projects, people reached or unique actors. The language model is not a source.']
    return '\n'.join(lines)
