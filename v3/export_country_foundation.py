"""Export a standalone country-only SQLite database, CSVs and GeoJSON.

Reuses MKH source UUIDs. Does not export accounts, conversations, operational
datasets, or humanitarian observations. No external services are contacted.
"""
import argparse
import csv
import gzip
import json
from pathlib import Path
import sqlite3

from country_foundation import OVERLAY,country_foundation
from country_indicators import indicator_package
from country_climate import climate_package
from source_wave import snapshot_path


def export(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'Mali_Country_Foundation.sqlite'
    if path.exists():raise ValueError('Use a fresh export directory')
    foundation=country_foundation()
    retained=(foundation.model.preferred,foundation.cod)
    src=sqlite3.connect(f'file:{snapshot_path()}?mode=ro',uri=True)
    out=sqlite3.connect(path);src.backup(out);src.close()
    for table in ('mkh_population_observations','mkh_humanitarian_observations','mkh_geo_unresolved',
                  'mkh_document_pages','mkh_evidence_spans','mkh_geo_units'):
        out.execute(f'delete from {table} where release_id not in (?,?)',retained)
    out.execute('delete from mkh_geo_names where unit_id not in (select id from mkh_geo_units)')
    out.execute('delete from mkh_geo_identifiers where unit_id not in (select id from mkh_geo_units)')
    out.execute('delete from mkh_geo_crosswalks where from_unit_id not in (select id from mkh_geo_units) or to_unit_id not in (select id from mkh_geo_units)')
    out.execute('delete from mkh_source_releases where id not in (?,?)',retained)
    out.execute('delete from mkh_datasets where current_release_id not in (?,?)',retained)
    out.execute('delete from mkh_ingestion_runs where dataset_id not in (select id from mkh_datasets)')
    out.execute('delete from mkh_sources where id not in (select source_id from mkh_datasets)')
    overlay=sqlite3.connect(':memory:');overlay.deserialize(gzip.decompress(OVERLAY.read_bytes()))
    for statement in overlay.iterdump():
        if statement not in ('BEGIN TRANSACTION;','COMMIT;'):out.execute(statement)
    overlay.close()
    out.executescript('''
        create table foundation_indicator_series(
          indicator_id text primary key,country_iso3 text not null,domain text not null,
          unit text not null,name text not null,definition text,source_organization text,
          data_url text not null,metadata_url text not null,api_last_updated text,
          retrieved_at text not null,response_sha256 text not null);
        create table foundation_indicator_observations(
          indicator_id text not null references foundation_indicator_series(indicator_id),
          year integer not null,value real,status text not null,
          primary key(indicator_id,year));
        create table foundation_climate_datasets(
          dataset_id text primary key,country_iso3 text not null,source_version text not null,
          reference_start text not null,reference_end text not null,retrieved_at text not null,
          geographic_framework text not null,source_page text not null,provenance_json text not null);
        create table foundation_climate_variables(
          dataset_id text not null references foundation_climate_datasets(dataset_id),
          variable text not null,label text not null,unit text not null,definition text not null,
          primary key(dataset_id,variable));
        create table foundation_climate_observations(
          dataset_id text not null,variable text not null,aggregation text not null,
          month integer not null,source_coordinate text not null,value real not null,status text not null,
          foreign key(dataset_id,variable) references foundation_climate_variables(dataset_id,variable),
          primary key(dataset_id,variable,aggregation,month),
          check((aggregation='annual' and month=0) or (aggregation='monthly' and month between 1 and 12)));
        create view country_climate as
          select d.dataset_id,d.country_iso3,d.source_version,d.reference_start,d.reference_end,
            v.variable,v.label,v.unit,v.definition,o.aggregation,o.month,o.source_coordinate,o.value,o.status,
            d.geographic_framework,d.source_page,d.retrieved_at
          from foundation_climate_datasets d
          join foundation_climate_variables v on v.dataset_id=d.dataset_id
          join foundation_climate_observations o on o.dataset_id=v.dataset_id and o.variable=v.variable;
        create view country_population as
          select u.id unit_id,u.parent_id,u.name,u.level,
            case when u.level='region' and lower(u.name)='bamako' then 'district' else u.level end unit_type,
            u.boundary_version,
            t.value population_total,m.value population_male,f.value population_female,
            a.residence,a.reported_localities,t.reference_start,t.reference_end,
            t.methodology,u.release_id,s.page pdf_page,s.printed_page,s.locator,s.passage,
            r.source_url,r.checksum source_checksum
          from mkh_geo_units u
          join mkh_population_observations t on t.unit_id=u.id and t.sex='total'
          join mkh_population_observations m on m.unit_id=u.id and m.sex='male'
          join mkh_population_observations f on f.unit_id=u.id and f.sex='female'
          join foundation_attributes a on a.unit_id=u.id
          join mkh_evidence_spans s on s.id=t.span_id
          join mkh_source_releases r on r.id=u.release_id;
        create view country_boundaries as
          select u.id unit_id,u.parent_id,u.name,u.level,u.boundary_version,
            b.area_km2,b.method,b.west,b.south,b.east,b.north,
            b.representative_lon,b.representative_lat,u.geometry_json,
            u.release_id,u.original_record_id,r.source_url,r.checksum source_checksum
          from mkh_geo_units u
          join foundation_boundary_metrics b on b.unit_id=u.id and b.release_id=u.release_id
          join mkh_source_releases r on r.id=u.release_id;
    ''')
    package=indicator_package()
    for series in package['series']:
        out.execute('insert into foundation_indicator_series values (?,?,?,?,?,?,?,?,?,?,?,?)',
            (series['indicator_id'],'MLI',series['domain'],series['unit'],series['metadata']['name'],
             series['metadata'].get('sourceNote'),series['metadata'].get('sourceOrganization'),
             series['data_url'],series['metadata_url'],series['api_header'].get('lastupdated'),
             package['retrieved_at'],series['response_sha256']))
        out.executemany('insert into foundation_indicator_observations values (?,?,?,?)',
            [(series['indicator_id'],o['year'],o['value'],o['status']) for o in series['observations']])
    out.execute('insert into foundation_metadata values (?,?)',
                ('national_indicator_provenance',json.dumps({k:v for k,v in package.items() if k!='series'},ensure_ascii=False)))
    climate=climate_package();dataset=climate['dataset_id']
    out.execute('insert into foundation_climate_datasets values (?,?,?,?,?,?,?,?,?)',
        (dataset,'MLI',climate['source_version'],climate['reference_start'],climate['reference_end'],
         climate['retrieved_at'],climate['geographic_framework'],climate['source_page'],
         json.dumps({k:v for k,v in climate.items() if k not in ('variables','observations')},ensure_ascii=False)))
    out.executemany('insert into foundation_climate_variables values (?,?,?,?,?)',
        [(dataset,v,m['label'],m['unit'],m['info']) for v,m in climate['variables'].items()])
    out.executemany('insert into foundation_climate_observations values (?,?,?,?,?,?,?)',
        [(dataset,o['variable'],o['aggregation'],o['month'],o['source_coordinate'],o['value'],o['status']) for o in climate['observations']])
    out.commit()
    out.execute('vacuum')  # Remove deleted non-country source bytes from the export.
    if out.execute('pragma integrity_check').fetchone()[0]!='ok' or out.execute('pragma foreign_key_check').fetchall():
        raise ValueError('Standalone database integrity failure')
    for view,filename in [('country_population','Administrative_Population_2023.csv'),
                          ('country_boundaries','Boundary_Metrics_COD_v03.csv'),
                          ('country_climate','National_Climate_Normals_1991-2020.csv')]:
        cursor=out.execute('select * from '+view)
        columns=[c[0] for c in cursor.description]
        if view=='country_boundaries':
            columns.remove('geometry_json')
        with (directory/filename).open('w',newline='',encoding='utf-8-sig') as file:
            writer=csv.DictWriter(file,fieldnames=columns);writer.writeheader()
            names=[c[0] for c in cursor.description]
            for row in cursor:writer.writerow({k:v for k,v in zip(names,row) if k in columns})
    for level in ('country','region','cercle'):
        (directory/f'Boundaries_COD_v03_{level}.geojson').write_text(
            json.dumps(foundation.geometry(level),ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (directory/'National_Indicators_WDI.json').write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (directory/'National_Climate_Normals_CRU_TS4.09.json').write_text(json.dumps(climate,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (directory/'Source_Validation.json').write_text(json.dumps(foundation.validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    out.close()
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    print(export(parser.parse_args().output))
