# Mali Knowledge Hub source integration — 2 October 2026

## Authorized systems

Repository `BenjaminMoscovici/mali-knowledge-hub`, branch `v4-frontend-rewrite`.
V4 test: https://mali-knowledge-hub-v4-test.onrender.com/
Render service `srv-davpdjugekts73ev4v3g`; GIZ Supabase `hofoubbmepacdljeablj`.
The original public MKH service and all unrelated projects remain untouched.

Rollback: deployed foundation milestone `74611e513046efbb2370f1b68344707ad382462a`.
The local equivalent is tagged `rollback-local-wave1` at `811ba7e`.
Operational wave deployed `52071d2e9e0f7af780e89f9740af14e3a29b2ff6`;
source-link UI deployed `dc0777d466736f3c294bb4703f96d7029c1db103`.
Applied migrations are additive source infrastructure. Existing data remain.

## Actually integrated and exposed: operational wave

| Source | Records | Reference coverage | Retrieval |
|---|---:|---|---|
| OCHA Mali 3W Q1 2026 | 5,413 | Source regions/cercles/communes, January–March 2026 | 2 October 2026 |
| IOM DTM Round 83 | 467 | Public commune aggregates, September 2025 | 2 October 2026 |

DTM categories: 227 internally displaced, 126 returned-IDP, 114 repatriated-person rows.
Village/site fields are excluded. Stocks are distinct from movement flows.
OCHA activity, project title, start/end date, targeted and reached fields are
blank: this release establishes presence only, never active/completed delivery.
Actor full-name/acronym pairs are labels, not resolved global identities.

Region/cercle matching requires agreement of P-code, name and parent. Commune
labels remain source-only until approved crosswalks exist. Issue occurrences:
5,661 commune-label-only; 305 code/name/parent conflicts; 48 unavailable codes.
There are 171 crosswalk proposals in the prior foundation, none approved.
FONGIM, CH and some DTM hierarchies use older region boundaries; the word
Mopti does not imply identical scope across source releases. No coverage ratio.

Database audit after this wave: population observations 41,751; geo units
14,099; source records 5,880; private source table RLS enabled; no anon or
authenticated SELECT; three indexes including PK; eight constraints before
food-security extension. Existing operational paths remain compatible.

## Real joined user test

Question: In Mopti region, what needs and displaced populations are documented,
which actors/sectors are recorded by OCHA 3W and FONGIM, and what can we conclude
about delivery or coverage?

Live guest answer used 49 evidence items from needs documents/HAPI, FONGIM,
COD/HPC, OCHA 3W and DTM. It correctly distinguished:

- HAPI 2025 selected Admin2/locality needs from region totals;
- OCHA Q1 2026 source-labelled Mopti: 301 rows, 40 actor labels;
- FONGIM: 257 unique projects, 622 locations, last sync 28 August 2026;
- DTM September 2025: Mopti commune 13,582 IDPs, Socoura 13,002 IDPs;
  returned-IDP and repatriated categories separate, Haire geography conflict;
- presence versus delivery/reach; no defensible coverage ratio or evidence of
  absence when source records are missing.

Direct evidence: source counts/labels, needs observations, stock estimates.
Synthesis: needs and recorded actors share thematic topics/place labels.
Not established: identical geography boundaries, actual delivery, current
October displacement, needs met, effectiveness, population coverage.

Source citations open original HTTPS files and show exact worksheet rows.
Guest answer restored on browser reload. Authenticated Hub research is not
live-verified: logged-in GitHub/Supabase sessions do not constitute Hub login.
Conversation ownership/persistence regression tests remain passing.

## Food-security/financing wave: integrated and exposed

113 CH observations (112 area rows plus one national factual-table extraction),
49 FTS plan/year records. Latest Mali workbook exercise is late 2025, despite
March 2026 filename. It has 56 current and 56 projected analysis areas.
CILSS July 2026 bulletin explicitly carries Mali's October/November 2025
projection forward: it is not a fresh 2026 assessment. Phase-5 printed dash
stays missing. CH is not relabelled IPC. FTS national figures are requirements
and total reported funding, not reached persons or solely disbursements.

Migration `20261002154155_food_security_financing_wave.sql` applied successfully
after inspecting the correct table and existing constraints. It preserves
presence/displacement checks, foreign keys, RLS and permissions and adds CH
and funding semantic checks. Live commit `254742a564e15d3e7868d1dfa6288deed837e07c`; all 162 records confirmed in Supabase. The real Mopti food-security/presence/funding test passed with exact CH and FTS citations, older geography limitations, projected versus current periods, and no unsupported coverage claim.

Validation at this checkpoint: 79 tests and two subtests pass (`pytest -q v3`).

## Source failure protocol and next wave

REACH/MSNA: public metadata verified; direct bulletin/methodology downloads
return 403 and published reuse terms require review. No REACH ingestion is
claimed. Registry status `licence_review_required`. No public HDX Mali MSNA
aggregate package was found in the limited alternate retrieval attempt.
Request authorized aggregate releases/methodology and reuse permission;
retain sampling dates, representative geography and inaccessible-area limits.

World Bank: current v3 API acquired (215 exact-Mali projects, regional projects
excluded); older v2 response rejected as stale. Some v3 Active projects have
past closing dates and must be flagged, not treated as confirmed ongoing.
IATI: HDX country export acquired. World Bank publisher 44000 subset has
136 sector rows / 36 activities; financial values repeat per sector and
must not be summed. Location export has country/coordinate contradictions;
those coordinates will not be published. Wider publisher licences need review.
IEG P144442: accessible historical project review. Only small factual,
paraphrased findings with page citations may be exposed; the complete PDF/full
text is not redistributed under an assumed open-data licence.

## Acceptance states

Architecture prepared: yes. Operational source access verified: yes.
Operational data staged/integrated/exposed: yes. CH/FTS access and staging: yes;
CH/FTS publication and live answer tests passed. WB/IATI/IEG 254 records staged and validated; deployment/live verification pending. Full programme/user
acceptance: no. All-source, exact local project/funding joins require further
geographic/actor reconciliation and richer activity/funding evidence.

Project/learning wave staged: 215 exact-Mali WB profiles, 36 WB IATI activities, three IEG findings. All 36 exact project IDs match profiles. FONGIM ending-intent retrieval now selects reported active projects in the next 180 days and flags overdue active dates. Validation: V3 83 tests plus two subtests; V2 11 tests; JavaScript syntax check passes. The combined importlib test invocation failed collection because these version directories use top-level imports; running each version in its proper import context passes.
