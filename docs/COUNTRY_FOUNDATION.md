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
| World Bank CCKP / CRU | National MLI climatology, CRU TS 4.09, 1991–2020 normal period | `country_climate.json.gz`; four variables × twelve monthly normals plus one annual normal, original API responses, units, checksums and attribution |
| Natural Earth / NACIS | Layer 5.0.0, pinned source revision 2 June 2022; survey dates unspecified | Ten clipped source features, nine river IDs and eight name labels; generalized cartography, not an official hydrographic census |
| NOAA NCEI ETOPO | ETOPO2022 v1, 60 arc-second surface derivative, EGM2008 heights; publication 1 October 2022; inputs vary | Country and twenty COD admin1 terrain summaries, original source metadata/checksums and masked GeoTIFF; no population join |

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
- `What is the climate of Mali?`
- `Which month is wettest in Mali?`
- `Average daily maximum temperature in Mali`
- `What are the major rivers in Mali?`
- `Niger river in Mali`
- `What is the mean elevation of Gao region?`
- `Compare mean elevation in Gao and Mopti regions`
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
/api/country?metric=climate&variables=pr,tas&aggregation=both&period=1991-2020
/api/country?metric=climate&variables=pr&aggregation=monthly&month=8
/api/country?metric=physical_rivers
/api/country?metric=physical_rivers&name=Baoulé&river_id=499
/api/country?metric=river_geometry&name=Niger
/api/country?metric=terrain&level=region&name=Gao
/api/country?metric=terrain_raster
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
python v3/import_country_climate.py --output v3/country_climate.json.gz
python v3/build_country_physical.py --inputs NEW_SOURCE_DIRECTORY --fetch \
  --output v3/country_physical.json.gz --raster v3/country_terrain.tif
python v3/export_country_foundation.py --output NEW_EXPORT_DIRECTORY
python -m pytest -q v3/test_country_foundation.py v3/test_country_indicators.py v3/test_country_climate.py v3/test_country_physical.py
```

Only the WDI/climate importers and the explicit physical-builder `--fetch` step make network requests. Omit `--fetch` to rebuild physical layers offline from the retained input files and manifest. Refreshing an immutable snapshot
requires review and a code release; no automatic feed is enabled. The builder's
Shapely/pyproj dependencies are not needed by the serving process.

The standalone export includes normalized SQLite views `country_population`
and `country_boundaries`, normalized climate tables and `country_climate`, normalized physical tables and `country_rivers`/`country_terrain`, national indicators, CSVs,
GeoJSON and a validation report. It excludes operational and humanitarian
observations. Deleted source bytes are removed by VACUUM.

## Physical geography and spatial provenance

`country_physical.json.gz` retains source identities, source bytes' checksums,
selected original river features, the NOAA metadata response, methods and
quality results. River and terrain queries cite both their physical source and
the COD release used as the spatial mask. INSTAT population identities are not
joined to this overlay. The original source geometry is not silently repaired.

Natural Earth 5.0.0 is pinned to source revision
`ca96624a56bd078437bca8184e78163e5039ad19`, rather than a changing master URL.
The source revision date is not a survey date or an exact layer publication
date. The ten country-intersecting features retain their global source-row
occurrence and Natural Earth `rivernum`. Two Niger features are respectively a
river and lake centerline, sharing one river ID. Both Baoulé rivers retain
distinct IDs499 and816; no destructive deduplication by name is applied.

This is 1:10-million cartographic context: names, generalized traces and source
attributes, not a complete watercourse inventory, present flow, navigability or
an official river length. The GeoJSON clips these traces to the COD country
outline. No commune/settlement crossings or links to HydroRIVERS are inferred.
Stored trace lengths describe those clipped line geometries only.

The NOAA ETOPO2022 v1 surface product is a composite global relief model. This
increment uses its **60-arc-second derivative**, approximately1.85km north–south,
not the original15-arc-second grid. Heights are metres relative to EGM2008
(EPSG:3855), with WGS84 longitude/latitude (EPSG:4326). The source catalogue
global input range1998–2022 does not date each Mali cell. Publication2022-10-01
is stored separately from retrieval; no current/single-year measure is claimed.

The NOAA service uses0–360° longitude. Two native-resolution subsets are joined
at360°/0°, transformed to−180–180° and validated for equal latitude axes,
uniform spacing, no duplicated/missing seam columns, dimensions, units, datum,
finite values and NoData. No resampling or interpolation occurs. The north-up
GeoTIFF is masked to Mali; outside-country cells are NoData, not zero. Exact
raster round-trip and pixel-data checksum are checked.

Terrain summaries select grid-cell centres strictly inside COD polygons and
weight the mean by each cell's WGS84 ellipsoidal area. All384,668 selected Mali
cells belong to exactly one of the20 COD admin1 units; there are no unassigned
or multiply assigned selected centres. National plus20 admin1 summaries are
stored. Bamako is identified as a district. Selected whole-cell area approximates
the boundary and is not an official or surveyed area. Grid minima/maxima are
**not surveyed extrema or peaks**; the coarse grid smooths local relief.

Raster and vector processing dependencies are builder-only. Runtime queries
read precomputed data; the fixed GeoTIFF download verifies its checksum and
does not accept a caller-supplied filesystem path. The standalone database
includes normalized physical-source, river, terrain and raster-asset tables,
with original geographic/release IDs and foreign keys. The separate GeoTIFF
and river GeoJSON are usable in GIS software.

## Climate interpretation and validation

The climatology API labels monthly normals `1991-MM` and the annual normal
`1991-07`. These coordinates represent the **whole 1991–2020 normal period**;
they are neither observations for 1991 nor, for the annual row, July values.
The API keeps the country code MLI and World Bank aggregation geography. There
is no link to civil administrative units and no allocation to settlements.

The portal's active climatology configuration requests TS 4.09; its general
collection documentation still describes TS 4.07. The importer pins 4.09 in
both requests and retains the configuration URL. No different CRU versions or
climate reference periods are combined. The upstream release page is dated
March 2025, but an exact CCKP product publication date is not supplied and
remains null. Retrieval time is retained separately.

All 52 source values must be finite and complete, with exactly the four expected
variables and national MLI geography. Original metadata verifies precipitation
in mm and temperature in °C. Annual precipitation is independently checked
against the sum of monthly normals, and annual temperatures against calendar
day weighted monthly values across the 30-year period. Checks allow only
two-decimal source rounding. Minimum ≤ mean ≤ maximum is checked for every
aggregation. A missing month, unexpected place, unit change, null or inconsistent
annual value aborts the import rather than producing a partial snapshot.

All eight underlying NetCDF product metadata records are retained with byte
checksums. Their version, period, collection, variable, aggregation, scenario,
units and Open Government Licence v3 statement must match the requested product.
This independently confirms the pinned release and units beyond API URL labels.

`tasmin`/`tasmax` are averages of daily minima/maxima, not recorded extremes.
The wettest/warmest monthly normal is a comparison of national averages, not a
claim about every location, a rainy-season onset, a forecast or a current
condition. CRU's station-interpolated 0.5° grid has varying station coverage.
The bounded chat route refuses unsupported periods, current weather and mixed
or subnational scopes. The climate API also rejects administrative allocation.

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

Source screening for subsequent layers (checked 15 October 2026):

| Candidate | Source date/framework | Current decision |
|---|---|---|
| [Current COD-AB catalogue](https://data.humdata.org/dataset/cod-ab-mli) | Catalogue still describes v03, 20 admin1 and 160 admin2 features; metadata updated April 2026 | Reuse the existing validated release. No commune layer is listed. The latest archive download was blocked at its redirected host, so byte identity with the latest resource was not reverified. |
| [HOT roads](https://data.humdata.org/dataset/hotosm_mli_roads) | OpenStreetMap extract dated 5 October 2026; ODbL | Candidate mapped road inventory only; not evidence of current passability or travel times. |
| [HOT education facilities](https://data.humdata.org/dataset/hotosm_mli_education_facilities) | OpenStreetMap extract dated 5 October 2026; ODbL | Candidate mapped-feature inventory; completeness, duplicates and spatial assignments need validation before integration. Not an official census or evidence of operational status. |
| [HOT health facilities](https://data.humdata.org/dataset/hotosm_mli_health_facilities) | OpenStreetMap extract dated 5 October 2026; ODbL | Same mapped-feature limitations. No inference of staffing, services, opening status or facility coverage. |

These candidate rows are research metadata, not loaded evidence. No facility
or road observations were imported in these country increments. HydroSHEDS v1
river/terrain products remain deferred for a separate redistribution review:
the v1.4 technical documentation Appendix A, clauses2.1.2–2.1.3, contains
distribution/sublicensing conditions. This increment uses NOAA CC0 and Natural
Earth public-domain data instead. No HydroSHEDS data is packaged. The remaining
commune-boundary gap is a qualification gap, not a claim that such data does
not exist. Civil administrative and health-reporting boundaries are not
interchangeable.

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
- Climate: Climatic Research Unit (University of East Anglia) and Met Office;
  national aggregation via World Bank CCKP. Upstream Open Government Licence v3:
  https://crudata.uea.ac.uk/cru/data/hrg/cru_ts_4.09/
  and https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/
  CCKP source: https://climateknowledgeportal.worldbank.org/country/mali/climate-data-historical
- Rivers: Made with Natural Earth. https://www.naturalearthdata.com/about/terms-of-use/
- Terrain: NOAA National Centers for Environmental Information (2022), ETOPO2022,
  https://doi.org/10.25921/fd45-gt74. CC0-1.0;60-arc-second derivative accessed
  through NOAA OceanWatch ERDDAP. https://www.ncei.noaa.gov/products/etopo-global-relief-model
