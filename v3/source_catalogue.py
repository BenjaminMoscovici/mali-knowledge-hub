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


FRENCH_ANALYTICAL_USE = {
    'EU-funded learning with sampling and transferability limitations': 'apprentissage financé par l’UE, avec limites d’échantillonnage et de transférabilité',
    'actors and sectors present': 'acteurs et secteurs présents',
    'administrative geography/population': 'géographie administrative et population',
    'aid activity': 'activité d’aide',
    'approved action/amendment and original activity semantics audit': 'audit des actions/avenants approuvés et de la sémantique des activités originales',
    'development project': 'projet de développement',
    'displaced/returned/repatriated population stocks': 'stocks de populations déplacées, retournées et rapatriées',
    'echo programming': 'programmation ECHO',
    'eib project': 'projet BEI',
    'eu activity': 'activité de l’UE',
    'eu programming': 'programmation de l’UE',
    'eu project metadata': 'métadonnées de projet de l’UE',
    'eu tei': 'initiative Équipe Europe',
    'evaluation finding': 'constat d’évaluation',
    'food security classification': 'classification de la sécurité alimentaire',
    'funding aggregate': 'agrégat de financement',
    'future additional evidence layer': 'future couche de preuves supplémentaire',
    'national HPC planning observations': 'observations nationales de planification HPC',
    'needs, planned response, requirements, methods': 'besoins, réponse prévue, exigences et méthodes',
    'official national priorities': 'priorités nationales officielles',
    'project-ID actor/sector/location/donor and reported end-date relationships': 'relations entre identifiant de projet, acteur, secteur, lieu, bailleur et date de fin déclarée',
    'subnational people-in-need and targets': 'personnes dans le besoin et cibles infranationales',
}

FRENCH_STATUS = {
    'institutional_access_required': 'accès institutionnel requis',
    'integrated_with_limitations': 'intégrée avec des limites',
    'licence_review_required': 'examen de licence requis',
    'metadata_only': 'métadonnées uniquement',
    'not_current_enough': 'pas assez actuelle',
    'public_access_confirmed': 'accès public confirmé',
    'rejected_for_quality_or_safety': 'rejetée pour qualité ou sécurité',
}


def answer(documents=(), root=None, document_registry_available=True, language='English'):
    rows=entries(root)
    available=[r for r in rows if r['evidence_available']]
    pending=[r for r in rows if not r['evidence_available']]
    french=language=='French'
    cell=lambda value:str(value or ('non renseigné' if french else 'not reported')).replace('|','\\|').replace('\n',' ')
    lines=[('Le Hub combine des flux de sources ayant des finalités et des périodes de référence différentes. Le catalogue ci-dessous provient de leurs métadonnées d’intégration et des preuves chargées ; les dates de récupération ne rendent pas actuelles des observations historiques. Les noms de sources et les notes descriptives du registre versionné sont conservés dans leur langue d’origine.' if french else
            'The Hub combines source streams with different purposes and reference periods. The catalogue below comes from their onboarding metadata and loaded evidence; retrieval dates do not make historical observations current.'), '']
    if document_registry_available:
        titles=sorted({str(d['title']) for d in documents if d.get('title')})
        lines += [f'**Documents indexés : {len(titles)}**' if french else f'**Indexed documents: {len(titles)}**', *['- '+cell(title) for title in titles], '']
    else:
        lines += [('Le registre des documents indexés n’a pas pu être vérifié pour cette demande ; son contenu n’est pas déduit.' if french else
                   'The indexed-document registry could not be checked for this request; its contents are not inferred.'), '']
    lines += [('**Flux de preuves disponibles**' if french else '**Available evidence streams**'), '',
              ('| Source | Période de référence / récupération | Utile pour | Limites |' if french else
               '| Source | Reference period / retrieval | Useful for | Limits |'), '|---|---|---|---|']
    for row in available:
        if row.get('records') is not None:
            french_count='élément de preuve' if row['records']==1 else 'éléments de preuve'
            count=f" ; {row['records']:,} {french_count}" if french else f"; {row['records']:,} evidence records"
        else:
            count=''
        period=row.get('historical_coverage') or row.get('temporal_granularity') or ('variable selon la requête / non précisée' if french else 'query-dependent / not specified')
        if french:
            period=str(period).replace(' to ', ' au ')
        retrieved=str(row.get('last_successful_retrieval') or ('non renseigné' if french else 'not reported'))[:10]
        use=str(row.get('analytical_use') or 'see source description').replace('_',' ')
        if french:
            use=FRENCH_ANALYTICAL_USE.get(use, 'voir la description de la source' if use=='see source description' else use)
        limitations=' '.join(row.get('limitations') or []) or ('Aucune limite supplémentaire consignée dans ce catalogue ; cela ne prouve pas une utilisation analytique sans restriction.' if french else 'No additional limit recorded in this catalogue; this does not prove unrestricted analytical use.')
        retrieval_label='récupéré le' if french else 'retrieved'
        separator=' ; ' if french else '; '
        lines.append(f"| {cell(row['source_name'])}{count} | {cell(period)}{separator}{retrieval_label} {cell(retrieved)} | {cell(use)} | {cell(limitations)} |")
    if pending:
        lines += ['', ('**Sources cataloguées en attente de preuves, d’accès ou de qualification**' if french else '**Catalogued sources awaiting evidence, access or qualification**'), '',
                  ('| Source | État actuel | Contrainte |' if french else '| Source | Current status | Constraint |'), '|---|---|---|']
        for row in pending:
            status=str(row.get('integration_status') or 'not integrated')
            status=FRENCH_STATUS.get(status, 'non intégrée' if french and status=='not integrated' else status.replace('_',' '))
            constraint=' '.join(row.get('limitations') or []) or row.get('next_action') or ('Aucune preuve utilisable confirmée dans ce catalogue' if french else 'No usable evidence confirmed in this catalogue')
            lines.append(f"| {cell(row['source_name'])} | {cell(status)} | {cell(constraint)} |")
    lines += ['', ('Les décomptes d’éléments de preuve correspondent à des lignes sources ou à des faits extraits, et non à des nombres de projets, de personnes atteintes ou d’acteurs uniques. Le modèle de langage n’est pas une source.' if french else
                  'Evidence-record counts are source rows or extracted facts, not counts of projects, people reached or unique actors. The language model is not a source.')]
    return '\n'.join(lines)
