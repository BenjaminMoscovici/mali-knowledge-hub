# Mali Knowledge Hub V2 development candidate

The accepted V1 baseline is the immutable local tag `v1-rc1`. V2 lives on the
separate `v2-development` branch under `v2/`. Run from the project root with
Python 3.12 and `v2/requirements.txt` installed:

```sh
streamlit run v2/app.py
```

For a separate Render V2 service, select repository root directory `v2`.
Its `.python-version` selects Python 3.12; use build command
`pip install -r requirements.txt` and start command
`streamlit run app.py --server.address 0.0.0.0 --server.port $PORT`.
Keep the existing service on its accepted branch until V2 passes the release
gate. Copy the four server-side variables through Render's environment controls.

Server-side environment variables: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
`OPENAI_API_KEY`, `HDX_HAPI_APP_IDENTIFIER`. Never place them in a public
repository, browser bundle, downloadable artifact or application log. The
verified GIZ project reference is `hofoubbmepacdljeablj`.

V2 retains V1 retrieval, citations and cost logging. It adds a conservative
region/cercle hierarchy built from the FONGIM mirror, response-side HAPI
geographic validation, curated sector terms, evidence-type cues, versioned
organization decisions, exact FONGIM project-ID relationships, and a thematic
join audit. The audit only connects original ledger IDs; it is not evidence.
Broad sector matches such as FONGIM `SAME` remain qualified. Similar
organization names are proposals, not automatic merges. Single `commune_raw`
labels form provisional nodes under their recorded cercle and region. They
cannot be used as verified administrative communes or coverage claims; a raw
label containing multiple places remains unparsed.

There is currently no local development plan in the five-document corpus.
For local-plan questions the app cites a live registry inventory, while
allowing for plans outside the Hub. No Supabase schema change is required for
this candidate. Reviewed entity decisions are append-only in
`entity_decisions.json`; `entity_audit.py` can supersede an earlier decision
without deleting its source value or history.

The frozen `benchmark_v2_frozen.json` contains 13 development and five
held-out cases. Run `probes/v2_batch.py` for development cases and the
unchanged `benchmark_v1_frozen.json` for regression. Do not use held-out cases
until milestone review. V2 is not accepted or deployed yet.
