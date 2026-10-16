"""Validate real geometry/raster provenance, scientific semantics and serving."""
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from pyproj import Geod
from shapely.geometry import shape
import shapely
from starlette.testclient import TestClient

from build_country_physical import join_grid,terrain_statistics
from country_physical import (physical_package,physical_plan,physical_query,physical_answer,
                              river_geometry,RASTER)
from country_foundation import country_foundation,country_plan
from query_router import classify
from source_inventory import catalogue
import web_api


def test_physical_sources_versions_and_dates_are_not_population_crosswalks():
    p=physical_package();f=country_foundation()
    assert p['boundary_release_id']==f.cod and p['boundary_checksum']==f.model.releases[f.cod]['checksum']
    assert p['sources']['rivers']['version']=='5.0.0'
    assert p['sources']['rivers']['publication_date'] is None
    assert p['sources']['rivers']['source_revision']=='ca96624a56bd078437bca8184e78163e5039ad19'
    assert p['sources']['terrain']['resolution_arc_seconds']==60
    assert p['sources']['terrain']['publication_date']=='2022-10-01'
    assert p['sources']['terrain']['vertical_datum']=='EGM2008 (EPSG:3855)'
    assert p['sources']['terrain']['global_input_period']==['1998-01-01','2022-09-01']
    assert len(p['terrain'])==21 and len(p['rivers'])==10
    assert all(row['unit_id'] not in f.populations for row in p['terrain'])
    assert all('population' not in row for row in p['terrain'])


def test_original_river_features_reproduce_clips_and_lengths_without_name_conflation():
    p=physical_package();f=country_foundation();country=shape(f.geometry('country','Mali')['features'][0]['geometry'])
    geod=Geod(ellps='WGS84')
    for row in p['rivers']:
        original=row['source_feature'];clipped=shape(row['geometry'])
        assert original['properties']==row['source_properties']
        assert str(original['properties']['rivernum'])==row['river_id']
        assert clipped.is_valid and clipped.equals_exact(shape(original['geometry']).intersection(country),1e-12)
        assert clipped.difference(country).length<1e-9
        assert geod.geometry_length(clipped)/1000==pytest.approx(row['clipped_line_km'])
    baoule=physical_query('physical_rivers',['Baoulé'])
    assert baoule['status']=='same_name_distinct_rivers' and {r['river_id'] for r in baoule['rows']}=={'499','816'}
    niger=physical_query('physical_rivers',['Niger'])
    assert len(niger['rows'])==1 and niger['rows'][0]['feature_classes']==['Lake Centerline','River']
    assert len(river_geometry('Niger')['features'])==2
    assert len(river_geometry('Baoulé','499')['features'])==1
    assert physical_query('physical_rivers',['Unknownriver'])['rows']==[]
    assert physical_query('terrain',['Gao','Unknownregion'],'region')['rows']==[]


def test_raster_orientation_values_and_area_weighted_summaries_reproduce_exactly():
    p=physical_package();f=country_foundation();geod=Geod(ellps='WGS84')
    assert hashlib.sha256(RASTER.read_bytes()).hexdigest()==p['raster']['sha256']
    with rasterio.open(RASTER) as raster:
        values=raster.read(1);inside=values!=raster.nodata
        assert raster.crs.to_epsg()==4326 and raster.nodata==-99999
        assert raster.res==(1/60,1/60) and raster.transform.e<0
        assert raster.tags()['VERTICAL_DATUM']=='EGM2008 (EPSG:3855)'
        assert hashlib.sha256(values.astype('<f4').tobytes()).hexdigest()==p['raster']['pixel_data_sha256']
        assert int(inside.sum())==384668
        # Independently read the written north-up product and calculate weights
        # from each row's cell bounds, rather than reusing builder arrays.
        rows=np.arange(raster.height);lat=raster.transform.f+(rows+.5)*raster.transform.e
        weights=np.array([abs(geod.polygon_area_perimeter([0,1/60,1/60,0],
            [y-1/120,y-1/120,y+1/120,y+1/120])[0]) for y in lat])
        national=next(r for r in p['terrain'] if r['level']=='country')
        mean=np.average(values[inside],weights=np.broadcast_to(weights[:,None],values.shape)[inside])
        assert mean==pytest.approx(national['cell_area_weighted_mean_m'],abs=1e-10)
        assert national['cell_area_weighted_mean_m']==pytest.approx(317.6850026,abs=1e-6)
        assert national['minimum_grid_value_m']==pytest.approx(23.04509735)
        assert national['maximum_grid_value_m']==pytest.approx(914.78100586)
        gao_geometry=shape(f.geometry('region','Gao')['features'][0]['geometry'])
        lon=raster.transform.c+(np.arange(raster.width)+.5)*raster.transform.a
        xx,yy=np.meshgrid(lon,lat)
        gao_mask=shapely.contains_xy(gao_geometry,xx,yy)&inside
        gao_mean=np.average(values[gao_mask],weights=np.broadcast_to(weights[:,None],values.shape)[gao_mask])
        assert gao_mean==pytest.approx(312.8439332541769,abs=1e-10)
        assert gao_mean==pytest.approx(physical_query('terrain',['Gao'],'region')['rows'][0]['cell_area_weighted_mean_m'],abs=1e-10)
        assert sum(r['cell_count'] for r in p['terrain'] if r['level']=='region')==national['cell_count']
        assert p['quality']['coverage']=={'country_cells':384668,'unassigned_country_cells':0,'multiply_assigned_country_cells':0}
        assert not np.any(values[inside]==0) and np.all(values[~inside]==-99999)


def test_meridian_join_preserves_sign_orientation_and_every_source_value():
    lat=np.array([10.0083333333,10.025]);westlon=np.array([359.975,359.9916666667]);eastlon=np.array([.0083333333,.025])
    attrs={'units':b'meters','vert_crs_name':b'EGM2008','positive':b'up','_FillValue':-99999}
    west=(lat,westlon,np.array([[1,2],[3,4]]),attrs)
    east=(lat,eastlon,np.array([[5,6],[7,8]]),attrs)
    _,lon,z=join_grid(west,east)
    assert lon[0]<0<lon[-1] and np.allclose(np.diff(lon),1/60,atol=1e-10)
    assert z.tolist()==[[1,2,5,6],[3,4,7,8]]
    with pytest.raises(ValueError):join_grid(west,(lat,eastlon+1/60,east[2],attrs))
    with pytest.raises(ValueError):join_grid(west,(lat[::-1],eastlon,east[2],attrs))
    with pytest.raises(ValueError):join_grid(west,(lat,eastlon,east[2],{**attrs,'units':b'feet'}))
    with pytest.raises(ValueError):join_grid(west,(lat,eastlon,np.array([[5,-99999],[7,8]]),attrs))
    stats=terrain_statistics(np.array([[10.,20.],[100.,200.]]),np.ones((2,2),dtype=bool),np.array([2.,1.]))
    assert stats['cell_area_weighted_mean_m']==60
    assert stats['minimum_grid_value_m']==10 and stats['maximum_grid_value_m']==200


@pytest.mark.parametrize('question',[
    'Which rivers are mapped in Mali?', 'Which rivers flow through Mali?', 'Niger river in Mali',
    'What are the major rivers in Mali?', 'Quels sont les principaux fleuves du Mali ?', 'Wie hoch ist Mali?',
    'What is the elevation of Mali?', 'What is the mean elevation of Gao region?',
    'Compare mean elevation in Gao and Mopti regions', 'What is the elevation of Bamako district?',
    'Quelles rivières traversent le Mali ?', 'Quelle est l’altitude moyenne du Mali ?',
    'Welche Flüsse fliessen durch Mali?', 'Wie ist die mittlere Höhe in Mali?',
])
def test_bounded_physical_intents(question):
    assert physical_plan(question) is not None
    assert classify(question)['path']=='country_fact'


@pytest.mark.parametrize('question',[
    'Which rivers flow through Gao region in Mali?', 'What is the elevation of Gao commune in Mali?',
    'What is the current elevation of Mali?', 'What is the elevation of Mali in 2023?',
    'What is the highest point in Mali?', 'How long is the Niger river in Mali?',
])
def test_local_surveyed_official_and_current_claims_are_not_substituted(question):
    result=physical_answer(question)
    assert result['country']['status']=='unsupported_physical_selection' and not result['evidence']


@pytest.mark.parametrize('question',[
    'What is the population and elevation of Mali?', 'Why does terrain affect agriculture in Mali?',
    'What is elevation in Atlantis region, Mali?', 'Which rivers affect conflict in Mali?',
    'Which bridges cross rivers in Mali?', 'What is the river discharge in Mali?',
    'Which river datasets are available in Mali Knowledge Hub?',
])
def test_mixed_unknown_and_other_definitions_keep_existing_research(question):
    assert physical_plan(question) is None


def test_sources_and_cited_zero_provider_http_with_raster_download():
    entries=catalogue()
    assert next(r for r in entries if 'named river cartography' in r['title'])['records']==10
    assert next(r for r in entries if 'modeled terrain summaries' in r['title'])['records']==21
    with TestClient(web_api.app,base_url='https://mali-knowledge-hub.onrender.com') as client:
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network')):
            for question in ['Which rivers are mapped in Mali?','What is the mean elevation of Gao region?']:
                r=client.post('/api/chat',json={'question':question},headers={'Origin':'https://mali-knowledge-hub.onrender.com'})
                assert r.status_code==200,r.text
                body=r.json();assert body['metrics']['route']=='country_fact'
                assert body['metrics']['model_calls']==body['metrics']['embedding_calls']==body['metrics']['external_research_calls']==0
                assert body['metrics']['estimated_usd']==0 and len(body['evidence'])==2
                assert body['evidence'][1]['release_id']==physical_package()['boundary_release_id']
                assert 'not a verbatim publisher quotation' in body['evidence'][0]['content']
            for question,term in [('Quelle est l’altitude moyenne du Mali ?','Altitude modélisée'),
                                  ('Wie ist die mittlere Höhe in Mali?','Modellierte Höhe')]:
                result=client.post('/api/chat',json={'question':question},headers={'Origin':'https://mali-knowledge-hub.onrender.com'}).json()
                assert term in result['answer'] and result['metrics']['model_calls']==0
            r=client.get('/api/country',params={'metric':'terrain','level':'region','name':'Gao'})
            assert r.json()['country']['rows'][0]['cell_area_weighted_mean_m']==pytest.approx(312.8439332541769,abs=1e-10)
            assert client.get('/api/country',params={'metric':'river_geometry','name':'Niger'}).headers['content-type'].startswith('application/geo+json')
            r=client.get('/api/country',params={'metric':'terrain_raster'})
            assert r.status_code==200 and hashlib.sha256(r.content).hexdigest()==physical_package()['raster']['sha256']
            for params in [{'metric':'terrain','level':'commune','name':'Gao'}, {'metric':'terrain','year':2023},
                           {'metric':'physical_rivers','level':'region'}, {'metric':'terrain_raster','name':'Gao'},
                           {'metric':'physical_rivers','river_id':'invalid'}]:
                assert client.get('/api/country',params=params).status_code==400


def test_physical_export_has_normalized_foreign_keys_geometry_and_raster(tmp_path):
    from export_country_foundation import export
    path=export(tmp_path)
    with sqlite3.connect(path) as db:
        assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert not db.execute('pragma foreign_key_check').fetchall()
        assert db.execute('select count(*) from country_terrain').fetchone()[0]==21
        assert db.execute('select count(*) from country_rivers').fetchone()[0]==10
        assert db.execute("select count(distinct river_id) from country_rivers where name='Baoulé'").fetchone()[0]==2
        assert db.execute('select count(*) from country_climate').fetchone()[0]==52
        assert db.execute('select count(*) from mkh_population_observations').fetchone()[0]==41751
        assert db.execute('select count(*) from mkh_humanitarian_observations').fetchone()[0]==0
    assert hashlib.sha256((tmp_path/'Mali_ETOPO2022_60s_COD_v03.tif').read_bytes()).hexdigest()==physical_package()['raster']['sha256']
    assert len(json.loads((tmp_path/'Named_Rivers_Natural_Earth_5.0.0.geojson').read_text())['features'])==10
