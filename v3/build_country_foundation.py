"""Build a small, reproducible overlay over MKH's existing public source store.

No network, Supabase writes, new source identities or inferred crosswalks.
Requires requirements-country-build.txt; runtime queries need only SQLite.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

SCHEMA = """
create table foundation_metadata(key text primary key, value_json text not null);
create table foundation_attributes(
 unit_id text primary key, release_id text not null, span_id text not null,
 reported_localities integer not null check(reported_localities>=0),
 residence text check(residence in ('U','R') or residence is null));
create table foundation_boundary_metrics(
 unit_id text primary key, release_id text not null, boundary_version text not null,
 area_km2 real not null check(area_km2>0), west real, south real, east real, north real,
 representative_lon real, representative_lat real,
 method text not null, geometry_valid integer not null check(geometry_valid=1));
create table foundation_boundary_relations(
 from_unit_id text not null, to_unit_id text not null, release_id text not null,
 shared_border_m real not null, overlap_m2 real not null, relation text not null,
 primary key(from_unit_id,to_unit_id), check(from_unit_id<to_unit_id));
"""


def build(source, destination):
    from pyproj import Geod
    import pyproj
    import shapely
    from shapely.geometry import shape
    from shapely.geometry.polygon import orient
    from shapely.strtree import STRtree
    geod = Geod(ellps='WGS84')
    src = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    src.row_factory = sqlite3.Row
    units = {r['id']: dict(r) for r in src.execute('select * from mkh_geo_units')}
    releases = {r['id']: dict(r) for r in src.execute('select * from mkh_source_releases')}
    instat = src.execute("select current_release_id from mkh_datasets where id='mli-instat-localities-2023'").fetchone()[0]
    cod = src.execute("select current_release_id from mkh_datasets where id='mli-cod-ab'").fetchone()[0]
    out = sqlite3.connect(destination)
    out.executescript(SCHEMA)
    attributes = {}
    for row in src.execute('''select u.id,u.release_id,p.span_id,s.passage
        from mkh_geo_units u join mkh_population_observations p on p.unit_id=u.id
        join mkh_evidence_spans s on s.id=p.span_id
        where u.release_id=? and p.sex='total' ''', (instat,)):
        # These cells are printed in the existing evidence, previously unused.
        cells = re.split(r'\s{2,}', row['passage'].strip())
        residence = cells[-1] if cells[-1] in ('U', 'R') else None
        number = cells[-2] if residence else cells[-1]
        if not re.fullmatch(r'\d[\d ]*', number):
            raise ValueError('Unparsed locality-count cell: ' + row['id'])
        count = int(number.replace(' ', ''))
        attributes[row['id']] = (count, residence)
        out.execute('insert into foundation_attributes values (?,?,?,?,?)',
                    (row['id'], instat, row['span_id'], count, residence))
    children = defaultdict(list)
    for u in units.values():
        if u['release_id'] == instat:
            children[u['parent_id']].append(u['id'])
    counts = Counter(units[uid]['level'] for uid in attributes)
    expected = {'country': 1, 'region': 20, 'cercle': 159, 'commune': 815, 'arrondissement': 7, 'locality': 12915}
    if dict(counts) != expected:
        raise ValueError('Changed INSTAT source counts; review before building')
    gaps = []
    rounding = []
    populations = defaultdict(dict)
    for row in src.execute('select unit_id,sex,value from mkh_population_observations where release_id=?', (instat,)):
        populations[row['unit_id']][row['sex']] = row['value']
    for uid in attributes:
        u = units[uid]
        p = populations[uid]
        if set(p) != {'male','female','total'} or abs(p['male'] + p['female'] - p['total']) > 1:
            raise ValueError('Incomplete or inconsistent sex observations')
        if u['level'] in ('commune','arrondissement'):
            actual = len(children[uid])
            if actual != attributes[uid][0]:
                gaps.append({'unit_id':uid,'name':u['name'],'reported':attributes[uid][0],'enumerated':actual,
                             'locator':u['original_record_id']})
            if attributes[uid][1] not in ('U','R'):
                raise ValueError('Missing settlement classification')
        if children[uid]:
            delta = sum(populations[c]['total'] for c in children[uid]) - p['total']
            # Rounding to nearest integer at each node can accumulate across children.
            bound = (len(children[uid]) + 1) / 2
            rounding.append({'unit_id':uid,'name':u['name'],'level':u['level'],
                             'child_count':len(children[uid]),'sum_minus_reported':delta,
                             'rounding_bound':bound,'within_rounding_bound':abs(delta)<=bound})
    geometries = []
    metrics = []
    for u in units.values():
        if u['release_id'] != cod:
            continue
        if not u['geometry_json']:
            raise ValueError('Missing COD boundary')
        g = shape(json.loads(u['geometry_json']))
        if not g.is_valid or g.is_empty or g.geom_type not in ('Polygon','MultiPolygon'):
            raise ValueError('Invalid COD polygon; no silent geometry repair')
        area = abs(geod.geometry_area_perimeter(orient(g, sign=1))[0]) / 1e6
        point = g.representative_point()  # inside polygon; not a town coordinate
        if not g.covers(point):
            raise ValueError('Invalid representative point')
        method = 'WGS84 ellipsoidal area; pyproj.Geod; oriented exterior rings; not official survey area'
        out.execute('insert into foundation_boundary_metrics values (?,?,?,?,?,?,?,?,?,?,?,?)',
            (u['id'], cod, u['boundary_version'], area, *g.bounds, point.x, point.y, method, 1))
        geometries.append((u,g))
        metrics.append({'unit_id':u['id'],'level':u['level'],'area_km2':area})
    relations = Counter()
    for level in ('region','cercle'):
        group = [(u,g) for u,g in geometries if u['level']==level]
        shapes = [g for _,g in group]
        tree = STRtree(shapes)
        for i,(u,g) in enumerate(group):
            for j in tree.query(g, predicate='intersects'):
                if j<=i: continue
                other,h = group[j]
                intersection = g.intersection(h)
                polygons = ([intersection] if intersection.geom_type in ('Polygon','MultiPolygon') else
                            [part for part in getattr(intersection,'geoms',()) if part.geom_type in ('Polygon','MultiPolygon')])
                overlap = sum(abs(geod.geometry_area_perimeter(orient(part,sign=1))[0]) for part in polygons)
                shared = geod.geometry_length(g.boundary.intersection(h.boundary))
                relation = 'overlap_review' if overlap>1 else 'shared_border' if shared>1 else 'point_contact'
                a,b = sorted([u['id'],other['id']])
                out.execute('insert into foundation_boundary_relations values (?,?,?,?,?,?)',
                            (a,b,cod,shared,overlap,relation))
                relations[(level,relation)] += 1
    report = {
        'source_releases': {rid:{'checksum':releases[rid]['checksum'], 'dataset_id':releases[rid]['dataset_id']}
                            for rid in (instat,cod)},
        'attribute_counts':dict(counts),'population_observations':sum(map(len,populations.values())),
        'locality_count_discrepancies':gaps,
        'population_rollups':rounding,
        'geometry_count':len(metrics), 'geometry_invalid_count':0,
        'boundary_relations':{':'.join(k):v for k,v in relations.items()},
        'builder_versions':{'shapely':shapely.__version__,'pyproj':pyproj.__version__},
        'limitations':[
            'Population reference is 2023, projected from RGPH5 2022; publication month 2026-01.',
            'Locality names can repeat. No government code or locality coordinates invented.',
            'Published locality totals and enumerated rows differ in Dialafara and Massigui.',
            'Areas and borders belong exclusively to COD v03; INSTAT/COD crosswalks remain unapproved.',
            'No commune polygons, cross-country borders, route travel times or service-facility inventories.',
            'Point contacts and overlapping polygons are not shared-line neighbours.',
            'Representative points locate polygons for display; they are not settlement coordinates.',
        ]}
    out.execute('insert into foundation_metadata values (?,?)', ('validation',json.dumps(report,ensure_ascii=False)))
    out.commit()
    if out.execute('pragma integrity_check').fetchone()[0]!='ok':
        raise ValueError('Overlay integrity check failed')
    out.close();src.close()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'overlay.sqlite'
        report=build(args.source,db)
        args.output.write_bytes(gzip.compress(db.read_bytes(),mtime=0))
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='population_rollups'},ensure_ascii=False))
