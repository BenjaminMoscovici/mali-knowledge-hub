# MKH professional capability radar · version 2.1

The current default is `mkh-professional-capability-2.1`. This is a reporting
recalibration, not a change to frozen questions, judge labels or release gates.
The prior quality-only formulas and artifacts remain reproducible with
`--formula-version legacy`; see RADAR_FORMULAS_V1.md. Never compare a v1 score
to a v2 score as a product improvement.

100 means a mature, reliable professional analytical assistant across the fixed
Mali evidence requirements. Every available axis is:

`quality points × demonstrated capability coverage fraction × availability`.

No manually assigned scores, total radar average or redistributed weights.
Missing required measurements are **Unavailable**, not zero or a pass.

## Quality and coverage

Rates use their recorded denominators; a 1–5 judge mean becomes `(mean−1)/4`.
The quality formulas from v1 remain the measured quality component, with these
explicit overrides. Their exact expressions and anchors appear in every JSON.

| Axis | Quality component | Coverage component |
| --- | --- | --- |
| Evidence reliability & completeness | V1 grounding/citation/unsupported-claim quality × assessable claims / all material claims | Mean of all ten evidence layers |
| Geographic intelligence | V1 geographic validator and judge quality | Geographic requirements |
| Source coverage | V1 relevant-family recall and evidence completeness | Mean of all ten evidence layers |
| Joined analysis | V1 joined-only synthesis, inference and gap-handling quality | Mean of all ten layers; acknowledging a missing layer earns no coverage credit |
| Analytical usefulness | V1 decision usefulness, completeness, clarity and inference discipline | Mean of all ten layers needed for coordination, prioritisation, gaps and sequencing |
| Conversational ability | V1 interpretation, unnecessary-clarification and grounding-proxy quality | Demonstrated share of seven fixed context requirements |
| Performance | `100 × mean(min(1,mode target / all-attempt client median) × cell success rate) × mean(route assertion pass rate, zero-call assertion pass rate)` | Mean of professional evidence layers; all six cold/warm mode cells must first be observed |
| Cost efficiency | `min(V1 quality-adjusted cost-efficiency points, V1 usefulness points)` | Mean of professional layers; cheap incomplete answers cannot reach maturity |

Availability is successful attempts / all attempts. Failed calls remain visible
and receive no success substitution. Cost retains unknown/unpriced usage.
The evidence reliability and completeness axis discounts unassessable material claims instead of ignoring
them. Missing facts, incomplete relevant source coverage and citation failures
also lower the quality component; missing operational evidence lowers coverage.

## Frozen professional evidence requirements

`benchmarks/professional_requirements_v2_1.json` and its freeze manifest define
20 machine-checkable requirements, exactly two per evidence layer: needs,
priorities, actors, interventions, delivery/reach, funding, timelines, results,
learning and geography. Requirements have equal weights within each layer;
required layers have equal weights within an axis. Definitions, typed record
selectors, minimum distinct entities and numeric field checks are immutable.

Examples: organization presence cannot satisfy reached beneficiaries;
indicative allocations cannot satisfy verified project transactions; country
project profiles cannot satisfy approved local activity geography; three IEG
findings on one project cannot satisfy multi-project learning breadth.
Historical needs observations earn bounded evidence credit, but do not satisfy
current multisector assessment readiness. Traceable national strategies do not
satisfy local priorities. Narrative assertions and source-name counts cannot
satisfy operational data requirements.

Coverage is a **conservative demonstrated lower bound**, not a percentage of
all Mali documents. An unmatched requirement is **Not demonstrated**, not proof
that no relevant source exists. The evaluator scans immutable packaged data
from the measured commit and original captured evidence; it emits snapshot
hashes, source row witnesses, selector definitions and denominators. If the
commit's source objects cannot be retrieved, coverage is unavailable; today's
inventory is never substituted for a historical release.

Seven fixed conversation requirements cover geography/administrative level,
sex/metric, period, entity/status subset, continuity/topic reset, false-premise
referents and genuine ambiguity. A requirement is demonstrated only when all
its expected frozen follow-up turns interpret correctly and pass the factual
presence/number/context proxy. This is stricter than average turn reliability;
both measurements are reported. It is still not semantic claim entailment.

Performance requires explicitly tagged cold and warm observations for Quick,
Balanced and Deep, with client elapsed time and availability. Targets are
1/8/15 seconds respectively. Provider cached-token counts or request order do
not establish application cold/warm state. Historical runs without these six
cells are unavailable. Client timings are not compared across UI, HTTP or
isolated ASGI observer protocols.

Maturity bands: 0–20 prototype; 20–40 basic; 40–60 useful but materially
incomplete; 60–75 strong; 75–90 advanced; 90–100 near-mature professional.
These labels interpret calculated scores; they do not assign them.

## Release artifacts and comparability

`evaluation.scorecard` automatically generates the professional radar SVG/PNG,
0–100 JSON/CSV table, capability coverage/witnesses, protected gates,
quality/latency/cost scorecard, five remaining weaknesses and live comparison.
The JSON includes exact formulas, requirement SHA256, component scores and
limitations. Version 2 scores use independently recorded baseline judgments;
uncalibrated analytical scores remain provisional. Missing historical or
candidate independent judgments remain unavailable; no labels are fabricated.

Comparisons require identical original suite, repetition, evaluator, observer
protocol and recalibration definitions. Frozen baseline data and v1 artifacts
must not be overwritten. Recompute comparable versions into a new directory:

```
python -m evaluation.radar --run BASELINE_RUN --label 'Current live V4' \
  --output PROFESSIONAL_V2_OUTPUT
python -m evaluation.radar --run CANDIDATE_RUN --live BASELINE_RUN \
  --conversation CONVERSATION_SCORECARD --output CANDIDATE_V2_OUTPUT
python -m evaluation.radar --run BASELINE_RUN --formula-version legacy \
  --output LEGACY_REPRODUCTION_OUTPUT
```

Hard gates stay separate: grounding, citation IDs/entailment, geography,
unsupported claims, privacy/access and original-currency preservation.
No high radar polygon compensates for a failure or unknown prerequisite.

Version 2.1 changes the evidence-axis display name only. The 2.0 freeze and artifacts remain preserved; numerical quality/coverage formulas and protected factual correctness are unchanged.
