# Mali Knowledge Hub V4 conversation frontend

The V4 frontend rewrite lives in `web/` and is served by `web_api.py` through
Uvicorn. `analysis_core.py` contains the accepted V1–V3 research path extracted
from the existing Streamlit application. The latter remains in `app.py` for
rollback and the separate V3 administration service. The browser receives
answer text and bounded evidence; Supabase and OpenAI credentials remain on
the server. The new public service uses the existing RLS-protected V4 history
tables through the verified user's JWT.

Start the conversation service locally with
`uvicorn web_api:app --host 127.0.0.1 --port 8765`. The Dockerfile starts this
service on Render's `$PORT`. If Render is configured for a native Python build,
set the start command to
`uvicorn web_api:app --host 0.0.0.0 --port $PORT --proxy-headers`.

Set `MKH_PUBLIC_ORIGIN` to the exact browser origin for sign-in redirects and
same-origin mutation checks. Register that origin followed by `/` in Supabase
Auth redirect URLs. Set `MKH_ADMIN_URL` to the separate V3 administration
service URL to make `/admin` redirect there. The administration service must
keep its own email allowlist and server-side credentials. Neither URL variable
is a secret. Account email links use Supabase's implicit flow; the browser
clears token fragments immediately and exchanges them for secure HttpOnly
cookies. Guest histories stay in the current browser tab's session storage;
importing one into an account requires an explicit action from the profile menu.

`python -m unittest discover -s . -p 'test_*.py'` runs the local suite. A real
email-link sign-in, cross-session history, cross-user privacy, and live source
inspection still require verification on a deployed origin before V4 acceptance.

## Legacy V3 and V4 notes

V3 starts at the immutable `v2-rc1` tag. V1 `v1-rc1` and V2 `v2-rc1` remain
rollback points. The V3 interim release is preserved on
`v3-interim-release`; the current public Streamlit service uses `v4-development`
until the frontend rewrite is deployed. `app.py` is the rollback analytical app;
its `Administration` page enforces server-side authentication before reading
the corpus or exposing an action. Run administration as a separate service
when the conversation frontend is deployed.

## Setup

Use Python 3.12. For local work, install `requirements.txt`. The isolated V3
admin service includes Tesseract with English and French packs. The public
Render service builds `v4-development` from the repository root with
`pip install -r requirements.txt`; change its start command from Streamlit to
Uvicorn when deploying the conversation frontend. Vision OCR supports scanned
PDFs in the administration deployment.

Server-side environment variables:

* `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `OPENAI_API_KEY`,
  `HDX_HAPI_APP_IDENTIFIER`: same server-side sources as V2.
* `SUPABASE_PUBLISHABLE_KEY`: used only by server-side Supabase Auth requests.
* `MKH_ADMIN_EMAILS`: comma-separated, exact email allowlist. Set to the
  publisher's verified address for initial DEV testing.

Never commit values for these variables. Do not render service credentials or
copy them to the browser. Admin and V4 account sign-in use Supabase Auth email
magic links. Allow `https://mali-knowledge-hub.onrender.com/` as an Auth
redirect URL; retain the isolated V3 admin URL as the default Site URL until
that rollback route no longer needs it. The GIZ project's default email sender
currently permits only two sign-in emails per hour. Configure a custom SMTP
sender before wider account rollout.

Apply `migrations/001_admin_ingestion.sql` only after checking the GIZ project's
`documents` and `chunks` column types. It adds a private Storage bucket, a
server-only job table and a service-role-only transactional publish RPC. It
does not change the existing match function, indexes, documents or chunks.
If the SQL Editor stalls after submission, run the read-only
`migrations/verify_admin_ingestion.sql` before retrying the migration. A
complete migration has a job table with RLS enabled, a publish RPC, a private
originals bucket, and no anonymous or authenticated read/execute privileges.
Record the document/chunk counts before the first live ingestion.
Apply `migrations/002_ingestion_claims.sql` before running this version of the
ingestion worker. It adds a unique live-original index and a service-role-only
atomic job claim, preventing duplicate concurrent uploads or processing.
If earlier V3 tests created multiple live jobs for the same SHA-256, review
those jobs before creating the index. Verify that anonymous and authenticated
roles cannot execute `claim_ingestion_job`.
The app needs a server-side secret key that can write Storage and execute the
RPC. Original files are retained privately, including broken submissions.

Apply `migrations/003_private_research.sql` for V4 private histories. This has
already been applied to the GIZ project. It creates account-scoped conversation
and message tables with RLS and no anonymous table privileges, separate from
the shared corpus. The app writes histories through the authenticated user's
JWT and the publishable key, never the service-role key. Document passages are
resolved from corpus chunk references; structured API evidence snapshots are
bounded and labelled as historical. Fresh analysis always retrieves evidence
again. Do not call V4 accepted until a real email sign-in, cross-session
continuation, and user-facing privacy test are complete.

Run: `streamlit run app.py`. Drag a PDF onto the Administration page and click
**Upload and process**. The job is uploaded, queued, processing and finally
ready or failed. Parsing failures are `failed`; embedding/publish failures are
`partially processed`. First-time failures have no public chunks. A retry
downloads the checksummed original and repeats processing. A ready document can
be reprocessed atomically; its previously validated chunks remain available if
the new attempt fails, and the attempt status and existing active record are
both visible to the administrator.
An administrator can correct title, organisation, publication date, document
type, language, geography and version from a ready job. Saving a correction
reprocesses the original, consumes embeddings again, and replaces the published
chunks atomically. Confirmed values are retained on later retries and
reprocessing. Malformed corrections are rejected before job status changes.
Job quality records embedding token count and processing duration for
operational review. The admin table shows both the attempt status and the
current published document state when a reprocessing attempt fails.
An exact-file SHA-256 check and database unique index prevent duplicate
uploaded, queued, processing or ready jobs, including concurrent uploads,
before storing another original or requesting embeddings. Failed attempts can
still be retried from the existing job or submitted again.

Limits: PDFs up to 20 MB and 80 pages. OCR runs page by page. Metadata is a
proposal with per-field confidence in the job details; the app does not claim
high-confidence publisher/geography/date where extraction cannot establish it.
Existing five corpus documents remain listed as pre-V3 records. For acceptance,
use public-source test documents and the frozen `benchmark_v3_frozen.json` plus
the unchanged V1 and V2 suites. Do not use sensitive documents in public DEV.

## V4 acceptance still pending

Guest chat, the teal conversation sidebar, Quick/Balanced/Deep modes, and an
optional email sign-in entry are live. Private-history storage, rename,
archive, delete, and reopening are implemented. The database privacy policies
were checked with two identities in a rolled-back transaction; no test data
remains. The email-link journey and cross-session continuation still need a
real user test. V3 was published as an interim release at the user's direction,
not declared accepted against its full frozen benchmark.
