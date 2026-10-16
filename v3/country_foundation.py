"""Cited, deterministic country facts over existing MKH identities and releases.

The overlay adds only previously unused printed attributes and derived COD
geometry metrics. Population and names remain in the original source store.
There are no runtime network requests, model calls or database writes.
"""
from collections import Counter, defaultdict
from functools import lru_cache
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from threading import Lock

from geographic_model import geographic_model
from source_wave import _fold, snapshot_path

OVERLAY = Path(__file__).with_name('country_foundation.sqlite.gz')
_lock = Lock()
VALID_LEVELS = {'country','region','cercle','commune','arrondissement','locality'}
STOP_NAMES = {'mali','what','which','there','here','are','the','and','how','full','parent','path',
              'name','region','cercle','commune','locality','population','compare','rural','urban',
              'entre','dans','pour','les','des','une','qui','plus','moins','grand','petit'}


def country_plan(question):
    """Bounded factual intents only; mixed analytical questions retain research."""
    from country_physical import physical_plan
    physical=physical_plan(question)
    if physical:return physical
    from country_climate import climate_plan
    climate=climate_plan(question)
    if climate:return climate
    from country_indicators import indicator_plan
    indicator=indicator_plan(question)
    if indicator:return indicator
    q = _fold(question)
    if len(q)>1500 or re.search(r'\b(projects?|projets?|fund\w*|financ\w*|needs?|besoins?|'
            r'conflict\w*|security|securite|displace\w*|deplace\w*|humanitaire|humanitarian|'
            r'politic\w*|institution\w*|actors?|acteurs?|recommend\w*|priorit\w*|why|pourquoi|'
            r'impact|affect\w*|explain|explique\w*|planification|planning|scenario\w*|forecast\w*|prevision\w*|hub|datasets?|documents?|sources?|available|coverage|evidence|women|men|female|male|femmes?|hommes?)\b',q):
        return None
    population = bool(re.search(r'\b(population|populations|populated|peuplee?s?|peuples?|habitants?|einwohner\w*|density|densite|bevolkerungsdichte)\b',q))
    area = bool(re.search(r'\b(area|areas|surface|superficie|superficies|flache|flachen)\b',q))
    borders = bool(re.search(r'\b(neighbou?rs?|adjacen\w*|border\w*|limitroph\w*|voisin\w*|nachbar\w*|grenz\w*)\b',q))
    residence = population and bool(re.search(r'\b(urban|urbain\w*|rural\w*|stadt\w*|landlich\w*)\b',q))
    if not (population or area or borders): return None
    # Do not let a demographic route swallow infrastructure or service analytics.
    if re.search(r'\b(health|sante|schools?|ecoles?|education|wash|water|eau|roads?|routes?|'
                 r'access\w*|services?|hospitals?|climat\w*|econom\w*|livelihood\w*|transport\w*|electricity|electricite|sanitation|assainissement|gdp|pib|enrol\w*)\b',q):
        return None
    metric = 'residence' if residence else 'population' if population else 'area' if area else 'neighbours'
    if population and (area or borders): metric = 'incompatible_join'
    if re.search(r'\b(density|densite|bevolkerungsdichte)\b',q): metric='incompatible_join'
    # A year in the request is a real constraint, never silently replaced by 2023.
    years = re.findall(r'\b(?:19|20)\d{2}\b',q)
    if population and (any(y!='2023' for y in years) or re.search(r'\b(current|currently|today|actuel\w*|aujourd hui|heute|aktuell\w*)\b',q)):
        metric='unavailable_period'
    levels=[]
    for label,level in [('regions?|regionen','region'),('cercles?','cercle'),('communes?|municipalit(?:y|ies)|gemeinden?','commune'),
                        ('arrondissements?','arrondissement'),('localit(?:y|ies|e|es)|villages?','locality')]:
        for match in re.finditer(r'\b(?:'+label+r')\b',q):levels.append((match.start(),level,match[0]))
    levels.sort()
    level=levels[0][1] if levels else None
    scope_level=next((l for _,l,_ in levels[1:] if l!=level), None)
    ranking=population and bool(re.search(r'\b(top|rank\w*|largest|smallest|most|least|classe\w*|plus peuple\w*|moins peuple\w*|gro(?:ss|sste)\w*|kleinste\w*)\b',q))
    if ranking and metric=='population':metric='ranking'
    # Geographic area / density ranking needs a separate supported query.
    if not population and re.search(r'\b(largest|smallest|top|rank\w*|plus grande?s?|plus petite?s?)\b',q):
        metric='area_ranking_unavailable'
    limit_match=re.search(r'\b(?:top|first|premier\w*)\s+(\d{1,3})\b',q)
    if not limit_match and ranking:limit_match=re.search(r'\b(\d{1,3})\s+(?:communes|regions|cercles|localities|localites)\b',q)
    limit=min(50,max(1,int(limit_match[1]))) if limit_match else 10 if ranking else 50
    order='asc' if re.search(r'\b(smallest|least|moins|kleinste\w*)\b',q) else 'desc'
    # Only actual exact names from the existing model, preserving homonyms.
    names=[n for n in geographic_model().retrieval_place_names(question) if n not in STOP_NAMES]
    # Localities are intentionally opt-in to avoid treating ordinary words as villages.
    if level=='locality':
        words=q.split();model=geographic_model()
        names=sorted({' '.join(words[i:i+s]) for i in range(len(words)) for s in range(1,min(model.max_name_words,len(words)-i)+1)
            if ' '.join(words[i:i+s]) not in STOP_NAMES and len(' '.join(words[i:i+s]))>2
            and model.lookup(' '.join(words[i:i+s]),'locality',model.preferred)})
        names=[n for n in names if not any(n!=other and (' '+n+' ') in (' '+other+' ') for other in names)]
    comparison=bool(re.search(r'\b(compare\w*|comparaison|vergleich\w*)\b',q))
    incomplete_comparison=False
    if comparison:
        remainder=' '+q+' '
        for name in sorted(names,key=len,reverse=True):remainder=remainder.replace(' '+name+' ',' ')
        grammar={'compare','compares','comparing','comparez','comparer','comparaison','the','of','and','et','und','de','du','des','la','le','les',
                 'population','populations','in','en','au','mali','region','regions','cercle','cercles','commune','communes','with','to',
                 'for','2023','between','entre','by'}
        incomplete_comparison=any(token not in grammar for token in remainder.split())
    unknown_place=False
    for match in re.finditer(r'\b(?:of|in|von|du) (?:the )?(.+?) (region|cercle|commune|locality)\b',q):
        name=match[1]
        if not re.search(r'\b(and|et|und|in|of|de|du|population|most|least|top|urban|rural)\b',name):
            if not geographic_model().lookup(name,match[2],geographic_model().preferred):unknown_place=True
    return {'metric':metric,'level':level,'scope_level':scope_level,'names':names,'unknown_place':unknown_place,
            'comparison':comparison,'incomplete_comparison':incomplete_comparison,
            'national':bool(re.search(r'\bmali\b',q)), 'limit':limit,'order':order,
            'international':bool(re.search(r'\b(countries|country borders|pays|international\w*|lander)\b',q)),
            'question':question}


class CountryFoundation:
    def __init__(self):
        self.model=geographic_model()
        overlay=sqlite3.connect(':memory:')
        overlay.deserialize(gzip.decompress(OVERLAY.read_bytes()))
        overlay.row_factory=sqlite3.Row
        self.validation=json.loads(overlay.execute("select value_json from foundation_metadata where key='validation'").fetchone()[0])
        for rid,record in self.validation['source_releases'].items():
            release=self.model.releases.get(rid)
            if not release or release['checksum']!=record['checksum']:
                raise ValueError('Country overlay does not match source release')
        self.attributes={r['unit_id']:dict(r) for r in overlay.execute('select * from foundation_attributes')}
        self.metrics={r['unit_id']:dict(r) for r in overlay.execute('select * from foundation_boundary_metrics')}
        self.relations=[dict(r) for r in overlay.execute('select * from foundation_boundary_relations')]
        overlay.close()
        self.cod=next(rid for rid,r in self.model.releases.items() if r['dataset_id']=='mli-cod-ab')
        self.populations=defaultdict(dict)
        db=sqlite3.connect(f'file:{snapshot_path()}?mode=ro',uri=True)
        try:
            for uid,sex,value in db.execute('select unit_id,sex,value from mkh_population_observations where release_id=?',(self.model.preferred,)):
                self.populations[uid][sex]=value
        finally:db.close()
        if len(self.populations)!=len(self.attributes):
            raise ValueError('Incomplete country population store')

    def select(self,level=None,name=None,scope_level=None,scope=None,release=None):
        release=release or self.model.preferred
        if level and level not in VALID_LEVELS:raise ValueError('Invalid geographic level')
        if name:
            rows=self.model.lookup(name,level,release)
        else:
            rows=[self.model.describe(u['id']) for u in self.model.units.values()
                  if u['release_id']==release and (not level or u['level']==level)]
        if scope:
            parents=self.model.lookup(scope,scope_level,release)
            if len(parents)!=1:
                return [],'ambiguous_scope' if parents else 'unknown_scope'
            pid=parents[0]['id']
            rows=[u for u in rows if any(p['id']==pid for p in u['path'])]
        return rows,None

    def population_rows(self,level,name=None,scope_level=None,scope=None,order='desc',limit=50,ranking=False):
        rows,error=self.select(level,name,scope_level,scope)
        if error:return {'status':error,'rows':[]}
        result=[]
        for u in rows:
            if u['id'] not in self.populations:continue
            attr=self.attributes[u['id']]
            result.append({'unit_id':u['id'],'name':u['name'],'level':u['level'],'unit_type':u['unit_type'],
                'path':u['path'],'population':self.populations[u['id']], 'residence':attr['residence'],
                'reported_localities':attr['reported_localities'],'span_id':attr['span_id'],
                'locator':u['locator'],'release_id':u['release_id'],'reference_year':2023})
        result.sort(key=lambda r:((1 if order=='asc' else -1)*r['population']['total'],
                                  [p['name'] for p in r['path']],r['unit_id']))
        if ranking:
            last=None;rank=0
            for i,r in enumerate(result,1):
                if r['population']['total']!=last:rank=i
                r['rank']=rank;last=r['population']['total']
        return {'status':'ok' if result else 'no_match','rows':result[:limit],
                'candidate_count':len(result),'omitted_count':max(0,len(result)-limit),
                'basis':'Published totals at the selected level in the INSTAT 2023 release; no sum across levels.',
                'candidate_ids':[r['unit_id'] for r in result]}

    def spatial_rows(self,metric,level,name):
        if level in ('commune','locality','arrondissement'):
            return {'status':'no_geometry_at_level','rows':[]}
        if metric=='neighbours' and level=='country':
            return {'status':'no_crosscountry_geometry','rows':[]}
        rows,error=self.select(level,name,release=self.cod)
        if not name or len(rows)!=1:
            return {'status':'ambiguous_place' if rows else 'no_match','rows':[],
                    'candidates':[{'name':u['name'],'level':u['level']} for u in rows[:20]]}
        u=rows[0];value=self.metrics[u['id']]
        result={'unit_id':u['id'],'name':u['name'],'level':u['level'],'unit_type':u['unit_type'],
                'path':u['path'],'release_id':self.cod,**value}
        if metric=='neighbours':
            result['neighbours']=[]
            for rel in self.relations:
                if rel['relation']!='shared_border' or u['id'] not in (rel['from_unit_id'],rel['to_unit_id']):continue
                other=rel['to_unit_id'] if rel['from_unit_id']==u['id'] else rel['from_unit_id']
                peer=self.model.units[other]
                result['neighbours'].append({'unit_id':other,'name':peer['name'],
                    'level':peer['level'],'shared_border_m':rel['shared_border_m']})
            result['neighbours'].sort(key=lambda n:_fold(n['name']))
        return {'status':'ok','rows':[result],
            'basis':'COD v03 polygons only. Shared-line border >1 metre, overlap <=1 m²; point contacts excluded. No INSTAT population join.'}

    def geometry(self,level,name=None):
        if level not in ('country','region','cercle'):
            return {'type':'FeatureCollection','features':[],
                    'status':'no_geometry_at_level'}
        rows,error=self.select(level,name,release=self.cod)
        if error:raise ValueError(error)
        ids={r['id'] for r in rows}
        db=sqlite3.connect(f'file:{snapshot_path()}?mode=ro',uri=True)
        try:
            features=[]
            for uid,geometry in db.execute('select id,geometry_json from mkh_geo_units where release_id=? and level=?',(self.cod,level)):
                if uid not in ids:continue
                u=self.model.units[uid];m=self.metrics[uid]
                features.append({'type':'Feature','id':uid,'geometry':json.loads(geometry),
                    'properties':{'name':u['name'],'level':level,'release_id':self.cod,
                        'boundary_version':u['boundary_version'],'area_km2_derived':m['area_km2'],
                        'source_url':self.model.releases[self.cod]['source_url'],
                        'source_record_id':u['original_record_id'],
                        'population_join':'not approved; no population attached'}})
            return {'type':'FeatureCollection','features':features,'status':'ok' if features else 'no_match'}
        finally:db.close()

    def residence(self,name='Mali',level='country'):
        scope,error=self.select(level,name)
        if error or len(scope)!=1:return {'status':'ambiguous_scope' if scope else 'no_match','rows':[]}
        uid=scope[0]['id'];partitions=[]
        for pid,pop in self.populations.items():
            u=self.model.units[pid]
            if u['level'] not in ('commune','arrondissement'):continue
            if any(p['id']==uid for p in self.model.path(pid)):partitions.append(pid)
        if not partitions:return {'status':'no_partition_at_level','rows':[]}
        sums=Counter();counts=Counter()
        for pid in partitions:
            category=self.attributes[pid]['residence']
            sums[category]+=self.populations[pid]['total'];counts[category]+=1
        total=sum(sums.values());published=self.populations[uid]['total']
        return {'status':'ok','scope_name':scope[0]['name'],'scope_unit_id':uid,'rows':[
                {'residence':c,'population':sums[c],'administrative_units':counts[c],
                 'share_of_partition_sum_pct':100*sums[c]/total if total else None} for c in ('U','R')],
            'partition_sum':total,'published_scope_total':published,'sum_minus_published':total-published,
            'candidate_ids':partitions,'release_id':self.model.preferred,
            'basis':'Sum of disjoint commune and Bamako arrondissement totals; classification inherited by all their localities per INSTAT page 7. Share denominator is the partition sum. Rounding differences retained.'}

    def evidence(self,data,metric):
        spatial=metric in ('area','neighbours');rid=self.cod if spatial else self.model.preferred
        release=self.model.releases[rid]
        ids=[r['unit_id'] for r in data.get('rows',[]) if 'unit_id' in r]
        if metric=='residence':ids=[data['scope_unit_id']]
        pages=sorted({self.model.spans[uid]['page'] for uid in ids if uid in self.model.spans})
        passages=[{'unit_id':uid,**{k:self.model.spans[uid].get(k) for k in ('page','printed_page','locator','passage')}}
                  for uid in ids if uid in self.model.spans]
        return {'evidence_id':'E01','source_type':'official_geography_registry' if spatial else 'official_population_table',
            'source_family':'Mali Country Knowledge Foundation', 'document_title':release['title'],
            'organization':release['provider'],'version':release['upstream_version'],'release_id':rid,
            'record_id':ids[0] if ids else rid,'source_endpoint':release['source_url'],
            'retrieved_at':release['retrieved_at'],'publication_date':release['publication_date'],
            'reference_period_start':None if spatial else '2023-01-01',
            'reference_period_end':None if spatial else '2023-12-31',
            'geographic_scope':'COD v03 polygons' if spatial else 'INSTAT 2023 administrative framework',
            'page':pages[0] if pages else None,
            'locator':('PDF pages '+', '.join(map(str,pages))) if pages else 'COD v03 source polygon identities',
            'content':json.dumps({'result':data,'source_rows':passages,'source_checksum':release['checksum'],
                'publication_month':json.loads(release['quality_json']).get('publication_month'),
                'limitations':self.validation['limitations']},ensure_ascii=False)}

    def answer(self,question,language='English'):
        plan=country_plan(question)
        if not plan:return None
        if plan['metric'] in ('terrain','physical_rivers'):
            from country_physical import physical_answer
            return physical_answer(question,language)
        if plan['metric']=='climate':
            from country_climate import climate_answer
            return climate_answer(question,language)
        if plan['metric']=='indicator':
            from country_indicators import indicator_answer
            return indicator_answer(question,language)
        metric=plan['metric'];fr=language=='French';de=language=='German'
        def tr(en,frs,des):return des if de else frs if fr else en
        if metric in ('incompatible_join','unavailable_period','area_ranking_unavailable') or plan['international']:
            answer=tr('This country table cannot establish that result. Population estimates refer to 2023; polygon areas and borders belong to COD v03. Their identity crosswalks are not approved, so density or combined population–area comparisons would be unsupported. Cross-country boundaries and area rankings are not available on this route.',
                'Cette table ne permet pas d’établir ce résultat. Les populations se réfèrent à 2023; les superficies et limites relèvent de COD v03. Les correspondances ne sont pas approuvées : aucune densité ou comparaison population–superficie ne peut être établie. Les frontières internationales et classements de superficie ne sont pas disponibles ici.',
                'Diese Tabelle belegt das angefragte Ergebnis nicht. Die Bevölkerungswerte beziehen sich auf 2023; Flächen und Nachbarschaften stammen aus COD v03. Die Zuordnungen sind nicht freigegeben. Dichten und kombinierte Vergleiche wären daher unbelegt; internationale Grenzen und Flächenranglisten sind hier nicht verfügbar.')
            return {'answer':answer,'evidence':[],'country':{'status':metric},'family_counts':{}}
        names=plan['names'];level=plan['level'];scope=None;scope_level=plan['scope_level']
        if scope_level:
            scope_names=[n for n in names if self.model.lookup(n,scope_level,self.cod if metric in ('area','neighbours') else self.model.preferred)]
            if len(scope_names)==1:scope=scope_names[0]
            else:return {'answer':tr('Specify one unambiguous parent place and level.','Précisez un lieu parent et son niveau sans ambiguïté.','Bitte einen eindeutigen übergeordneten Ort mit Verwaltungsebene angeben.'),'evidence':[],'country':{'status':'ambiguous_scope'}}
        targets=[n for n in names if n!=scope]
        if plan['unknown_place']:
            data={'status':'unknown_requested_place','rows':[]}
        elif plan['incomplete_comparison'] or (plan['comparison'] and names and len(targets)<2):
            data={'status':'incomplete_comparison','rows':[]}
        elif metric in ('area','neighbours'):
            if not level and plan['national'] and not targets:level='country'
            data=self.spatial_rows(metric,level,targets[0] if len(targets)==1 else 'Mali' if plan['national'] and not targets else None)
        elif metric=='residence':
            data=self.residence(targets[0] if len(targets)==1 else 'Mali' if plan['national'] else '',level or 'country')
        else:
            if not level and plan['national'] and not names:level='country'
            if metric=='ranking' and not level:data={'status':'specify_level','rows':[]}
            elif not targets and not plan['national'] and not scope:
                data={'status':'specify_place','rows':[]}
            elif len(targets)>1:
                # Named comparisons use the requested level and identical release.
                if not level:data={'status':'specify_level','rows':[]}
                else:
                    parts=[self.population_rows(level,n,scope_level,scope) for n in targets]
                    data={'status':'ok' if all(p['status']=='ok' for p in parts) else 'no_match',
                          'rows':[r for p in parts for r in p['rows']],
                          'basis':'Named units at the same level and INSTAT 2023 release; published totals, not a cross-level sum.'}
            else:
                data=self.population_rows(level,targets[0] if targets else None,scope_level,scope,plan['order'],plan['limit'],metric=='ranking')
        if data['status']!='ok':
            answer=tr('No verified result for that selection. Specify the exact place, administrative level and parent where names repeat. COD v03 has country, region and cercle polygons; commune/locality areas and borders are unavailable.',
                'Aucun résultat vérifié pour cette sélection. Précisez le lieu exact, le niveau et le parent en cas d’homonymie. COD v03 contient des polygones nationaux, régionaux et de cercle; les superficies et limites des communes/localités ne sont pas disponibles.',
                'Für diese Auswahl liegt kein gesichertes Ergebnis vor. Bitte Ort, Verwaltungsebene und bei gleichen Namen den übergeordneten Ort angeben. COD v03 enthält Landes-, Regional- und Cercle-Polygone; Flächen und Grenzen von Gemeinden/Ortschaften fehlen.')
            return {'answer':answer,'evidence':[],'country':data,'family_counts':{}}
        lines=[]
        if metric in ('population','ranking'):
            rows=data['rows']
            intro=tr('Population estimates for **2023**, based on RGPH5 2022 and DNP projections, in the 2023 administrative framework (publication: January 2026).',
                     'Estimations de population pour **2023**, issues du RGPH5 2022 et des projections DNP, selon le découpage de 2023 (publication : janvier 2026).',
                     'Bevölkerungsschätzungen für **2023**, auf Grundlage des RGPH5 2022 und der DNP-Projektionen, nach der Gebietsstruktur von 2023 (veröffentlicht im Januar 2026).')
            lines=[intro+' [E01]','',tr('| Place and level | Population | Male | Female | U/R |','| Lieu et niveau | Population | Hommes | Femmes | U/R |','| Ort und Ebene | Bevölkerung | Männer | Frauen | U/R |'), '|---|---:|---:|---:|:---:|']
            for r in rows:
                path=' → '.join(p['name'] for p in r['path'][1:]) or 'Mali'
                rank=str(r['rank'])+'. ' if 'rank' in r else ''
                p=r['population']
                lines.append(f"| {rank}{path} ({r['unit_type']}) | {p['total']:,} | {p['male']:,} | {p['female']:,} | {r['residence'] or '—'} |")
            lines+=['','[E01] '+tr('Published totals are retained; sex subtotals can differ by one person through rounding. U/R denotes the publisher’s urban/rural administrative classification, not built-up land cover.',
                'Les totaux publiés sont conservés; les sous-totaux par sexe peuvent différer d’une personne par arrondi. U/R désigne le classement administratif urbain/rural de l’éditeur, pas l’occupation du sol.',
                'Veröffentlichte Summen bleiben erhalten; Rundungen können Abweichungen von einer Person zwischen den Geschlechtern und der Gesamtsumme ergeben. U/R ist die administrative Stadt-/Land-Klassifikation des Herausgebers, keine Landbedeckung.')]
            if data.get('omitted_count'):lines.append(tr(f"Showing {len(rows)} of {data['candidate_count']} matching units.",f"{len(rows)} unités affichées sur {data['candidate_count']}.",f"Angezeigt: {len(rows)} von {data['candidate_count']} passenden Einheiten."))
            if metric=='ranking' and level=='commune':lines.append(tr(
                'Bamako is represented by seven arrondissements in this edition; they are not included as communes in this ranking.',
                'Bamako est représenté par sept arrondissements dans cette édition; ils ne sont pas classés comme communes ici.',
                'Bamako ist in dieser Ausgabe durch sieben Arrondissements vertreten; diese werden hier nicht als Gemeinden eingereiht.')+' [E01]')
            gaps=[g for g in self.validation['locality_count_discrepancies'] if any(r['unit_id']==g['unit_id'] for r in rows)]
            if gaps:lines.append(tr('Locality-count warning: ','Avertissement sur le nombre de localités : ','Hinweis zur Ortszahl: ')+ '; '.join(f"{g['name']}: {g['reported']} reported, {g['enumerated']} enumerated" for g in gaps)+'. [E01]')
        elif metric=='area':
            r=data['rows'][0]
            lines=[tr(f"**{r['name']} ({r['unit_type']}): approximately {r['area_km2']:,.1f} km²**, calculated from its COD v03 polygon on the WGS84 ellipsoid.",
                f"**{r['name']} ({r['unit_type']}) : environ {r['area_km2']:,.1f} km²**, calculés à partir du polygone COD v03 sur l’ellipsoïde WGS84.",
                f"**{r['name']} ({r['unit_type']}): etwa {r['area_km2']:,.1f} km²**, aus dem COD-v03-Polygon auf dem WGS84-Ellipsoid berechnet.")+' [E01]',
                tr('This is a derived polygon area, not an official surveyed area or an approved INSTAT population boundary.',
                   'Il s’agit d’une superficie dérivée du polygone, pas d’une superficie cadastrale officielle ni d’une limite INSTAT approuvée pour joindre la population.',
                   'Dies ist eine berechnete Polygonfläche, keine amtlich vermessene Fläche oder freigegebene Grenze zur Verknüpfung mit INSTAT-Bevölkerungszahlen.')+' [E01]']
        elif metric=='neighbours':
            r=data['rows'][0];names_text=', '.join(n['name'] for n in r['neighbours'])
            lines=[tr(f"In **COD v03**, {r['name']} ({r['unit_type']}) shares a line border with: **{names_text or 'no stored unit at the same level'}**.",
                f"Dans **COD v03**, {r['name']} ({r['unit_type']}) partage une limite linéaire avec : **{names_text or 'aucune unité enregistrée au même niveau'}**.",
                f"In **COD v03** hat {r['name']} ({r['unit_type']}) eine gemeinsame Grenzlinie mit: **{names_text or 'keiner gespeicherten Einheit derselben Ebene'}**.")+' [E01]',
                tr('Computed from same-release polygons. Point contacts are excluded; this says nothing about road connections, travel time or service access.',
                   'Calculé à partir de polygones de la même version. Les contacts ponctuels sont exclus; cela ne décrit ni les routes, ni les temps de trajet, ni l’accès aux services.',
                   'Aus Polygonen derselben Version berechnet. Punktkontakte sind ausgeschlossen; daraus folgen keine Straßenverbindungen, Reisezeiten oder Aussagen zum Zugang zu Dienstleistungen.')+' [E01]']
        else:
            lines=[tr(f"For {data['scope_name']}, the sum of 2023 commune and Bamako arrondissement populations by INSTAT classification is:",
                f"Pour {data['scope_name']}, la somme des populations 2023 des communes et arrondissements de Bamako, selon le classement INSTAT, est :",
                f"Für {data['scope_name']} ergibt die Summe der Bevölkerungen von Gemeinden und Bamako-Arrondissements 2023 nach INSTAT-Klassifikation:")]
            lines.extend(f"- {r['residence']}: **{r['population']:,}** ({r['share_of_partition_sum_pct']:.2f}%). [E01]" for r in data['rows'])
            lines.append(tr(f"Shares use the partition sum ({data['partition_sum']:,}); it differs from the published scope total by {data['sum_minus_published']:+,} people through separate rounding. U/R is inherited from commune/arrondissement status.",
                f"Les parts utilisent la somme des unités ({data['partition_sum']:,}); l’écart au total publié est de {data['sum_minus_published']:+,} personnes, lié aux arrondis distincts. U/R est hérité du statut communal/de l’arrondissement.",
                f"Der Nenner ist die Summe der Einheiten ({data['partition_sum']:,}); die Abweichung zum veröffentlichten Gesamtwert beträgt {data['sum_minus_published']:+,} Personen durch separate Rundung. U/R folgt dem Gemeinde-/Arrondissementstatus.")+' [E01]')
        return {'answer':'\n\n'.join(lines) if metric not in ('population','ranking') else '\n'.join(lines),
                'evidence':[self.evidence(data,metric)],'country':data,
                'family_counts':{'Mali Country Knowledge Foundation':1}}


@lru_cache(maxsize=1)
def _load():return CountryFoundation()


def country_foundation():
    with _lock:return _load()


def resolve_country_followup(question,messages):
    from followup_context import previous_question
    match=re.fullmatch(r'(?:and(?: in)?|what about|same for|et(?: a|dans|en)?|und(?: in)?) (.+)',_fold(question))
    if not match:return None
    previous=previous_question(messages)
    plan=country_plan(previous) if previous else None
    if not plan or plan['metric'] not in ('population','area','neighbours') or plan['scope_level']:
        return None
    level=plan['level']
    target=match[1]
    explicit=re.fullmatch(r'(.+) (region|cercle|commune|arrondissement|locality)',target)
    if explicit:target,level=explicit.groups()
    if not level:return None
    foundation=country_foundation()
    release=foundation.model.preferred if plan['metric']=='population' else foundation.cod
    if len(foundation.model.lookup(target,level,release))!=1:return None
    # Copy only metric and explicit selection, never prior assistant facts.
    return f"What is the {plan['metric']} of {target} {level}?"
