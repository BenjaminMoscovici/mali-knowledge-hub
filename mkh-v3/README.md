# MKH V3 development preview

Run the app from this directory with `python -m uvicorn app:app --host 127.0.0.1 --port 8127`.
Run regression checks with `python -m unittest discover -s tests -v`.

The `v3-development` branch owns the preview. Render builds `mkh-v3/requirements.txt`
and serves this directory on the isolated **mali-knowledge-hub-v3-dev** Free web service.
The **mkh-v3-dev** Supabase project holds preview sessions and owner-scoped conversations.
Deploys are triggered manually after verification. The Render service supplies project
configuration, including `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `OPENAI_API_KEY`.
An independent `MKH_HISTORY_SIGNING_KEY` can keep transcript signatures valid across model
credential rotation. Preview users receive one-time codes through Supabase Auth.
The V3 project's **Magic Link** and **Confirm signup** email templates both use the
body in `supabase/templates/email-code.html` and the subject **Your MKH V3 sign-in code**.
Apply those settings in the V3 Supabase dashboard to deliver codes for both returning
and first-time sign-ins. Hosted templates are settings on the V3 project.

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
limits. SQL evidence includes the exact operation and the input releases. The initial
catalogue and document search use bilingual metadata and normalized lexical matching.
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
email-code sign-in and paired browser evaluation remain open.
