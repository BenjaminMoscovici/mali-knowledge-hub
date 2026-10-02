# Mali Knowledge Hub V1 analytical milestone — 2026-09-28

Candidate: local git commit `a8c285e`, tag `v1-rc1`. The unchanged v0.3
baseline is preserved under `baseline/v0.3`; no Supabase schema or records were
changed during this milestone. V1 is an analytical release candidate, not yet
deployed.

**Project identity verified on 2026-09-28:** The dashboard session for
`benjamin.moscovici@giz.de` shows the **HDP Nexus Team Mali** organization and
its project `hofoubbmepacdljeablj`, with URL
`https://hofoubbmepacdljeablj.supabase.co`. Its public tables include
`documents`, `chunks`, and the FONGIM mirror; the five document records are
readable. This is the same project reference used for the benchmark below.
The earlier confusion concerned the dashboard's active account, which was
`benjaminmoscovici@gmail.com` before signing into GIZ. No database writes were
made during this identity check.

## Frozen benchmark

- 24 cases were frozen before optimization: 18 development and six held-out.
- All 24 final candidate runs completed without an app exception. Required
  source families were selected in 24/24; every generated evidence ID resolved
  within its answer's ledger in 24/24. These deterministic checks do not prove
  every sentence is fully supported; representative outputs were inspected
  against source passages and structured summaries.
- Seven paired v0.3/V1 cases: median end-to-end latency was 50.9s versus
  41.41s, an 18.6% reduction. Excluding the ambiguous clarification case,
  the six paired medians were 46.85s versus 41.52s. FONGIM and some joins
  remained variable and occasionally slower due to network/data queries.
- Median V1 latency: 41.52s across the 18 development cases and 58.45s
  across six held-out cases. The longest held-out query was 96.55s.
- Estimated OpenAI token charges totaled US$0.04147 for one final run of each
  frozen case, median US$0.00145 per development query. This excludes Supabase
  and HDX network charges. Prompt caching and network variance make a single
  run insufficient for a stable cost or latency distribution.

## Changes and observed quality

- The runtime is local and versioned; V1 no longer downloads executable Python
  from Supabase at startup. Python 3.12 dependencies are pinned.
- Explicit source names route without a model planner when unambiguous.
  Ambiguous geographic references request clarification before retrieval.
- Questions naming multiple government documents retrieve from each named
  source. M01 now includes Vision 2063, SNEDD and the project portfolio;
  M02 includes SNEDD and the actual phasing document. This can add latency.
- Gao–Mopti comparison now queries each region's HAPI records. The initial
  held-out run queried Mopti only; that failure is preserved in results.
  The corrected answer keeps Admin2 observations, population category and
  reference period distinct and avoids fabricated regional totals.
- A citation gate validates ledger IDs, including IDs written as ranges.
  Evidence inspection shows document title, page, version and available dates.
- HAPI request counts, model calls, tokens, approximate charges and timings
  are emitted as structured server log metadata, without prompts or secrets.
- A validated PDF ingestion CLI provides a dry-run, rejects unreadable PDFs,
  embeds before document creation, and removes an incomplete document record
  if chunk upload fails. It has not ingested a production document in this
  milestone; a synthetic two-page PDF and a corrupt file were tested locally.
- Quick, Balanced and Deep were tested on D01 and X01. Balanced remains the
  default: it retained more document evidence than Quick and completed the
  cross-source case faster than both alternatives in those runs. Cached-input
  effects prevent a clean monetary ranking from these few samples.

## Review limits and release route

The representative outputs correctly distinguished strategy from results,
project presence from coverage or impact, region from cercle/commune, and
missing evidence from a negative finding. The held-out I02 answer initially
used French for an English question; a subsequent run answered in English.
No independent human adjudication of every claim or repeated statistical
quality estimate has been performed.

The connected public GitHub repository exists, but the current integration
reports pull access without push access. Its existing deployment source was
left unchanged. The Colab execution URL redirects to a Google sign-in page in
the cloud browser; only the user can complete that authentication. A durable
hosting route with server-side secrets is still required to make V1 live.
The current baseline has not been replaced.
