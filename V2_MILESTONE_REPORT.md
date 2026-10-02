# Mali Knowledge Hub V2 joined-analysis milestone — 2026-09-28

Status: **analytical release candidate, not yet deployed or accepted**. The
accepted V1 remains unchanged at local tag `v1-rc1`. The current Render service
is live from GitHub `main` commit `1abab1a`, which predates the V1/V2 work.
No Supabase records or schema, Drive files, or Render settings were changed.

## Joined-analysis work

- Region and cercle candidates retain their parent relationship, source label,
  method and confidence. Single FONGIM `commune_raw` labels are provisional
  under their recorded parents; pipe-separated or multi-place labels remain
  unparsed. Unknown or homonymous names are not silently equated. HAPI rows are
  checked against the requested Admin1/Admin2 after the API responds.
- Organization resolution preserves source values and supports distinctive
  exact names, unique normalized spellings, and a unique acronym explicitly
  attached to a full source name. Similar names remain uncertain proposals.
  Reviewed decisions record confidence, reviewer, rationale, date and ID;
  corrections append a superseding decision.
- Curated sector terms keep the FONGIM `SAME` relationship to food security
  broad rather than equivalent. Source semantics and lexical cues distinguish
  needs, priorities, objectives, targets, activities, outputs and results.
- FONGIM project-ID joins link recorded organizations, sectors and locations.
  Cross-source sector links point to original evidence IDs and are labelled
  thematic. They do not establish programme causality, needs coverage or impact.
  The five-document registry has no local plan; the app reports that indexed
  absence without claiming no plan exists elsewhere.
- Public answers show source periods and caveats. Errors no longer show raw
  exception messages. Per-query model calls, token counts, approximate costs,
  external API calls and latency remain in server-side usage logs.

## Evaluation

The frozen V2 benchmark contains 13 development and five held-out questions.
All 18 final runs had no app exception and cited only IDs in their evidence
ledgers. Manual review found and corrected an overbroad locality attribution,
an overly narrow acronym rule, and language treating a reported needs estimate
as a direct measurement. The initial held-out outputs and reruns remain in the
local test log. These checks do not constitute independent adjudication of
every factual clause.

The hand-labelled organization sample scored 20/20 with zero false merges.
It is small and includes constructed alias scenarios from real FONGIM names;
it is not a population-wide accuracy estimate. Eleven focused tests cover
homonymous geography, provisional communes, entity supersession, sector
mapping, HAPI response filtering and thematic joins. A fresh Python 3.12
environment installed `v2/requirements.txt`, passed `pip check`, imported the
runtime packages, and passed those tests.

The unchanged frozen V1 suite ran all 24 cases on the V2 candidate: no app
exceptions and valid evidence IDs in 24/24. Manual review caught a wrong
locality-list count, an unsupported organization total and an overconfident
reading of raw commune strings. The affected answers were rerun after the
general factual rules were strengthened. A further rerun exposed variable
source selection for a national-strategy/commune question; deterministic
government-plus-operational routing was added and verified. The full suite
was not blindly adjudicated claim by claim, so the ID audit should not be
reported as 24/24 factual correctness.

| Final-run set | Cases | Median latency | Maximum latency | Approx. OpenAI cost |
|---|---:|---:|---:|---:|
| V2 development | 13 | 57.23 s | 117.91 s | US$0.03829 |
| V2 held-out | 5 | 72.99 s | 119.18 s | US$0.01534 |
| V1 regression on V2 | 24 | 53.55 s | 130.48 s | US$0.05262 |

The accepted V1 run had median 41.52 s for development and 58.45 s for
held-out cases, with approximately US$0.04147 in OpenAI token charges across
24 cases. The V2 regression medians were 51.62 s and 66.39 s respectively.
Network and cache variance is material; a single run is not a stable latency
distribution. A query-scope FONGIM cache change reduced a repeated Mopti
case from 69.27 s to 23.71 s after a first Mopti query; its FONGIM trace was
0.0 s on the second call. Generic entity-method questions also avoid full
national project fetches. HDX/Supabase network charges are excluded from the
OpenAI estimates.

## Release boundary

The local candidate and benchmark are versioned separately from V1. V2 is
still missing a public Render deployment and live smoke test. The connected
GitHub account is `TheGlobalAnalyst`, with read but no push access to
`BenjaminMoscovici/mali-knowledge-hub`. Render sign-in succeeded and the
service is accessible, but the current repository cannot receive the release
through that GitHub connection. Connect `BenjaminMoscovici` with repository
write access, then publish V1 as the rollback baseline, deploy the V2
candidate to Render, verify the public service, and only then mark V2 accepted
and begin V3.

Known scope limits: no verified administrative commune gazetteer or curated
alternate-name crosswalk, no local priority plan in the indexed corpus, no
independent entity adjudication at scale, and no verified service outputs or
evaluations in FONGIM. The system exposes uncertainty rather than filling
these gaps with inferred facts.
