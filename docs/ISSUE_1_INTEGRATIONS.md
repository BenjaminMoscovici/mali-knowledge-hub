# Source-aware FONGIM, OCHA 3W and needs retrieval

The V4 web service starts `v3/web_api.py` and uses repository-versioned
`analysis_core.py` and `knowledge_hub_runtime.py`. The repository-root Streamlit
app is a separate legacy entry point that downloads its runtime from Storage;
this increment does not change that application or its runtime bucket.

Named humanitarian sources and NGO questions reach research before geographic
shortcuts. Explicit OCHA 3W/5W lookups select the existing packaged Q1 2026 3W
records; no new ingestion or separate verified 5W feed is implied. An HNO-only
lookup uses the stored national HNO observations. Other joined needs questions
retain independent stored HNO, DTM and Cadre Harmonise plus live HAPI when
requested. Each measure keeps its period, population category, administrative
resolution and method. National context cannot become a local needs estimate.

FONGIM ongoing-status queries filter projects before deriving every organization,
sector, location and aggregate. "Currently" means source-reported ongoing status
in the dated snapshot, not verified delivery today. Original dates remain visible,
including conflicts with status. Queries without that filter retain closed
records. Project IDs and synchronization/snapshot identifiers remain provenance;
project/location or sector associations must not be added as distinct projects.

OCHA presence evidence carries source release, exact sheet/row locators, record
count and bounded source-record/span identifiers (truncation explicitly marked).
Actor labels are not resolved cross-provider identities. Presence does not prove
active delivery or reach, and missing records do not prove no assistance. A 2027
or current request cannot change the Q1 2026 source period. Unmatched explicitly
requested operational administrative labels never become national totals.

HAPI exceptions retain independently acquired stored evidence and add an explicit
availability notice, without fabricating local observations or exposing provider
exception messages. Empty presence sources similarly state unavailability.

Request metrics expose an allowlisted source-selection/execution trace: source
status, row counts, release/period, FONGIM status filter and sync date. They do not
include questions, credentials, raw provider errors or account records.

Tests exercise routing, actual FONGIM aggregation, actual independent research
workers under offline/empty HAPI, packaged source provenance, empty sources,
unknown geography and the 15 Issue #1 question routes. Operational live test
receipts and project tracking stay outside the public source repository.
