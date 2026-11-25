# MKH V3 development preview

Run the app from this directory with `python -m uvicorn app:app --host 127.0.0.1 --port 8127`.
Run regression checks with `python -m unittest discover -s tests -v`.

The `v3-development` branch owns the preview. Render builds `mkh-v3/requirements.txt`
and serves this directory on the isolated **mali-knowledge-hub-v3-dev** Free web service.
The **mkh-v3-dev** Supabase project holds preview sessions and owner-scoped conversations.
Deploys are triggered manually after verification. The Render service supplies project
configuration, including `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `OPENAI_API_KEY`.
An independent `MKH_HISTORY_SIGNING_KEY` can keep transcript signatures valid across model
credential rotation. Chat supports guests and signed-in users with the same research
tools and Fast and Deep modes. Guest context is held temporarily in the service.
Signed-in users can save and reopen conversations.

Accounts use Supabase email and password. Supabase sends password setup, recovery,
and signup verification links back to the V3 callback. Add
`https://mali-knowledge-hub-v3-dev.onrender.com/auth/callback` under Redirect URLs in
the V3 Supabase project. Its built-in mail service sends to preview team addresses.

## Sources and evidence

`canon/` holds the published preview releases. The INSTAT geography and census methodology,
Mali Cadre Harmonisé tables, and CILSS bulletin extracts come from the approved public
packages on V2.1 at `c7a0efb6ff4cf22eae020d494608c8a8e7897914`. Each manifest carries the
original URL, release, licence, scope and limitations. The import script reads the pinned
V2.1 files and writes only the V3 extracts. Workbook numeric values, missing values,
source-era administrative names and row locators are retained. The CILSS bulletin uses
public factual extracts with page references.

The World Bank connector retrieves allowlisted national series. The chat loop uses typed
source discovery, document navigation, geography, SQL and live-API tools. Read-only SQL
runs against local release tables with restricted operations, bounded runtime and result
limits. SQL evidence includes the exact operation and the input releases. The research tools combine lexical BM25 ranking with multilingual OpenAI embeddings
and reciprocal-rank fusion. Only published text vectors are cached across requests.
A provider failure falls back to local text search and is reported on the turn.
The public catalogue uses local text search. Use `MKH_SEMANTIC_SEARCH=off` for
offline tests or an explicit lexical-only comparison.
External web research defaults off via `MKH_WEB_RESEARCH`.

## Development checks

Use the preserved V2.1 evaluation evidence as regressions. For the first paired browser
run, record the serving revision, answer, tool/citation support, elapsed time, assignment
cost and whether the result can be used professionally. Keep failed or interrupted
attempts. Use the same wording and follow-ups in V2.1, a frontier assistant without MKH,
and Fast and Deep in V3.

Development prompts cover a French Mopti briefing, historical-period comparison, a
geographic-scope follow-up, Mopti homonyms, a commune-only evidence gap, unknown phase
values, national cereal-yield context, failed live API, census versus projection, ordinary
editing, a malicious source instruction and a draft or withdrawn release. Independent
release qualification uses a separate holdout. The first validation suite uses test
doubles for Supabase authenticated state and model responses, and a metadata-only
unfamiliar-source fixture.

Hosted verification on 25 November 2026 used revision `929bd4a`, with external web
research off. Fast returned the French Mopti comparison after recovering from one SQL
tool error. The two sums matched the preserved workbook rows at two decimal places.
Deep retained the historical scope on follow-up, identified the June–August 2026
projection, and cited the live national WDI cereal-yield observations. The two
assignments took 23.10 and 13.96 seconds on the server, with combined estimated
model charges of US$0.0884. This run exercised the hosted companion; the real
paired browser qualification remains open. Email/password signup, recovery and saved history were subsequently exercised in Chromium with isolated Supabase services.

## Research and deliverables

Reviewed public releases include OCHA plan funding, World Bank project profiles, IATI
activity records, two IEG evaluation releases, EU programming and partnership extracts, COD regional
polygons, and 17 national WDI series in an immutable snapshot. The live WDI connection
covers those reviewed indicators as well as cereal yield. The offline
importer checks the pinned package digests and retains publication limitations and
record or page locators. Aggregates are computed over native tables. A registered
identifier permits an inner join across releases. The evidence records both input
versions, the relationship and the executed SQL. Live observations and complete
calculation results support a second calculation with a replayable input snapshot.

The companion can attach tables, charts or maps backed by issued result rows. Users
can download a standalone printable HTML brief with references, evidence JSON and CSV
data. Display polygons use a simplified geometry. Source areas are measured on the
original geometry. Working instructions travel with a conversation. Optional personal
notes are stored separately under owner-only row-level security and can be inspected,
edited, disabled and deleted. Guest memory is temporary.

Duplicate or missing identifiers, missing values, source withdrawals and geographic
vintages remain substantive limits on combination. The development suite covers
these boundaries where supported. Final qualification requires independent professional
review and a separate holdout of at least 100 cases.

A deployed Chromium check on revision `890bcdd` used the 2024 OCHA national plan.
The French brief calculated a USD 393,244,791 gap and 43.95% coverage from the named
plan, kept unspecified funding separate, and distinguished financing from expenditure.
The standalone brief and CSV both downloaded. Fast took 22.21 seconds, estimated
USD 0.017422 including the on-demand search index. An initial browser check also
identified a notes control binding issue. It was corrected and the account memory
lifecycle was verified through Chromium against isolated Supabase Auth and PostgREST.
Two-account database checks verified owner isolation.

Browser assignments run on the existing web instance and expose an owner-bound status
URL for progress, reconnection and cancellation. Refreshing the tab rejoins a running
assignment. The service retains completed jobs for up to 15 minutes, with a bounded
in-memory cache. A new service instance ends pending guest jobs. Signed-in completed
turns use Supabase. The streaming API remains available for existing clients.

A COD map exercise on revision `646809b` correctly ranked five regions but returned
only a table. The exhibit ledger now retains multiple presentations of the same
calculation and checks geographic identifiers against the published release's rows,
including SQL aliases. The attached map uses the same source values as the CSV.

Two reviewed releases extend analysis to reported humanitarian response and displacement.
OCHA's Q1 2026 3W workbook contributes 5,413 presence rows. IOM's September 2025
DTM Round 83 contributes 467 public aggregate stock records. Both preserve native
categories, row locators and source-era region labels. Only region IDs confirmed by
the original package against COD v03 can join or map. The calculation records how
many rows each input lost. A join that would multiply repeated identifiers is refused.
An issued table, chart or map can be downloaded with its evidence.

Source discovery searches catalogue descriptions, registered dimension values, passages
and indexed records. Current task requirements persist as quotations from the user's messages.
Signed-in chats archive older turns when the recent window fills. The assistant can reopen
previous work in that conversation, subject to current source approval and signatures.

The Source review panel is available to designated V3 editors. It accepts public CSV,
TSV, XLSX, text, text-bearing PDF and a declarative Mali WDI connection. Originals are
identified by their publisher URL and upload digest. Files remain private drafts until
an editor selects a version and publishes it. Editors can suspend a source, withdraw
it or restore an earlier version. Each research request checks the current publication
registry. Cached jobs, saved chat and recalled evidence are checked against the active
release. The preview intake limit is 1.5 MB per file and 5,000 worksheet rows. Scanned
PDFs require an accessible text version. Larger reviewed packages can use the offline
importer. AI metadata proposals use an editor-selected sample and require human review.

In a deployed November browser assignment, V3 computed 346,629.77 people projected in
CH Phase 3+ across eight historical Mopti analysis areas, and 11 distinct organizations
across 30 Q1 2026 3W food-security records in the current COD Mopti region. The follow-up
preserved the two geographies. The initial Deep turn reached a research limit and used
prospective language after the projection period. The next revision supplies the current
date in every investigation, supports independent tool calls in one round and gives the
model compact evidence while retaining the full inspection and export record.

A second professional assignment requested a regional map of reported nutrition-sector
organizations. The browser exposed a comparison between the data release and the boundary
release during rendering. The renderer now verifies the boundary version and fingerprint
from the calculation inputs. The browser regression replays the computed rows, verifies
all exported region values and checks that the standalone brief contains the rendered map.
