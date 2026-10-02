# EU / Team Europe integration — live acceptance, 2 October 2026

The V4 test Hub now retrieves EU programming, country activity records, selected
Team Europe initiatives, EIB profiles and DG ECHO programming alongside existing
needs, national plans, operational presence, displacement and food-security evidence.
The original public MKH service and unrelated systems were not modified.

Repository: BenjaminMoscovici/mali-knowledge-hub. Branch: v4-frontend-rewrite.
Test service: https://mali-knowledge-hub-v4-test.onrender.com/
Baseline / rollback: 3c2ad6c49c21e92113691348b16506068b5e9934.
Source-code commit: bdb09eb70d342afbe532aab61888b9216886a244.
Applied migration commit: 3f3e736cf8240b7b9b1290935fe8cc381b5edd56.
Both deployments were observed live; the following commit adds acceptance metadata
and stronger historical-record warnings without changing the ingested snapshot.

## What is actually integrated

322 evidence records across 10 active source releases were verified in the correct
GIZ database. Every record retains provider, URL, retrieval timestamp, original
file checksum, release and record IDs, source scope and page or CSV row locator.
These are selected factual observations and activity records, not 322 documents.

| Source subset | Records | Coverage and reference period | Last successful retrieval (UTC) |
|---|---:|---|---|
| DG INTPA IATI country activities | 134 | 100% Mali country allocation; mixed historical and reported future dates | 2 Oct 2026, 15:25:03 |
| DG ECHO IATI country activities | 172 | Same country allocation rule; 37 multicountry activities excluded | 2 Oct 2026, 15:25:03 |
| Joint Programming / NDICI original annex | 3 | National; Joint Programming 2020–24 and MIP 2021–27, original 2021–24 envelope | 2 Oct 2026, 16:50:04 |
| Current EU Mali overview | 3 | National; 2021–24 reported commitments and 2025–27 intent | 2 Oct 2026, 16:49:09 |
| Team Europe climate and youth proposals | 2 | National; January 2022 design metadata | 2 Oct 2026, 16:50:08 |
| Capacity4dev Mali-Centre project | 1 | Central Mali source label; project 2018–2023 | 2 Oct 2026, 16:59:07 |
| EIB signed project profiles | 3 | Bamako city descriptions; signatures in 2013, 2017 and 2020 | 2 Oct 2026, 16:56:19 |
| DG ECHO HIP 2026 technical annex v5 | 4 | Mali subset; 2026 programming, version dated 16 Sep 2026 | 2 Oct 2026, 16:50:18 |

The successful same-day IATI HDX CSV was retained unchanged. Later refresh,
registry and publisher XML timeouts are failures, not new successful retrievals.
Full timestamps, checksums, URLs, licences, limits and next actions are in
source_wave5_registry.json and the canonical source_registry.json.

Selected exact document locators: original combined 140-page Joint Programming /
NDICI PDF pages 79, 87 and 94; printed annex page 16 is PDF page 94. ECHO's
45-page technical annex: PDF page 5 (Mali finance row), pages 28–30 (priorities).
Both finance tables were visually checked. The live citation drawer was verified
to show the original PDF link, page 5, publication date and retrieval date.

## Finance and geography safeguards

The original EUR373m envelope is indicative programming for 2021–2024; EUR151m
is the current country page's provider-reported grant commitments for that period.
ECHO's EUR32m Mali allocation for 2026 is indicative (EUR30m humanitarian aid,
including education in emergencies; EUR2m preparedness). EUR276m is the whole
West/Central Africa HIP, not Mali. None establishes disbursement or results;
these amounts cannot be added or subtracted into a delivery gap.

The IATI fallback supplies identifiers, title, publisher/funder references,
source sector rows/percentages, country allocation, registry status and reported
start/end dates. Implementing and participating organisations, original financial
transaction semantics, linked documents and results are absent and explicitly null.
Raw CSV commitment/spend fields are preserved with warnings, excluded from answer
context. Original currency, transaction type, value date and hierarchy are missing.
No financial analysis is performed on those export totals.

Source sector codes remain distinct from title-derived thematic relevance. The
WASH-titled INTPA activity 2023-PC-34274 is coded democratic participation/civil
society in the source; the Hub does not silently change that source code.
Past reported ends receive explicit historical warnings; an Implementation status
with a past end receives an unresolved status/date-conflict warning. Future starts
are not promoted to confirmed current delivery. Planned versus actual date types
are unavailable in the fallback.

Titles mentioning Mopti or Gao are geographical mentions, not approved local
activity locations. Three EIB Bamako city assignments remain unresolved below
city level; no arrondissement or commune is guessed. EIB profiles retain the
source label proposed approximate finance even where status is Signed; closing,
approval, disbursement and results are unknown. Linked EIB supporting documents
are identified on profiles but their contents are not ingested.

TEI participant lists describe historical proposals, not today's actor roster.
Capacity4dev reports Mali-Centre as Completed with a EUR3m project budget;
neither that status nor budget establishes delivery, disbursement or impact.
Only attributed factual metadata is redistributed from contributor platforms and
EIB, without contributor descriptions, personal owners or copyrighted media.

Existing COD/INSTAT units, P-codes, sex-disaggregated population retrieval and
unresolved geographic matches remain available. Source communes, versions and
parent conflicts are still exposed; no coverage ratios use unapproved crosswalks.

## Database migration and compatibility

The source-foundation baseline already existed in GIZ project hofoubbmepacdljeablj.
A transactional additive EU migration extended the source-type allowlist with six
EU types and added evidence-stage and country-allocation constraints. Seven prior
source checks were retained. No tables or rows were removed; RLS, policies,
grants and indexes were unchanged. The prior constraint definitions and counts
were captured before migration; rollback code remains available.

| Check | Before migration | After migration | After publication |
|---|---:|---:|---:|
| Source records | 6,296 | 6,296 | 6,618 |
| Geographic units | 14,099 | 14,099 | unchanged by this wave |
| Population observations | 41,751 | 41,751 | unchanged by this wave |
| Source-table constraints | 13 | 15 | 15 |
| Source-table indexes | 3 | 3 | 3 |
| RLS | enabled | enabled | enabled |
| Source-table policies | 0 | 0 | 0 |

service_role retains SELECT/INSERT for source publication; source records are not
exposed directly to anon or authenticated database clients. Publication verified:
306 eu_activity, 6 eu_programming, 2 eu_tei, 1 eu_project_metadata,
3 eib_project and 4 echo_programming records; 10 active release pointers.

Validation: 94 V3 tests and 2 subtests passed; 11 V2 tests passed; JavaScript syntax
passed. Meaningful tests cover exact-country filtering, identifier deduplication,
money semantics, historical records, source-sector preservation, original locators
and real EU/3W/DTM/CH joined retrieval. Authenticated persistence regression tests
passed. Guest research and guest conversation restoration after reload were checked
live. A live authenticated Hub session has not been verified; signed-in infrastructure
sessions are not a substitute. Cost/latency logging remains enabled.

## Real user-question acceptance

**Question 1: What are current EU / Team Europe priorities, and how do programming,
commitments, ECHO allocations and project status differ?**

Before this wave the same question could not find EU evidence. After deployment,
the guest answer cited 66 evidence items, including original programming, the current
country page, ECHO and activity records. It separated the original EUR373m envelope,
EUR151m reported commitments and EUR32m indicative Mali ECHO allocation, explicitly
rejecting a fabricated delivery gap or disbursement total. It described current
youth/basic-service/resilience priorities and explained that registry status does
not verify results. Citation E51 was inspected: ECHO PDF page 5, published 16 Sep
2026, retrieved 2 Oct 2026, and an Open original source link.

**Question 2: In Mopti, how do EU/ECHO activities and priorities align with documented
needs and Mali's priorities, and which food-security actors are recorded?**

The live answer joined 85 evidence items: government frameworks and HNRP/HAPI,
FONGIM, OCHA 3W Q1 2026, DTM Round 83 September 2025, Cadre Harmonisé current and
projected periods, EU programming and selected activities. It reported 11 food-
security actor labels in 30 OCHA source rows: AMSODE, CARE, DRC, FEDE, IMADEL,
ONG IAD3, IRC, NRC, PAM, SCI and WVI. Activities, targets and reached fields are
blank, so this establishes recorded presence only, not local coverage or EU funding.

The answer identified INTPA's water/sanitation-titled 2023-PC-34274 (reported
8 Dec 2023–10 Dec 2026) and ECHO's health/nutrition-titled 2017/91029 (reported
1 Jan 2017–30 Apr 2018) as source records mentioning Mopti. The historical ECHO
record is not evidence of present response. Inspection of the original row citations
prompted the additional explicit historical-date warning in this final patch.

Directly evidenced: provider priorities, source-reported activity dates/status,
OCHA actor presence, selected DTM displacement stocks, CH estimates and Mali
framework priorities. Thematic alignment is an inference, not proof of programme
implementation, causal contribution or local service coverage. Original MIP explicitly
references CREDD; alignment with later SNEDD or a specific PDSEC is not established
by that original document.

Dates and precision differ: OCHA is Q1 2026; DTM is September 2025 stocks, not
flows; CH current September–December 2025 and projected June–August 2026 are
historical analysis/projections, not October 2026 observations. Commune labels and
older geography versions are not fully reconciled. Missing: granular 5W delivery,
EU grant/transaction links, verified local implementers, results, MSNA access and
approved crosswalks. No EU actor funding attribution, current coverage ratio,
local financing adequacy or verified outcome can be concluded.

The guest conversations are retained in the test browser; their guest URLs are not
shared durable conversation links. Reproduce the questions at the public test URL.

## Failed sources and next unblocked work

AAP2024 C(2024)1428, support measures 2023–2025 C(2023)5124, older action/amendment
ZIPs and original IATI XML remain metadata_only; ZIP downloads returned 429 and
XML routes timed out after bounded different attempts. Their contents and approved
action amounts are not integrated. MTR2024 C(2024)7502 was accessible through the
web reader but not activated as page-level evidence; it remains public_access_confirmed.
Its regional EUR238m complex-settings amount must not be assigned entirely to Mali.
Current country-overview evidence separately supplies the 2025–2027 intent.

SIPRI's final 2023 report *Listen to us!* has verified publication metadata, but
French direct download timed out and both language PDFs exceeded the web reader
size limit. It is metadata_only; no findings or exact pages are integrated. It is
the next learning candidate when an accessible original/reuse notice is supplied.
Institutional request drafts in SOURCE_ACCESS_REQUESTS.md specify exact missing
files and semantics; no request has been sent. Blocked sources do not stop other work.

## Delivery stages

| Stage | Observed result |
|---|---|
| Architecture prepared | Import, bounded retrieval, safe publication and tests implemented |
| Source accessibility verified | Ten original source subsets successfully retrieved; failures separately registered |
| Data staged | 322 legitimate records validated in the reproducible snapshot |
| Data integrated | All 322 published, 10 active releases verified in correct GIZ database |
| Data exposed in user answers | EU priorities and joined Mopti guest answers passed; exact source links/locators checked |
| Full acceptance completed | No: originals/actions, transactions, granular delivery, learning findings, approved geographic joins and live authenticated acceptance remain incomplete |

Users can now compare EU programming and selected activity/project evidence with
needs, actors, national priorities and dated displacement/food-security evidence.
They still cannot infer actual disbursement, complete EU portfolio coverage,
local delivery or results from the selected public subset.
