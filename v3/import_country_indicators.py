"""Fetch only allowlisted, national, non-sensitive WDI series and metadata."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import gzip
import hashlib
import json
import math
from pathlib import Path

import requests

INDICATORS={
 'NY.GDP.MKTP.CD':('economy','current US$'),
 'NY.GDP.PCAP.CD':('economy','current US$ per person'),
 'NV.AGR.TOTL.ZS':('economy','% of GDP'),
 'SL.AGR.EMPL.ZS':('livelihoods','% of total employment; modelled ILO estimate'),
 'EG.ELC.ACCS.ZS':('infrastructure','% of population'),
 'EG.ELC.ACCS.UR.ZS':('infrastructure','% of urban population'),
 'EG.ELC.ACCS.RU.ZS':('infrastructure','% of rural population'),
 'SH.H2O.BASW.ZS':('WASH','% of population'),
 'SH.STA.BASS.ZS':('WASH','% of population'),
 'SE.PRM.CMPT.ZS':('education','% of relevant age group'),
 'SE.PRM.ENRR':('education','gross enrolment ratio, %'),
 'SE.SEC.ENRR':('education','gross enrolment ratio, %'),
 'AG.LND.FRST.ZS':('environment','% of land area'),
 'AG.LND.AGRI.ZS':('environment','% of land area'),
 'AG.SRF.TOTL.K2':('physical geography','km²'),
 'AG.LND.TOTL.K2':('physical geography','km²'),
 'SH.MED.BEDS.ZS':('health','hospital beds per 1,000 people'),
}


def retrieve(code,first_year,last_year):
    root='https://api.worldbank.org/v2'
    data_url=f'{root}/country/MLI/indicator/{code}?format=json&source=2&date={first_year}:{last_year}&per_page=1000'
    metadata_url=f'{root}/indicator/{code}?format=json&source=2'
    responses=[]
    for url in (metadata_url,data_url):
        response=requests.get(url,timeout=40)
        response.raise_for_status()
        responses.append(response.json())
    metadata,data=responses
    if len(metadata)!=2 or len(metadata[1])!=1 or metadata[1][0]['id']!=code:
        raise ValueError('Unexpected indicator metadata: '+code)
    if len(data)!=2 or data[0]['pages']!=1 or not isinstance(data[1],list):
        raise ValueError('Incomplete indicator response: '+code)
    observations=[];seen=set()
    for row in data[1]:
        if row.get('countryiso3code')!='MLI' or row['indicator']['id']!=code:
            raise ValueError('Wrong country or indicator')
        year=int(row['date']);value=row['value']
        if year in seen or not first_year<=year<=last_year:raise ValueError('Duplicate/out-of-window year')
        seen.add(year)
        if value is not None and (not isinstance(value,(float,int)) or not math.isfinite(value) or value<0):
            raise ValueError('Invalid indicator observation')
        observations.append({'year':year,'value':value,'status':'missing' if value is None else 'reported',
                             'decimal':row.get('decimal'),'obs_status':row.get('obs_status')})
    observations.extend({'year':year,'value':None,'status':'not_returned','decimal':None,'obs_status':None}
                        for year in range(first_year,last_year+1) if year not in seen)
    domain,unit=INDICATORS[code]
    return {'indicator_id':code,'domain':domain,'unit':unit,'country_iso3':'MLI',
        'source':'World Bank World Development Indicators','source_id':'2',
        'metadata':metadata[1][0],'api_header':data[0],
        'data_url':data_url,'metadata_url':metadata_url,
        'observations':sorted(observations,key=lambda r:r['year']),
        'response_sha256':hashlib.sha256(json.dumps(responses,sort_keys=True).encode()).hexdigest()}


def fetch(output,first_year=2015,last_year=2026):
    with ThreadPoolExecutor(max_workers=4) as pool:
        series=list(pool.map(lambda code:retrieve(code,first_year,last_year),INDICATORS))
    result={'dataset_id':'mli-wdi-country-foundation','country_iso3':'MLI',
        'retrieved_at':datetime.now(timezone.utc).isoformat(),
        'reference_window':[first_year,last_year],
        'geographic_framework':'WDI national MLI reporting geography; no administrative or polygon crosswalk',
        'license':'World Bank dataset terms; indicator-level third-party attribution retained in metadata',
        'license_url':'https://datacatalog.worldbank.org/public-licenses',
        'limitations':[
            'National estimates only; no allocation to regions, communes or facilities.',
            'Latest means latest non-null observation within the explicit reference window, not current conditions.',
            'API update date is not the observation year or an indicator-specific publication date.',
            'Null observations remain missing and are never treated as zero.',
            'Gross school enrolment ratios can exceed 100%; they are not completion or attendance rates.',
            'Electricity access is not continuous power supply; basic WASH is not safely managed WASH.',
            'National reported land/surface area is distinct from COD-derived polygon area.',
        ],'series':series}
    Path(output).write_bytes(gzip.compress(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(json.dumps({'series':len(series),'reported':sum(o['value'] is not None for s in series for o in s['observations']),
        'missing':sum(o['value'] is None for s in series for o in s['observations']),
        'latest_years':{s['indicator_id']:max((o['year'] for o in s['observations'] if o['value'] is not None),default=None) for s in series}}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();fetch(args.output)
