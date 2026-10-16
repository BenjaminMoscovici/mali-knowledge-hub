"""Build pinned named-river context and coarse terrain summaries over COD v03.

Builder-only scientific dependencies. No Supabase writes, runtime processing,
administrative crosswalk approval or automatic river-name conflation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re

import requests

NE_COMMIT = 'ca96624a56bd078437bca8184e78163e5039ad19'
NE_PAGE = 'https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-rivers-lake-centerlines/'
NOAA_PAGE = 'https://www.ncei.noaa.gov/products/etopo-global-relief-model'
ERDDAP = 'https://oceanwatch.pifsc.noaa.gov/erddap/griddap/ETOPO_2022_v1_60s'
SOURCES = {
    'rivers.geojson': f'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_COMMIT}/geojson/ne_10m_rivers_lake_centerlines.geojson',
    'rivers.VERSION.txt': f'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_COMMIT}/10m_physical/ne_10m_rivers_lake_centerlines.VERSION.txt',
    'terrain_west.nc': ERDDAP + '.nc?z[(10):1:(26)][(347):1:(359.9916666667)]',
    'terrain_east.nc': ERDDAP + '.nc?z[(10):1:(26)][(0.0083333333):1:(5)]',
    'terrain.das': ERDDAP + '.das',
    'terrain_catalogue.html': 'https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ngdc.mgg.dem%3Aetopo_2022',
}


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def fetch(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name in (*SOURCES, 'manifest.json')):
        raise ValueError('Fetch into a fresh source directory')
    def retrieve(item):
        name, url = item
        response = requests.get(url, timeout=55); response.raise_for_status()
        if len(response.content) > 20_000_000:
            raise ValueError('Unexpected source size')
        return name, response.content, {'url': url, 'response_url': response.url,
            'sha256': sha256(response.content), 'bytes': len(response.content),
            'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified')}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(retrieve, SOURCES.items()))
    manifest = {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'files': {}}
    for name, content, metadata in responses:
        (directory/name).write_bytes(content); manifest['files'][name] = metadata
    (directory/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')


def join_grid(west, east):
    """Validate native NOAA axes and join across 360°/0°, never interpolate."""
    import numpy as np
    arrays = []
    for lat, lon, z, attrs in (west, east):
        if (attrs.get('units') != b'meters' or attrs.get('vert_crs_name') != b'EGM2008'
                or attrs.get('positive') != b'up' or z.shape != (len(lat), len(lon))
                or not np.all(np.isfinite(z)) or np.any(z == attrs['_FillValue'])):
            raise ValueError('Wrong terrain units, datum, dimensions or missing data')
        if not np.allclose(np.diff(lat), 1/60, atol=1e-10, rtol=0) or not np.allclose(np.diff(lon), 1/60, atol=1e-10, rtol=0):
            raise ValueError('Unexpected terrain grid resolution or orientation')
        arrays.append((np.array(lat), np.array(lon), np.array(z, dtype='float32')))
    a, b = arrays
    if not np.array_equal(a[0], b[0]) or not (a[1].min() > 180 and b[1].max() < 180):
        raise ValueError('Mismatched latitude axes or longitude conventions')
    lon = np.concatenate([a[1]-360, b[1]])
    if not np.allclose(np.diff(lon), 1/60, atol=1e-10, rtol=0):
        raise ValueError('Gap or duplicate column at the prime meridian')
    return a[0], lon, np.concatenate([a[2], b[2]], axis=1)


def terrain_statistics(values, mask, row_areas):
    import numpy as np
    count = int(mask.sum())
    if count == 0: raise ValueError('No terrain cells in selected geometry')
    data = values[mask]; weights = np.broadcast_to(row_areas[:, None], values.shape)[mask]
    if not np.all(np.isfinite(data)) or np.any((data < -500) | (data > 6000)):
        raise ValueError('Invalid Mali terrain cells')
    return {'cell_count': count, 'cell_area_weighted_mean_m': float(np.average(data, weights=weights)),
            'minimum_grid_value_m': float(data.min()), 'maximum_grid_value_m': float(data.max()),
            'selected_grid_area_km2': float(weights.sum()/1e6), 'nodata_cells': 0}


def build(directory, output, raster):
    import numpy as np
    from scipy.io import netcdf_file
    import scipy
    import rasterio
    from rasterio.transform import from_origin
    import shapely
    from shapely.geometry import shape, mapping
    from pyproj import Geod
    from country_foundation import country_foundation
    directory = Path(directory); output = Path(output); raster = Path(raster)
    manifest = json.loads((directory/'manifest.json').read_text())
    if set(manifest['files']) != set(SOURCES): raise ValueError('Incomplete physical source manifest')
    for name, url in SOURCES.items():
        entry = manifest['files'][name]
        if entry['url'] != url or sha256((directory/name).read_bytes()) != entry['sha256']:
            raise ValueError('Physical source checksum or URL mismatch')
    if (directory/'rivers.VERSION.txt').read_text().strip() != '5.0.0':
        raise ValueError('Wrong Natural Earth layer version')
    das = (directory/'terrain.das').read_text()
    if not all(term in das for term in ('ETOPO 2022, 60 Arc-Second', 'EGM2008', 'EPSG:3855', 'NOAA NCEI')):
        raise ValueError('Unverified terrain product metadata')
    catalogue = (directory/'terrain_catalogue.html').read_text()
    if not all(term in catalogue for term in ('CC0-1.0', '2022-10-01', '1998-01-01', '2022-09-01')):
        raise ValueError('Unverified NOAA licence or temporal metadata')
    grids = []
    for name in ('terrain_west.nc', 'terrain_east.nc'):
        with netcdf_file(directory/name, mmap=False) as source:
            grids.append(tuple(np.array(source.variables[v].data) for v in ('latitude','longitude','z'))
                         + (dict(source.variables['z']._attributes),))
    lat, lon, values = join_grid(*grids)
    foundation = country_foundation()
    country_feature = foundation.geometry('country', 'Mali')['features'][0]
    country = shape(country_feature['geometry'])
    xx, yy = np.meshgrid(lon, lat)
    # Strict center inclusion is explicit and reproducible. Exact boundary
    # centers are omitted, not assigned to multiple administrative units.
    inside = shapely.contains_xy(country, xx, yy)
    geod = Geod(ellps='WGS84'); step = 1/60
    row_areas = np.array([abs(geod.polygon_area_perimeter(
        [0,step,step,0], [y-step/2,y-step/2,y+step/2,y+step/2])[0]) for y in lat])
    if not (lon[0]-step/2 <= country.bounds[0] and lon[-1]+step/2 >= country.bounds[2]
            and lat[0]-step/2 <= country.bounds[1] and lat[-1]+step/2 >= country.bounds[3]):
        raise ValueError('Terrain subset does not cover Mali')
    summaries = []; assigned = np.zeros(values.shape, dtype='uint8')
    features = [country_feature, *foundation.geometry('region')['features']]
    for feature in features:
        properties = feature['properties']; geometry = shape(feature['geometry'])
        selected = shapely.contains_xy(geometry, xx, yy) & inside
        if properties['level'] == 'region': assigned += selected
        stats = terrain_statistics(values, selected, row_areas)
        summaries.append({'unit_id': feature['id'], 'name': properties['name'],
            'level': properties['level'], 'unit_type': 'district' if properties['name'].casefold() == 'bamako' else properties['level'],
            'boundary_release_id': foundation.cod, **stats})
    coverage = {'country_cells': int(inside.sum()), 'unassigned_country_cells': int((inside & (assigned == 0)).sum()),
                'multiply_assigned_country_cells': int((inside & (assigned > 1)).sum())}
    # Boundary defects remain explicit. Never use these zonal means to claim
    # an exact regional partition if the source polygons do not provide one.
    masked = np.where(inside, values, -99999).astype('float32')[::-1]
    transform = from_origin(float(lon[0]-step/2), float(lat[-1]+step/2), step, step)
    with rasterio.open(raster, 'w', driver='GTiff', width=len(lon), height=len(lat), count=1,
        dtype='float32', crs='EPSG:4326', transform=transform, nodata=-99999,
        compress='DEFLATE', predictor=3, zlevel=9, tiled=True) as target:
        target.write(masked, 1)
        target.update_tags(SOURCE='NOAA NCEI ETOPO2022 v1, 60 arc-second surface grid',
            VERTICAL_DATUM='EGM2008 (EPSG:3855)', UNIT='metres', BOUNDARY_RELEASE=foundation.cod,
            MASK='Strict grid-center inclusion in COD v03 Mali; outside country is nodata')
    with rasterio.open(raster) as source:
        restored = source.read(1)
        if not np.array_equal(restored, masked): raise ValueError('Raster export changes terrain values')
    global_rivers = json.loads((directory/'rivers.geojson').read_text())
    if global_rivers.get('crs', {}).get('properties', {}).get('name') not in ('urn:ogc:def:crs:OGC:1.3:CRS84','urn:ogc:def:crs:EPSG::4326'):
        raise ValueError('Unverified river coordinate reference system')
    rivers = []
    for index, feature in enumerate(global_rivers['features']):
        geometry = shape(feature['geometry'])
        if not geometry.intersects(country): continue
        if not geometry.is_valid or geometry.geom_type not in ('LineString','MultiLineString'):
            raise ValueError('Invalid river geometry; no silent repair')
        properties = feature['properties']
        if not properties.get('name') or properties['featurecla'] not in ('River','Lake Centerline'):
            raise ValueError('Unqualified named river feature')
        clipped = geometry.intersection(country)
        if clipped.is_empty or clipped.geom_type not in ('LineString','MultiLineString'):
            raise ValueError('Non-line country river intersection')
        rivers.append({'source_row': index, 'source_record_id': f'ne5.0.0:row:{index}',
            'river_id': str(properties['rivernum']), 'name': properties['name'],
            'source_properties': properties, 'source_feature': feature,
            'geometry': mapping(clipped), 'clipped_line_km': geod.geometry_length(clipped)/1000,
            'clip_boundary_release_id': foundation.cod})
    if not rivers: raise ValueError('No intersecting named rivers')
    package = {'dataset_id': 'mli-physical-country-foundation-v1', 'retrieved_at': manifest['retrieved_at'],
        'boundary_release_id': foundation.cod, 'boundary_checksum': foundation.model.releases[foundation.cod]['checksum'],
        'boundary_version': 'COD v03', 'source_manifest': manifest,
        'sources': {
            'rivers': {'dataset_id': 'mli-natural-earth-rivers-5.0.0', 'provider': 'Natural Earth / NACIS contributors',
                'version': '5.0.0', 'source_revision': NE_COMMIT, 'source_revision_date': '2022-06-02',
                'source_page': NE_PAGE, 'scale_denominator': 10_000_000, 'publication_date': None,
                'reference_start': None, 'reference_end': None, 'license': 'Public domain',
                'license_url': 'https://www.naturalearthdata.com/about/terms-of-use/', 'attribution': 'Made with Natural Earth.',
                'limitations': ['Generalized cartographic river/lake centerlines at 1:10 million; not a complete hydrographic inventory.',
                    'Names and river IDs are retained from Natural Earth, not official Malian geographic codes.',
                    'Same-name rivers remain distinct; lake centerline parts are identified separately.',
                    'Geometry is clipped to COD v03 country only. No commune, settlement or infrastructure relationship is inferred.',
                    'Lengths are lengths of generalized clipped traces, not official river lengths, navigability or flow measurements.',
                    'Observation dates and exact layer publication date are not supplied; source revision date is not a survey date.']},
            'terrain': {'dataset_id': 'mli-noaa-etopo2022-v1-60s', 'provider': 'NOAA National Centers for Environmental Information',
                'version': 'ETOPO2022 v1; 60 arc-second surface', 'source_page': NOAA_PAGE,
                'doi': 'https://doi.org/10.25921/fd45-gt74', 'publication_date': '2022-10-01',
                'global_input_period': ['1998-01-01','2022-09-01'], 'reference_start': None, 'reference_end': None,
                'license': 'CC0-1.0', 'license_url': SOURCES['terrain_catalogue.html'],
                'attribution': 'NOAA National Centers for Environmental Information (2022), ETOPO 2022, doi:10.25921/fd45-gt74; 60 arc-second derivative.',
                'resolution_arc_seconds': 60, 'horizontal_crs': 'EPSG:4326', 'vertical_datum': 'EGM2008 (EPSG:3855)', 'unit': 'm',
                'method': 'Strict grid-center inclusion in COD v03; WGS84 ellipsoidal cell-area-weighted mean; no resampling or interpolation.',
                'raw_metadata_das': das,
                'limitations': ['Coarse 60-arc-second grid (about 1.85 km north-south); regional context, not engineering, navigation or site assessment.',
                    'Composite product published in 2022; input dates vary. The catalogue global input period does not date each Mali cell.',
                    'Minimum and maximum are selected grid values, not surveyed lowest/highest points or named peaks.',
                    'Strict center inclusion approximates polygon coverage; selected grid-cell area is not the surveyed or calculated polygon area.',
                    'Zonal summaries use COD v03 only; no INSTAT population join, commune allocation or approved identity crosswalk.',
                    'NoData remains missing. Outside the country mask is NoData, not zero elevation.']},
        },
        'rivers': rivers, 'terrain': summaries,
        'raster': {'filename': raster.name, 'sha256': sha256(raster.read_bytes()), 'width': len(lon), 'height': len(lat),
            'bounds': [float(lon[0]-step/2),float(lat[0]-step/2),float(lon[-1]+step/2),float(lat[-1]+step/2)],
            'nodata': -99999, 'valid_cells': int(inside.sum()), 'pixel_data_sha256': sha256(masked.astype('<f4').tobytes())},
        'quality': {'river_source_features_global': len(global_rivers['features']), 'river_features_in_country': len(rivers),
            'river_ids_in_country': len({r['river_id'] for r in rivers}), 'distinct_name_labels': len({r['name'] for r in rivers}),
            'terrain_summaries': len(summaries), 'prime_meridian_contiguous': True, 'raster_roundtrip_exact': True,
            'coverage': coverage, 'builder_versions': {'numpy': np.__version__, 'scipy': scipy.__version__,
                'rasterio': rasterio.__version__, 'shapely': shapely.__version__}},
    }
    output.write_bytes(gzip.compress(json.dumps(package, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0))
    print(json.dumps({'quality': package['quality'], 'raster_bytes': raster.stat().st_size,
        'national_terrain': summaries[0]}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--inputs', required=True)
    parser.add_argument('--fetch', action='store_true'); parser.add_argument('--output', required=True); parser.add_argument('--raster', required=True)
    args = parser.parse_args()
    if args.fetch: fetch(args.inputs)
    build(args.inputs, args.output, args.raster)
