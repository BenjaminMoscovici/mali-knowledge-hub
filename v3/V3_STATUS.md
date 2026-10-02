# V3 development checkpoint — 2026-09-29

## Stable baseline

- Accepted V1 tag: `v1-rc1`; accepted V2 tag: `v2-rc1`.
- V2 Render service `srv-dat68s60tbcc73a298p0` serves
  `https://mali-knowledge-hub.onrender.com/` from `v2-release` commit
  `ab9406814642ebe70a8fe1953cdcff4575b2e7fe`.
- A fresh joined Mopti question returned a cited HAPI/FONGIM/document answer
  on 2026-09-29. The existing V2 service was not changed during V3 setup.

## V3 test route

- Separate Render Docker service `srv-datnmp97lnhs73e30970` at
  `https://mali-knowledge-hub-v3-test.onrender.com/`, source `v3-test`.
- Build with French and English Tesseract succeeded. Six required server-side
  variables are configured in Render with masked values; the configured build
  is live. No secret values were committed.
- GIZ Supabase project `hofoubbmepacdljeablj`: additive migration 001 and
  follow-up `002_ingestion_claims.sql` applied. The unique live-original
  index and claim RPC exist; anon/authenticated cannot execute the RPC and
  service_role can. Counts after migration: 0 ingestion jobs, 5 documents,
  1,239 chunks.
- Local V3 suite: 26 passing tests, including machine-readable PDF, scanned
  PDF OCR, malformed input exclusion, retry, metadata correction, duplicate
  guard, V2 joined-analysis logic and the French WASH language regression.
- A focused teal chat interface was committed locally as `1dd64e1` and deployed
  from GitHub `ce758855c9f74d20bee62d0eb3cc43d384346580` on 2026-09-29.
  It has sidebar navigation, New chat, example prompts and a persistent chat
  composer. A live source-inventory exchange and a Mopti joined question
  worked in that interface; the latter took 21.9 seconds with inspectable
  HNRP, HAPI and FONGIM evidence.
- V2 frozen case J02 was run on the V3 test service. The answer separated
  Bandiagara cercle's 98 unique FONGIM projects from needs recorded for other
  Mopti localities, refused to downscale regional evidence, cited source IDs,
  and took 17.0 seconds. This is one qualitative regression check, not the
  complete frozen suite.
- The subsequent public checks D01 and J03–J06 passed their qualitative
  rubrics (French SNEDD with citations; Ségou coverage uncertainty; absent
  Mopti local plan; Gao project versus result; HNRP versus SNEDD evidence
  types). J03 first returned a generic failure and succeeded on immediate
  retry. A safe exception-class/frame diagnostic change was deployed to the
  isolated V3 service, and J03 passed on that build. The first failure's cause
  remains unknown until it recurs with diagnostics. Results and limitations
  are recorded in `LIVE_REGRESSION_2026-09-29.md`.
- A J11 live check exposed English output for a French question beginning
  “Les besoins”. The V3-only language selector was fixed, deployed to the
  isolated service and retested with a predominantly French, cited response
  that kept geographic and temporal scope distinct. J07 and J08 also passed
  their many-to-many count and Mopti ambiguity checks. J09, J10, J12 and J13
  passed qualitative entity resolution, joined thematic analysis, raw commune
  provenance and national-to-cercle inference checks. The V2 release stayed
  unchanged.
- The administrator signed into the shared V3 tab with the GIZ account. Three
  public-source DEV uploads created managed jobs: a six-page UNICEF appeal
  reached `ready` (17 chunks, 17 embeddings); the eleven-page image-only
  UNICEF report retained its original but failed on hosted Tesseract's 120 s
  page timeout; the deliberately malformed PDF failed cleanly without a
  published document. A metadata correction for the ready appeal was saved.
- Hosted OCR was reduced to 1.5x cover/1.25x body rendering and a bounded
  300 s page timeout. The entire scanned report extracted locally in
  28.7 s with 31 chunks. Its hosted retry still failed after 663.55 s on
  Render Free's constrained CPU; the job remained unpublished. The next V3
  build switches hosted scanned-page extraction to OpenAI vision with token
  accounting and page-level validation, and runs the attempt in a worker
  independent of the administrator's browser session. This build is local
  until separately deployed and verified.
- The first public appeal query missed the newly published UNICEF document.
  V3 family classification, explicit title targeting and humanitarian routing
  were corrected and deployed on the separate V3 service at GitHub commit
  `108d428fc41ce93c66e073f4160dd5a1579fbf4a`. A fresh public query
  answered 202,575 children with severe wasting planned for treatment, citing
  E05, PDF page 3; the displayed evidence contains that exact UNICEF target.
  Response time was 7.2 s, source research 2.4 s. V2 live was untouched.
- The redeploy reset Streamlit's admin server session. A short-lived access
  token restoration from tab-scoped browser session storage was deployed to
  the V3 test route at `589f8bd`. The administrator completed a fresh secure
  sign-in and is currently signed into the V3 administration page.
- Additional live qualitative frozen cases D02–D04, H01, I01 and J14–J18 passed
  their source, geography, entity-resolution and evidence-layer rubrics.
  J02–J18 and six V1 cases have been observed so far; J01 and the remaining
  V1 cases still need systematic V3 regression. Cost/latency coverage is
  incomplete.
- A live read-only GIZ Supabase query confirmed that the ready appeal has 17
  published chunks and both failed jobs have no document ID and zero chunks.
  Total chunks are 1,256, exactly the 1,239 pre-V3 baseline plus 17.

## Remaining acceptance work

1. Deploy vision OCR and the background ingestion worker to isolated V3.
   Retry the stored scanned report, validate all page-level chunks and a
   searchable page citation. Verify admin restoration across a redeploy and
   unlisted address denial as feasible.
2. Complete the frozen V3 acceptance cases and V1/V2 regression suites against
   the configured V3 test service, record cost/latency, investigate any
   recurring query error, then decide V3 acceptance.
3. Preserve V2 rollback when promoting an accepted V3 release.

## Next mandate, held until V3 acceptance

V4 ToR: optional user accounts and private persistent conversation threads,
guest access by default, contextual continuation without treating prior
answers as evidence, Quick/Balanced/Deep selection, and a chat-style sidebar.
Preserve accepted V3 as rollback before deploying V4 live. The user resumed
development after the earlier stop-and-save request on 2026-09-29.
