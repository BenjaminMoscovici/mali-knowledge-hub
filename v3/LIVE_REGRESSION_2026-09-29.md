# V3 public test route — qualitative regression log, 2026-09-29

The separate V3 Render service was tested through its public chat UI. These
are observed case-level checks, not a complete numerical benchmark or a V3
acceptance decision. The accepted V2 live service was unchanged.

| Frozen case | Observation | Answer time | Cost observation |
| --- | --- | ---: | --- |
| V1 D01 (French SNEDD) | Passed French answer and page-citation audit (four IDs). | 10.5 s | 2 API calls; 5,001 input and 396 output tokens; estimated US$0.00127. |
| V2 J02 (Bandiagara) | Passed cercle/region separation, 98 distinct FONGIM projects, no regional needs downscaling. | 17.0 s | Not recorded. |
| V2 J03 (Ségou coverage) | First attempt failed generically; immediate retry and a later run on the diagnostic build passed, with no adequacy inference. Investigate recurrence. | 12.8 s on diagnostic build | Not recorded. |
| V2 J04 (Mopti local plan) | Passed: no indexed Mopti local development plan, no fabricated project match. | 8.0 s | Not recorded. |
| V2 J05 (Gao nutrition) | Passed: project-sector records did not become delivered results or unsupported organisation attribution. | 12.7 s | 1 API call; 6,659 input and 385 output tokens; estimated US$0.00160. |
| V2 J06 (HNRP/SNEDD) | Passed need, priority, activity, and result distinctions; no plan-as-achievement claim. | 10.5 s | 3 API calls; 10,046 input and 611 output tokens; estimated US$0.00252. |
| V2 J07 (many-to-many counts) | Passed: explicitly rejected adding project-sector and project-location association counts; recommended distinct project IDs. | Not recorded | Not recorded. |
| V2 J08 (Mopti ambiguity) | Passed: distinguished region and cercle, marked commune label unverified, disclosed region default and scope uncertainty. | Not recorded | Not recorded. |
| V2 J09 (organisation names) | Passed: no similarity-only merge; explained confidence, reviewer, decision ID and source preservation. | Not recorded | Not recorded. |
| V2 J10 (Mopti joined themes) | Passed: cited needs, national plans and FONGIM sectors, separated facts and synthesis, and did not infer programme relationship or coverage. | Not recorded | Not recorded. |
| V2 J11 (French Ségou WASH) | First run failed language rubric despite sound evidence/coverage caution. The fixed V3 build returned a predominantly French answer, kept Bla's 2025 observation separate from the Ségou region and 2026 FONGIM records, and refused a coverage inference. | Not recorded | Not recorded. |
| V2 J12 (Mopti commune data) | Passed: 257 distinct Mopti-region projects versus 622 project-location records; raw, sometimes pipe-separated commune strings were not treated as verified commune entities. | Not recorded | Not recorded. |
| V2 J13 (national versus Bankass) | Passed: national priorities did not become evidence that any named Bankass project implemented them; 96 recorded projects were presence only. | Not recorded | Not recorded. |
| V1 D02 (Vision Mali 2063) | Passed: cited English account of stated 2024–2063 ambition; no achieved-outcome claim. | Not recorded | Not recorded. |
| V1 D03 (priority-project phasing) | Passed: cited French answer describing the eleven-project portfolio and decade phases; explicitly treated it as planning, not implementation. | Not recorded | Not recorded. |
| V1 D04 (2026 humanitarian needs) | Passed: cited national 5.1 million people in need versus 3.8 million targeted, broad community priorities, and refused to invent a detailed local distribution. | Not recorded | Not recorded. |
| V1 H01 (Mopti HAPI) | Passed: eight intersectoral Admin2 observations and sector-specific examples with 2025 reference dates; refused regional sum and reach inference. | Not recorded | Not recorded. |
| V1 I01 (Bandiagara poverty impact) | Passed: 98 recorded projects remained project presence; no measurable poverty impact, baseline, outcome or attribution was invented. | Not recorded | Not recorded. |
| V2 J14 (Gao joins) | Passed: HAPI locality needs, Mali-wide priorities, HNRP planning, FONGIM sectors and actors; clearly marked geography/theme as synthesis, not a programme relationship. | Not recorded | Not recorded. |
| V2 J15 (Mopti ambiguity) | Passed: region and cercle both named Mopti, regional 257 distinct projects versus cercle 133, overlapping locations and no sum of cercle counts. | Not recorded | Not recorded. |
| V2 J16 (Bandiagara local plan) | Passed: no indexed local plan, 98 recorded cercle projects are presence, no proof all align; did not claim no plan exists anywhere. | Not recorded | Not recorded. |
| V2 J17 (organisation acronym) | Passed: unique explicit acronym/full-name evidence or exact distinctive match, provenance/confidence, review and superseding reversal; similarity alone rejected. | Not recorded | Not recorded. |
| V2 J18 (Ségou nutrition layers) | Passed: Admin2 nutrition need, national priority, 30 nutrition-related recorded projects, targets versus delivered outputs, absent evaluated results and causal link. | Not recorded | Not recorded. |

One additional open-ended Mopti joined question returned inspectable HNRP,
HAPI and FONGIM sources in 21.9 seconds. The diagnostic build logs a safe
exception class and traceback frame names for failed queries; it has not yet
captured a repeat of the transient J03 failure. No complete V1/V2 suite pass
or protected-metric comparison is claimed here.

| V3 ingestion case | Observation | Processing/answer time |
| --- | --- | ---: |
| Machine-readable UNICEF appeal | `ready`: 6 PDF pages, 17 chunks and 17 embeddings. A public question about severe wasting returned **202,575**, with E05 linking to the uploaded appeal's PDF page 3 and the exact source passage. The initial retrieval miss was corrected by source-family and title routing. | 3.37 s ingest; 7.2 s answer |
| Scanned UNICEF situation report | Stored original and failed safely on hosted OCR's 120 s page timeout. A 300 s per-page hosted retry also timed out after 663.55 s. Local revised OCR extracted all 11 pages and 31 chunks in 28.7 s. The stored job remains unpublished; vision OCR retry is pending deployment. | 238.8 s and 663.55 s failed hosted attempts; 28.7 s local extraction |
| Malformed DEV PDF | `failed` with “PDF is malformed or cannot be opened”; no document ID or searchable publication observed. | 0.34 s |

A read-only query against the live GIZ Supabase project verified per-job
publication: `e2c7bcda` is ready with 17 chunks, while `f4ad53a9` (scanned)
and `b8289abf` (malformed) are failed, have no document ID and have zero
published chunks. Total corpus chunks are 1,256, equal to the 1,239 baseline
plus the appeal's 17.

Admin magic-link sign-in succeeded in the shared browser. A subsequent Render
redeploy reset that Streamlit session. The browser-tab token restoration build
is live at `589f8bd` on the isolated V3 service. The administrator completed a
new secure sign-in and can retry the stored scanned original. The vision OCR
and independent worker path currently pass 26 local tests and await isolated
deployment and live verification.
