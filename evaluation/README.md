# MKH evaluation framework

Capability radar generation is now automatic whenever a benchmark scorecard
is generated. See [RADAR_FORMULAS.md](RADAR_FORMULAS.md) for the fixed eight-axis
formulas, missing-data policy and release artifacts. Use `--live-run`,
`--conversation` and `--label` on `evaluation.scorecard` for candidate milestones.
Historical measurements are overlaid only when benchmark and evaluator
configurations match. The radar never changes protected gates or release acceptance.

This package is separate from the production answer pipeline. It evaluates the existing V4
guest API backed by the GIZ project `hofoubbmepacdljeablj`. It does not change Hub prompts,
retrieval, source ingestion, accounts, or deployments. No TGA/n8n component is used.

The 75-case frozen suite was committed at `b298353` before baseline execution. It contains
all 31 V1/V2 development questions and original checks unchanged; the 18 held-out cases
retain all 11 older held-out questions. Existing V1–V3 fixtures/tests remain active.
Frozen cases: geography/population 15, needs 10, actors/projects 10, plans/priorities 10,
funding/timelines 10, learning/evaluations 5, joined analysis 10, adversarial 5.
22/75 are French; the held-out file contains four French cases. Seven rolling cases
cover known failure classes. Expected behaviors are evaluator-only, never Hub inputs.

## Commands

From the repository root, Python 3.12; evaluation uses the standard library:

```
python -m unittest discover -s evaluation/tests
python -m evaluation.runner --split frozen --output evaluation/results/baseline --hub-commit VERIFIED_SHA
python -m evaluation.runner --split rolling --output evaluation/results/challenges --hub-commit VERIFIED_SHA
python -m evaluation.runner --split heldout --acceptance --output evaluation/results/acceptance --hub-commit VERIFIED_SHA
python -m evaluation.corpus --config PRIVATE_RUNTIME_JSON --output PRIVATE_SOURCE_ORACLE_JSON
python -m evaluation.judge --run evaluation/results/baseline --config PRIVATE_RUNTIME_JSON --public-provenance VERIFIED_PUBLIC_PDF_MANIFEST_JSON
python -m evaluation.scorecard --run evaluation/results/baseline --oracle PRIVATE_SOURCE_ORACLE_JSON
python -m evaluation.seeded --config PRIVATE_RUNTIME_JSON --output evaluation/results/seeded
python -m evaluation.web_verification --run evaluation/results/baseline --findings REVIEWED_WEB_FINDINGS_JSON
python -m evaluation.telemetry --run evaluation/results/baseline --export MKH_USAGE_EXPORT_JSON
python -m evaluation.calibration --run evaluation/results/baseline
python -m evaluation.calibration --run evaluation/results/baseline --ratings REAL_PUBLISHER_RATINGS_CSV
python -m evaluation.scorecard --live LIVE_SCORECARD_JSON --candidate CANDIDATE_SCORECARD_JSON --output COMPARISON_JSON
python -m evaluation.report --results evaluation/results --output evaluation/reports/20261005
```

For major comparisons use `--repetitions 3 --repeat-ids JOIN01,JOIN02,JOIN03,FUND04`.
Requests are sequential, contain only question/depth/prior messages, and do not automatically
retry. Resume skips already stored attempts, including failures. A failed attempt is never
silently replaced by a later success. Record a separate diagnostic run for an authorized retry.
Each attempt is atomically stored as JSON and in SQLite, with question/response hashes,
Hub commit, benchmark hashes, dates and request configuration. Failed request cost remains
unknown where no receipt is available. Client and server latency are separate.

## Judging and metrics

Independent judge: pinned `gpt-5-mini-2025-08-07`, rubric/schema/prompt version 1.0,
medium reasoning, structured output, store=false. Exact provider usage, model, time and
estimated cost are saved separately from Hub costs. Nine 1–5 dimensions include decision
usefulness. Atomic claims distinguish supported, contradicted, unsupported and unassessable;
the claim-rate denominator and coverage are reported. Model scores require Publisher calibration.
Failures and absent judgments are not scored as successful factual answers.
External packets pass a public-provenance gate. GIZ oracle chunks are reserved for local
validation and never exported to the judge. Independently downloaded official government
PDF pages can supply source evidence; document passages with unknown public provenance
are withheld. A separate, versioned conservative scoring guard makes claims relying on
withheld evidence unassessable. Raw judge outputs are retained unchanged. Such missing
evaluator material must not be reported as a Hub hallucination. Raw dimension scores can
still be affected by coverage limitations and remain provisional pending human review.
Coverage version 1.1 also treats mixed claims needing withheld evidence and retrieval-date
claims whose metadata was omitted from initial public packets as unassessable. Later packets
include public retrieval/validity metadata. Initial packets and raw judgments are not rewritten.
The date-stamped baseline report generator is an archived baseline renderer; general future
release aggregation uses `scorecard`. Its quality table reports both unique-case and
attempt-weighted dimension means. Claim rates include repeated attempts explicitly.

Deterministic checks reuse the existing citation validator, validate cited original GIZ
chunk/document/pages, original packaged record/release anchors, aggregate spreadsheet rows,
time metadata, explicit numerical facts, source-family presence and routes/call budgets.
Presence/phrase checks alone are not semantic entailment. Unresolvable dynamic HAPI/FONGIM
records are unknown. Source-family presence does not prove that every family was queried.
Baseline API telemetry gaps are explicitly reported; source-plan logs may enrich them.

Scorecards include median/P90/P95/max latency and median/total cost by mode, input tokens,
French language/writing results, evidence distribution, failures and judge findings. Quantiles
use linear interpolation. Protected metrics reject any measured regression for this sprint; missing
protected evidence cannot pass. Release acceptance additionally requires held-out qualification,
live smoke, privacy audit, human calibration and measured target improvement. A baseline
scorecard alone is not release acceptance. Configuration comparisons can use the same runner
against another isolated candidate URL, preserving the same benchmark and repetitions.

Nine seeded error packets and nine clean controls test evaluator verification independently;
they do not establish the catch rate of the production Hub's citation-only verifier.

Web checks are separate after immutable answer capture. Store publisher, URL, retrieved date,
reference period, public evidence, comparison and discrepancy category. Never feed web results
into the benchmark Hub request. Target 10–20% of cases; select held-out checks only at milestones.
Use primary public sources, preserve publication vs collection dates, and label failed verification
as not independently verifiable. `consistent` is an additional positive category.

## Governance and result storage

Frozen/held-out hashes are checked before every run. To change them, retain the old version,
create a new version and document why; do not remove failures or weaken expectations.
New rolling challenges need new IDs and failure provenance. Held-out requires `--acceptance`
and must not be used for active tuning. Raw public-source evidence/receipts are kept in the
durable evidence bundle; compact scorecards, code, benchmark cases and reports are versioned.
Do not commit runtime credentials, user histories or private packets. The read-only corpus
tool reads only shared documents/chunks, and omits embedding vectors. No Supabase migration
is necessary for evaluation persistence: SQLite plus JSON and versioned scorecards suffice.
Cross-user privacy requires a separate authenticated test; anonymous denials alone do not prove it.
The baseline rolling v1 transport fixture had a construction error (wrong question).
`rolling_v2.json` documents its correction and retires that ID; the frozen v1 manifest
and original rolling v1 are retained unchanged. Rolling run manifests pin their suite hash.
The offline GitHub workflow checks benchmark integrity and evaluator tests without secrets.

## Optional Render milestone worker

`MKH_EVALUATION_RUN=<unique-milestone-label>` enables the fixed release worker
on the GIZ V4 test service only (`srv-davpdjugekts73ev4v3g`, project
`hofoubbmepacdljeablj`). The default is off. A 40-character deployed commit is
required; labels cannot select commands, arbitrary endpoints or repositories.
The worker reuses the frozen 83-attempt configuration, rolling challenge set and
18-case held-out acceptance milestone. It captures Hub latency before invoking
any independent judge. It does not access user history or add an HTTP trigger.

The source oracle, raw answers and judge receipts are checkpointed in the private
`mkh-evaluations` GIZ bucket (ZIP only, 32 MiB maximum, no new access policy).
Public government PDFs are admitted to judge packets only if their downloaded
bytes match the baseline's recorded SHA256. Changed or unavailable files remain
unassessable. No source integration is added. Existing public Hub startup and
source publication remain unchanged when the flag is absent.

Each split emits computed aggregate chunks to the existing private Render logs
with `MKH_BENCHMARK_AGGREGATE`, a chunk index, count and SHA256. Those exports omit
questions, answers, source passages and claim labels. Save the exported scorecard
and its bound `radar_inputs.json` together to regenerate the six release artifacts
without exporting raw evidence. The original scorecard hash is retained; metric
inputs are calculated inside the worker from validators and immutable judgments.
Cached inputs must match the scorecard hash and formula version. Attach the
separately captured 24-sequence UI conversation scorecard for protocol-matched
conversation comparison. Missing historical scores and unresolved privacy/human
calibration gates remain unavailable; neither exports nor radar authorize release.

Restarting the same completed commit/milestone skips measurement. Intermediate
private checkpoints resume captured attempts and receipts. Clear the opt-in flag
after a milestone to keep ordinary starts free of benchmark work. If source
provenance, storage or judging fails, the worker logs only the error type and
retains measurements already checkpointed; it never marks an incomplete suite
qualified or hides failures by retrying them.
