# V4 user accounts and persistent research — development status

The existing Streamlit V4 test on `v4-development` remains on the main Render
service. The rewritten light frontend is public on a separate V4 test service.
Neither V4 candidate is accepted yet. `v3-interim-release` remains the unchanged V3 rollback branch; V3 was
published at the user's direction before its frozen acceptance suite was
complete. V1 `v1-rc1` and V2 `v2-rc1` remain accepted rollback points.

## Implemented

- Guest queries require no login. The teal chat interface has New chat, a
  conversation sidebar, recency ordering, rename/archive/restore/delete,
  source inspection, a research state, and Quick/Balanced/Deep selection.
  The engineering retrieval trace is hidden from public chat by default;
  `MKH_SHOW_RETRIEVAL_TRACE=1` is an optional server-side debug setting.
- Optional Supabase Auth email-link sign-in creates or reopens an account.
  Private conversations and paired messages are stored in separate tables with
  user-owned row-level policies and a composite owner/thread foreign key.
  The browser sends a caller JWT to private-history REST endpoints; it never
  receives the service-role credential. Guest threads are not silently adopted
  by a subsequently signed-in account.
- Each saved answer retains source references, with document passages resolved
  on demand from the shared corpus across the entire thread, in batches, and
  bounded structured-data snapshots labelled as historical. Missing or retired
  passages retain provenance without being presented as current evidence.
  A follow-up may use prior chat to clarify the question, then
  runs a new evidence search. Previous AI answers are never accepted as cited
  evidence. Citation validity is checked before displaying an answer.
- Long private threads paginate; a failed history load prevents appending to
  an incomplete thread. A timed-out write is checked for a committed pair
  before retry. The analysis mode used by each exchange is saved with it.

## Verification so far

- 34 local tests pass, including account-scoped request construction,
  paginated histories, timeout recovery, reference-only storage, and context
  rewrite guards. The saved-passage test covers 350 references, 100-ID fetch
  batches, and a missing corpus chunk.
- On the GIZ Supabase project, the two private tables have RLS enabled and
  anonymous reads are denied; authenticated SELECT/INSERT/UPDATE/DELETE grants
  are present on both tables. A rolled-back two-identity transaction confirmed
  that a second identity cannot read or insert into the owner's thread; no test
  records remain.
- A public guest Kayes query returned a cited answer with inspectable SNEDD
  passage. A Gao follow-up ran fresh research, cited separate evidence IDs,
  and avoided turning national priorities into Gao implementation claims.
  New chat, a second thread, Quick selection and return to the Balanced Kayes
  thread worked in the public browser.
- On the final navigation build, a public Mopti comparison joined 2025 HAPI
  locality needs with FONGIM project presence, kept region and cercle counts
  separate, warned that project counts are not coverage, and displayed source
  citations. The admin route still requires the separate authorized sign-in,
  and its return link opens the guest Hub.
- On the live V4 build at Render source `46146b8`, the frozen V2 J02
  Bandiagara question distinguished 98 unique projects from 99 location
  records, found no Bandiagara HAPI need estimate, and kept other Mopti
  localities separate (19.4 s). V2 J11 answered in French, classified
  36 Ségou EHA projects as presence only, kept Bla's Admin2 need separate,
  and declined a coverage inference (10.1 s). V2 J18 in Deep mode distinguished
  reported nutrition needs, national priorities, project presence, planned
  national targets and missing evaluated Ségou results (12.6 s). These are
  targeted manual checks, not frozen-suite scores. Frozen V1 S01 rejected
  the claim that the SNEDD is a completed success evaluation, with cited
  strategy passages. Guest threads remained available in recency order and
  a prior thread reopened within the browser session.
- The next live build at Render source `8c1b420` passed V1 G01 in Quick mode:
  it refused to relabel a Mopti-region estimate as Bandiagara's cercle
  estimate, with cited source passages. The same request emitted an immediate
  `MKH_USAGE` record with a valid citation audit, 12.75 s response time,
  5,073 input / 468 output tokens, and approximately US$0.00137 API cost.
  Usage logging now flushes each record so live observability does not depend
  on process shutdown.
- On the live `8b794a3` UI release, frozen V2 J15 distinguished `region=Mopti`
  (257 unique projects, 622 location records) from Mopti cercle (133 projects),
  warned against summing cercle counts, and kept raw commune labels qualified.
  The public answer retained citations and source inspection while the
  engineering trace panel was absent.
- Frozen V2 J17 cited the versioned entity-resolution method: a bare acronym
  remains uncertain, accepted merges retain source values and decision
  metadata, and a wrong merge is superseded rather than erased. Frozen V2 J04
  declined to invent specific Mopti local-plan matches because the indexed
  corpus contains no explicit local Mopti development plan; it separated
  thematic FONGIM examples from a verified plan match.
- Render application logs retained per-query usage records with source plan,
  response time, token counts, estimated API cost, and citation validity for
  the two earlier live document queries. Those observed records were 15.64 s
  / approximately US$0.00206 and 9.0 s / approximately US$0.00176.

## Acceptance still open

1. Test an actual email-link account creation, cross-session reopening and
   continuation, and a second user account in the public browser. The GIZ
   Supabase default sender is limited to two emails per hour for the project.
   Configure custom SMTP before broad public account rollout.
2. Complete a full V1–V3 protected benchmark and V4 account/privacy regression
   on the public candidate. The live questions above are qualitative checks,
   not a complete frozen-suite result.
3. Do not tag V4 accepted until the sign-in, persistence, privacy, regression
   and deployment criteria have been observed end to end. The current public
   build is a V4 test release.


## Light frontend hosted test — 2 October 2026

- Public candidate: https://mali-knowledge-hub-v4-test.onrender.com/ .
  Render service `srv-davpdjugekts73ev4v3g`, branch `v4-light-frontend`,
  Python 3.12.11, Uvicorn, `/api/health`, Free plan. The main service and
  the V3 rollback service were not changed. Draft PR #1 remains unmerged.
- The default desktop view was compared with `image(20261002-085857).png`:
  white canvas, quiet gray 300px sidebar, centered 750px reading column,
  bottom rounded composer, inline citation controls and on-demand drawer.
  Narrow-screen CSS is present; an actual mobile-size browser check is still open.
- A Balanced French Mopti needs/FONGIM question returned 36 evidence items,
  distinguished locality needs from regional totals, and project presence
  from coverage/impact. Opening E02 showed the HNRP 2026 page-16 passage.
  Observed research time: 18.01s; estimated API usage: USD 0.00457864.
  A Quick Bandiagara follow-up refused geographic downscaling and had valid
  citations (11.35s, USD 0.00147918).
- Live follow-up checks exposed a French-language detection problem. The
  response language is now derived from the original user question separately
  from the rewritten retrieval query, in both analytical-engine copies.
  The dedicated API regression covers a rewrite which drops the French opening.
- API history responses use `Cache-Control: no-store`; an expired account
  cannot silently continue a saved thread as an unsaved guest. The composer
  restores a failed question. New-chat/account/mode controls are disabled
  during research and thread mutation handlers guard against a busy query.
- Answer lists now render as semantic lists. Long titles retain space for
  source controls. Progress text describes ongoing research without claiming
  timer-generated pipeline stages. Evidence dates show both ends of a period
  when supplied and saved structured snapshots are labelled as historical.
- 43 local tests pass; JavaScript syntax, Python compilation and diff checks
  pass. These use mocked account/API boundaries, not live account acceptance.
- `/admin` was observed redirecting to the separate V3 `/Administration`
  page, which showed only authorized administrator email-link sign-in.
- `MKH_USAGE` research records start after query rewriting. The new
  `MKH_REQUEST_USAGE` record also captures the context-rewrite API usage,
  combined estimated cost and server request duration. A regression verifies
  rewrite cost is included without logging the user question. Sanitized
  `MKH_API_FAILURE` diagnostics identify the failing stage and error class.
- Reopening a thread retains the last analysis depth selected, for guest and
  account threads. Earlier per-message depth labels remain unchanged.
- GIZ Supabase account configuration remains blocked: the connector reports
  permission denied, and automatic approval review rejected private-dashboard
  sign-in without explicit authorization for that account. The new origin's
  Auth redirect allowlist entry, real sign-in, cross-session history and real
  two-account privacy checks remain open. No V4 acceptance or promotion is claimed.
- The full frozen V1/V2/V3 suite and V3 scanned-PDF/OCR acceptance remain open.
  Targeted guest checks and local unit tests do not replace those release gates.


### Publishing blocker at the latest checkpoint

GitHub began rejecting writes with HTTP 403: "Sorry. Your account was suspended".
The running test service still serves `efee74d2e0dfc28e73a0383db98bf6bde462109b`.
Remote branch head `d4baa8a16f5464d6ae4dade629e5b978090c963a` contains the
last-depth reopening fix but was not deployed. The full-request usage and
sanitized failure diagnostics changes are committed locally and not pushed;
43 tests passed on that local working tree. A French follow-up returned a
recoverable analysis failure on the running build; one retry succeeded in
French with 21 evidence items, refused geographic downscaling, and showed
HAPI reference period 2025-01-01–2025-12-08 and retrieval date 2026-10-02 in
the live drawer. The hosted language retry passed; the first failure's cause
is not yet established because its new diagnostic change could not be pushed.
