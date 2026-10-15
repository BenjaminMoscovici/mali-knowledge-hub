# Mali Country Knowledge Foundation

This extends MKH's existing versioned INSTAT/COD source store. It does not
re-import the same PDF into a parallel corpus or approve crosswalks by name.
Queries use the existing geographic UUIDs and original page evidence.

## Source separation

| Source | Reference and coverage | Storage and use |
|---|---|---|
| INSTAT/BCR locality directory | 2023 population estimates based on RGPH5 2022 and DNP projections; 2023 administrative framework; printed publication month January 2026 | Existing `source_wave1.sqlite.gz`; original UUIDs, sex-specific observations, page spans and exact passages |
| OCHA COD-AB | v03, its own validity metadata; country/admin1/admin2 polygons | Same original store; computed area and adjacency belong only to this release |
| World Bank WDI | National MLI series; explicit 2015–2026 request window; each observation has its own year | `country_indicators.json.gz`; original definitions, underlying providers, API update dates and missing values |

`country_foundation.sqlite.gz` is a small derived overlay. It contains printed
urban/rural and locality-count attributes, polygon metrics, adjacency and source
checksums. The runtime rejects an overlay whose source releases do not match.
It reads population observations from the existing store. Runtime serving adds
no dependencies, network requests or model calls.

## Administrative and population model

- Country → region → cercle → commune → locality, with Bamako represented as
  district → arrondissement → locality.
- 19 regions plus one district, 159 cercles, 815 communes, seven Bamako
  arrondissements, 12,915 enumerated locality occurrences.
- Homonyms retain distinct source identities and full parent paths. A PDF row
  identifier is not represented as an official government geographic code.
- The publisher's national locality count is 12,917. Dialafara reports 38 but
  enumerates 37 locality rows; Massigui reports 54 but enumerates 53. Both
  published totals and enumerations remain visible. No missing row is invented.
- Repeated KEL-INKABAR labels remain separate source occurrences, pending
  source clarification; no destructive deduplication is applied.
- Published population totals remain authoritative at each selected level.
  Rounding differences are retained. Urban/rural shares explicitly use the sum
  of disjoint communes plus Bamako arrondissements as denominator.
- Commune rankings exclude Bamako arrondissements and say so explicitly.
  Rankings evaluate the entire selected release/scope, not a retrieval sample.

## Geographic calculations

Areas are calculated on the WGS84 ellipsoid with pyproj.Geod after orienting
polygon rings. They are derived GIS areas, not surveyed or official area claims.
All 181 COD polygons are validated without silently repairing geometry.

Neighbours must have a shared line longer than one metre and overlap no greater
than one square metre in the same COD release and level. Point contacts and
overlaps are recorded separately. Adjacency does not imply roads, travel time,
service access or geographic equivalence with an INSTAT population unit.

Representative points lie inside their polygons and are for polygon display;
they are not coordinates of towns or localities. Original GeoJSON remains
available from the geometry endpoint. No population value is attached to COD
polygons while crosswalks are unapproved.

## Chat examples

- `What is the population of Gao commune?`
- `Top 10 most populated communes in Mali`
- `Rank communes in Gao region by population`
- `Compare the populations of Gao and Mopti regions`
- `What is the urban and rural population of Mali?`
- `What is the area of Gao region?`
- `Which regions border Mopti region?`
- `What is electricity access in Mali?`
- `Hospital beds in Mali in 2024` (missing stays missing)
- `Quelle est la population de la commune de Gao ?`
- `Wie viele Einwohner hat die Gemeinde Gao?`

The new `country_fact` route handles bounded factual questions and returns
normal MKH evidence cards. Unsupported periods, incompatible density joins,
unknown place selections and unsupported indicator definitions fail explicitly.
Mixed analytical and sex-specific follow-up questions retain existing research
routes. English, French and German deterministic responses are provided within
this route; this is not a claim of complete language parity across MKH.

## Read-only API

`GET /api/country` lists metrics, indicators and source limitations.

Examples (query parameters shown without URL encoding):

```text
/api/country?q=What is the population of Gao commune?
/api/country?metric=population&level=commune&name=Gao
/api/country?metric=ranking&level=commune&scope_level=region&scope=Gao&limit=10
/api/country?metric=area&level=region&name=Gao
/api/country?metric=neighbours&level=region&name=Mopti
/api/country?metric=geometry&level=region&name=Gao
/api/country?metric=residence&level=country&name=Mali
/api/country?metric=indicator&indicator=SH.H2O.BASW.ZS&year=2024
/api/country?metric=indicator&indicator=EG.ELC.ACCS.ZS&series=true
```

Limits are 1–50 records per population/ranking selection. Geometry exports are
bounded by the fixed COD dataset. SQL identifiers and arbitrary queries are not
accepted. Existing authentication, private history and corpus permissions are
unchanged.

## Rebuild and export

Use the existing validated source snapshot, decompressed to a local SQLite file:

```bash
python -m pip install -r v3/requirements-country-build.txt
python v3/build_country_foundation.py --source SOURCE.sqlite \
  --output v3/country_foundation.sqlite.gz --report VALIDATION.json
python v3/import_country_indicators.py --output v3/country_indicators.json.gz
python v3/export_country_foundation.py --output NEW_EXPORT_DIRECTORY
python -m pytest -q v3/test_country_foundation.py v3/test_country_indicators.py
```

Only the WDI importer makes network requests. Refreshing an immutable snapshot
requires review and a code release; no automatic feed is enabled. The builder's
Shapely/pyproj dependencies are not needed by the serving process.

The standalone export includes normalized SQLite views `country_population`
and `country_boundaries`, country-only sources, national indicators, CSVs,
GeoJSON and a validation report. It excludes operational and humanitarian
observations. Deleted source bytes are removed by VACUUM.

## Limits and subsequent work

There are no commune polygons, locality coordinates, international neighbour
polygons, routing network, facility inventories or climate time series in this
increment. National service indicators are not evidence about any facility or
commune. The stored hospital-bed series is historical and must retain its year.

PostGIS is not required for this bounded immutable overlay: area and topology
are calculated once and served from the existing packaged-store architecture.
A later interactive spatial store should reuse these release identities and
provenance. Enabling extensions or changing the shared production schema is a
separate consequential change requiring owner approval.

## Attribution

INSTAT: Ce produit a été adapté à partir des informations de l’Institut national
de la statistique du Mali, qui sont sous licence conformément à l’Accord de
licence de données ouvertes de l’INSTAT.

- INSTAT source: https://www.instat-mali.org/laravel-filemanager/files/shares/rgph/repvila-rgph5_rgph.pdf
- INSTAT terms: https://www.instat-mali.org/laravel-filemanager/files/shares/doc/conditions-utilisation-donnees-ouvertes_doc.pdf
- COD-AB: OCHA FISS / HDX, Mali COD-AB, CC BY 3.0 IGO. https://data.humdata.org/dataset/cod-ab-mli
- WDI: World Bank; underlying indicator providers retained in each series,
  including WHO/UNICEF JMP, UNESCO UIS, FAO and ILO where reported. Dataset
  terms: https://datacatalog.worldbank.org/public-licenses
