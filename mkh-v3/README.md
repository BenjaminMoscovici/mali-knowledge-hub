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

The V3 catalogue also includes full dated HDX snapshots of WFP market prices and
CHIRPS v2 subnational rainfall indicators, CRU national climate normals from the
reviewed MKH country foundation, and selected figures from Mali’s June 2026 general
budget execution report. Each release carries its source, scope and limitations.
The HDX tables use the dates, units, administrative identifiers and processing flags
provided by their publishers. The rainfall series uses WFP administrative areas.

INSTAT’s RGPH5 schooling report contributes all 20 rows of Table 1.4, comparing
census and school yearbook gross enrolment rates by sex in eight historical regions,
Bamako and the national total. The PRODEC 2 release contains French extracts from
pages 66, 70 and 71 of the adopted programme, covering targets and planned actions.

The `compare_sources` research tool checks the geographic frame, grain, measure,
units, evidence basis, declared dates and registered keys across releases. When
editors supply shared indicator codes, it also shows which selected releases declare
a measurement for each policy objective. A missing match is a gap in the cited
metadata. The model receives these checks during research and revision. Readers
can open **Compare sources** alongside the answer or inspect the exported evidence.

Large CSV releases use a reviewed column schema and a checksum-pinned SQLite
snapshot. Build a snapshot with `python scripts/pack_table.py MANIFEST SOURCE.csv`.
The build preserves source row numbers and missing values. The application opens the
table read-only for calculations. Review a new upstream release before republishing.

## Development checks

Treat an unsatisfactory answer as a way to discover a failure in a shared capability.
Trace it to the responsible layer, then exercise the change on an unfamiliar assignment
or source. Keep the original example as a regression. Exclude question-specific branches,
source lists embedded in prompts, and prewritten answers.

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
URL for progress, reconnection and cancellation. The browser subscribes to live tool
activity and draft answer text from the model. The server verifies evidence and persists
the turn before delivering the final answer. New Chat can stop the current run.
The Free preview admits 12 requests per user in a rolling five-minute window and 64
across the instance per rolling 24 hours. Model spending also has a per-assignment ceiling. Refreshing the tab rejoins a running
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

Each research assignment has a configurable ceiling for model and embedding estimates.
The preview defaults to USD 0.45 in Fast and USD 1.50 in Deep. Before each provider
request, the app budgets uncached input and limits the allowed output. The answer
footer displays the model estimate based on provider-reported tokens. External web
search is off. These per-assignment estimates exclude hosting and external web fees.
Use positive values for MKH_FAST_MAX_MODEL_USD and MKH_DEEP_MAX_MODEL_USD. Rolling
financial allowances by account and independent professional qualification remain open.

## Priorities for the next qualification

* **Complete source access.** The source drawer and Companion enumerate the current published
  registry with total counts. Model calls page through inventories and ranked topical matches.
  Qualify each release through inspection and an actual native operation, then repeat with
  unfamiliar sources and withdrawals. An inventory count alone establishes registration.
* **Research transparency.** Record executed tool activity with source titles, returned rows
  or passage counts, failures and progress. Show it during the assignment and alongside
  the answer on reopening. Verify that users can trace an important claim through its activity
  to the specific evidence or calculation. Personal reasoning and provider payloads stay private.
* **Economic sustainability.** Compare Fast/Sol and Deep/Astra on the same professional assignments.
  Predefine the acceptance rubric and count the cost of all attempts, retries and follow-ups in
  the numerator. Divide by independently accepted tasks. Record unknown costs separately and leave
  the metric undefined when no task passes. Report latency, evidence support and task success
  by task family alongside cost. Test scoped embedding caches, smaller input histories and routing
  to the least expensive qualified model in paired trials. Ship a routing change only when it
  preserves professional quality. Use observed task mix, volume and shared service costs to
  forecast monthly spend before expanding public access.

On 26 November 2026 the deployed browser returned all 16 registry IDs in Fast chat
and opened native content in each corresponding source drawer, including live WDI
observations. The inventory used zero embedding tokens. A local regression also traverses
165 published sources and excludes a withdrawn release. Each bundled document and table
was exercised through the model's actual tool dispatcher. A direct live WDI call failed
once and succeeded on retry. These checks establish reachability and basic use.

A paired browser trial on the same release asked for a financial decision note comparing
Mali's 2023 and 2025 humanitarian plans. Both modes identified HMLI23 and HMLI25, cited
their calculated gaps of USD 508,881,258 and 583,250,344, distinguished reported funding
from expenditure and suggested an appropriate check for the committee. Fast took 13.61 s
and Deep 20.35 s. This is an engineering check on one task. Fast paid for a cold semantic
index and Deep reused it. The estimates cover the reported inference and embedding usage.

Run `python scripts/task_cost.py evaluation/20261126-financing.jsonl` to reproduce the
per-mode cost per accepted task. Use a common task ID for all retries and follow-ups,
record failed attempts too and supply one final review per task and variant. An unknown
cost or pending review leaves the rate unreported. Expansion requires varied blind
professional assignments, order-balanced trials and comparison against provider billing.

Two Fast-mode guest assignments on the live preview each used three browser turns
to request, challenge and revise a French decision brief. A separate model reviewed
each conversation against a predeclared rubric and the original publications. The
Mopti market visit passed on the first trial. The initial Gao-to-Bamako education
revision omitted whether gross enrolment establishes retention. A shared indicator
check was added and the repeated education assignment passed. All nine turns completed
with a working source comparison drawer. Estimated inference and embedding charges
totalled USD 0.193692 across the two accepted tasks, including the unsuccessful trial.
Reproduce the result with `python scripts/task_cost.py evaluation/20261126-cross-source.jsonl`.
The estimate excludes the independent review and hosting.

### National inventory releases

The offline release command takes a Work ZIP, a separate JSON file of independently verified eligibility receipts keyed by Work ID, and a directory of original and evidence files. It uses Python 3.11+, `jsonschema` and Poppler's `pdftotext` for PDF pages.

```sh
python scripts/publish_inventory.py batch.zip receipts.json verified-files --canon canon
```

Receipts pin the original URL and SHA-256, the reuse evidence file and SHA-256, and the precise components covered by the grant. Each eligible receipt carries native release metadata plus PDF page numbers or a checksum-pinned JSON extraction. An existing equivalent component can be identified with `match_id`. Unresolved records can carry a reason. Missing qualification, invalid schema, changed bytes and ambiguous editions produce per-record flags. Successful additions are immutable and use the same catalogue, search, SQL and citation interfaces as other V3 sources. The checked-in inventory reports retain Work IDs and release decisions. Checked-in queue entries refer to original research archives by name and checksum.

### Full documents in the V3.1 Canon

A full-document edition uses the existing publication registry. Its manifest references a compressed, content-addressed package in `canon/documents/`. The Companion loads that package only through its active manifest, checks its digest and reuses its precomputed multilingual section embeddings. A rollback to the earlier manifest restores its earlier search scope.

Build a qualified PDF or HTML edition with the offline dependencies in `scripts/full_document_requirements.txt` and the runtime requirements. Install Tesseract and the edition’s language data for image pages. The rights receipt is JSON with `source_id`, `scope` (value `whole_work`), `basis`, `reuse_url`, `reuse_sha256`, and `upstream_sha256`. The two hashes bind the rights evidence and original bytes. Optional `ocr_language` uses Tesseract language codes. For HTML templates without a unique main element or article, `body_xpath` identifies one complete editorial body verified against the original.

```sh
python scripts/build_document.py manifest.json original rights.json terms canon full-manifest.json
```

Deploy the resulting package before promoting the new immutable manifest through the V3.1 publication pipeline. Keep the same source ID and Canon edition relationship. Regenerate on changes to the original, rights, or extractor. Public reachability and permission to extract individual facts do not establish permission for a complete work. When the publication is a web profile, the searchable edition is the profile itself. PDF citations refer to physical file pages. Tables and graphics should be checked against the facsimile before interpreting column alignment, maps or numerical series.

For a Canon wave, pass the manifest directory, a directory of original and terms files named by SHA-256, an array of rights receipts, the Canon directory and an empty output directory. The batch command emits qualified manifests and one disposition per published document. Repeated editions share the same stored package. It can process a wave before any live publication.

```sh
python scripts/build_document_batch.py manifests assets whole-work-rights.json canon qualified-wave
```
