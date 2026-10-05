# MKH capability radar · formula version 1.0

The radar is a visual summary, never an acceptance decision. Its formulas and
fixed reference targets are versioned and hashed in every capability table.
They must not be adjusted to improve a candidate's apparent result. A new
formula version requires recomputing all comparable versions from their
original measured inputs. No manual capability grades are accepted.

All rates are fractions. A judge mean on the existing 1–5 rubric becomes
`(mean − 1)/4`. Multiply the final weighted fraction by 100. Missing required
components make the whole axis **Unavailable**; weights are not redistributed.
The JSON artifact contains every exact input, denominator, scorecard hash and
comparison signature. Analytical judge scores remain provisional until human
calibration. Coverage exclusions and unassessable claims remain visible in the
quality scorecard; a high radar score cannot certify them.

| Stable axis | Exact formula |
| --- | --- |
| Evidence accuracy | `100 × mean(deterministic factual-grounding pass rate, min(citation-ID validity, citation entailment), 1 − unsupported/contradicted claim rate)` |
| Geographic intelligence | `100 × mean(deterministic geographic-discipline pass rate, normalized judge geographic discipline)` |
| Source coverage | `100 × mean(required-source-family presence rate, normalized judge evidence completeness)` |
| Joined analysis | `100 × mean(normalized cross-source synthesis, normalized inference discipline, normalized evidence-gap handling)`, using **joined-category attempts only** |
| Analytical usefulness | `100 × mean(normalized decision usefulness, normalized evidence completeness, normalized writing quality, normalized inference discipline)` |
| Conversational ability | `100 × mean(correct follow-up interpretation, 1 − unnecessary clarification, factual-grounding proxy after resolution)`, requiring all frozen sequence turns to be attempted and at least 20 sequences |
| Performance | `100 × [0.45 × min(1,5/complex median seconds) + 0.25 × min(1,15/complex P95 seconds) + 0.15 × explicit route-assertion pass rate + 0.15 × explicit zero-call-budget pass rate]` |
| Cost efficiency | `100 × min(1,(complex usefulness points/90) × (0.003/complex median USD))`; all successful complex attempts must have priced usage |

The 5-second median, 15-second P95 and USD0.003 at 90/100 usefulness are fixed
scoring anchors, not claimed measurements or release acceptance thresholds.
Targets stay fixed across releases. Failed attempts remain in availability and
client-attempt latency distributions; missing cost receipts are not zero-cost
successes. Radar latency is success-only server latency and is labelled as such.
The observed complex cohort includes `complex_research` and `deep_research`.
Incorrect fast routing remains an independent route assertion and hard quality
failure: it cannot be used to qualify a release through a faster radar.

Geographic checks and judge geographic discipline cover hierarchy, resolution
and release/boundary handling according to the frozen case expectations. They
are not three independently measured subscores. Relevant source diversity is
represented by **requested family presence**; extra unrelated families earn
no reward. Conversational grounding is the frozen suite's evidence/citation/
number proxy, not a substitute for semantic entailment. Route and call scores
use only explicit assertions; unavailable source-plan observations do not
become an inferred unnecessary-call measurement.

Repeated attempts receive the same attempt weighting as the release scorecard.
Overlay comparisons require identical benchmark manifest, suite, split,
case/repetition configuration and evaluator configuration. An older version
with only legacy test pass counts has **no radar score**. Versions v0.3, V1, V2,
V3, V4 and the current candidate remain listed even when unavailable.

## Automatic release artifacts

`evaluation.scorecard` regenerates a `release/` directory whenever a benchmark
scorecard is generated. The report includes an SVG radar, JSON/CSV 0–100 table,
protected-gate status, quality/latency/cost data, the five highest-priority
measured weaknesses or missing qualifications, and comparison against live.
The SVG has accessible text and a fixed 0–100 scale. Missing values break its
lines and are explicitly labelled; no missing polygon is drawn through zero.

```
python -m evaluation.scorecard --run CANDIDATE_RUN --oracle PRIVATE_ORACLE \
  --live-run LIVE_RUN --conversation CONVERSATION_SCORECARD --label 'Current candidate'
python -m evaluation.radar --run LIVE_RUN --label V4 --output RELEASE_DIRECTORY
python -m evaluation.radar --run CANDIDATE_RUN --live LIVE_RUN \
  --conversation CONVERSATION_SCORECARD --historical V2=COMPARABLE_V2_RUN
```

Protected gates use the release scorecard with zero regression tolerance for
this sprint's explicit no-regression requirement. Citation-ID correctness requires no invalid
IDs. Deterministic factual-grounding failures remain explicit failures. Privacy,
human calibration, held-out qualification, live smoke and target improvement
retain their own statuses. No radar average or total score is generated.

Service-produced aggregate exports may regenerate charts without raw evidence.
Their `radar_inputs.json` must bind to the exported scorecard SHA256 and this exact
formula version. Inputs are computed from the privately retained original run,
not manually rated. Original scorecard SHA256 and deployed commit remain recorded.
A separately measured conversation suite can replace only conversation inputs;
partial suites remain unavailable. This export path does not change formulas.
