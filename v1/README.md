# Mali Knowledge Hub V1 candidate

Python 3.12. Install `requirements.txt`, then set `SUPABASE_URL`,
`SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`, and `HDX_HAPI_APP_IDENTIFIER`
as server-side environment variables. Run `streamlit run v1/app.py` from
the project root. Never put credentials in this repository or a browser bundle.
The GIZ dashboard account `benjamin.moscovici@giz.de` lists the HDP Nexus
Team Mali project `hofoubbmepacdljeablj`, matching the earlier project URL.
Before any write or deployment, validate the runtime key against that project's
intended scope and keep it in server-side secrets.

The operational runtime is versioned locally; this app does not download
executable Python from Supabase on startup. It still reads the existing
Supabase document corpus, vector-search RPC, FONGIM mirror and HDX HAPI.
The optional FONGIM source synchronization requires the separate server-side
`FONGIM_POWERBI_RESOURCE_KEY`; ordinary questions use the existing mirror.

The `ingest.py` CLI validates PDF text and previews page/chunk counts without
database changes by default. Supply metadata JSON with a title and explicit
`status: active`; use `--commit` only after reviewing the preview. Unreadable
scanned PDFs are rejected pending OCR. Failed chunk uploads trigger deletion
of the newly created document record; the database must cascade delete its
chunks for complete cleanup.

`api_usage` records model, tokens, calls, latency, and approximate USD cost
per answer, using standard token prices checked on 2026-09-28. It excludes
Supabase, HAPI and FONGIM network costs; HDX HAPI request count and timing
are recorded separately. It does not record prompts or keys. Structured
`MKH_USAGE` lines contain per-query metadata suitable for server log capture.
