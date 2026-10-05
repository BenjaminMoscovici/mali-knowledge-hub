"""Render measured baseline artifacts without converting unknowns into passes."""
import argparse
import html
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from .common import write_json
from .scorecard import distribution


def build(results, output):
    results, output = Path(results), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    runs = {name: json.loads((results / f'{name}-20261005' / 'scorecard.json').read_text())
            for name in ['baseline', 'heldout', 'rolling']}
    baseline = runs['baseline']
    raw = [json.loads(p.read_text()) for p in (results / 'baseline-20261005/raw').glob('*.json')]
    phase_cost, phase_times, calls, routes = defaultdict(float), defaultdict(list), Counter(), Counter()
    for record in raw:
        t = record['telemetry']
        routes[t['route']] += 1
        calls[(t['depth'], sum(c['endpoint'] == 'responses' for c in t['model_calls']))] += 1
        for call in t['model_calls']:
            phase_cost[call['phase']] += call.get('estimated_usd') or 0
            phase_times[call['phase']].append(call.get('seconds', 0))
    first_judges = [json.loads(p.read_text()) for p in
                    (results / 'baseline-20261005/judgments').glob('*--0.json')]
    unique_scores = {dimension: statistics.mean(j['result']['scores'][dimension]
                     for j in first_judges if j['result']['scores'][dimension] is not None)
                     for dimension in baseline['analytical_dimensions']}
    smoke = json.loads((results / 'privacy_guest_smoke-20261005.json').read_text())
    seeded = json.loads((results / 'seeded-20261005/summary.json').read_text())
    prereqs = {'heldout_qualified': False, 'live_smoke_pass': smoke['live_smoke_pass'],
               'privacy_audit_pass': None, 'human_calibrated': False,
               'target_improvement_verified': False}
    release = {'decision': 'BASELINE_ONLY_NOT_QUALIFIED', 'release_prerequisites': prereqs,
               'hub_commit': baseline['run_manifest']['hub_commit'],
               'benchmark_hash': baseline['run_manifest']['benchmark_manifest_sha256'],
               'unique_case_dimension_means': unique_scores,
               'phase_cost_usd': dict(phase_cost),
               'phase_model_call_seconds': {k: distribution(v) for k, v in phase_times.items()},
               'routes': dict(routes),
               'generation_pass_counts': {f'{mode}:{n}': count for (mode, n), count in calls.items()},
               'measured_candidate_configurations': 0,
               'limitations': 'Uncalibrated analytical scores; partial public evidence coverage; no authenticated cross-user privacy audit or candidate optimization measured.'}
    write_json(output / 'release_scorecard.json', release)
    md, web = [], []

    def heading(text, level=2):
        md.append('#' * level + ' ' + text)
        web.append(f'<h{level}>{html.escape(text)}</h{level}>')

    def paragraph(text):
        md.append(text)
        web.append('<p>' + html.escape(text) + '</p>')

    def table(headers, rows):
        rows = [[str(v) for v in row] for row in rows]
        md.append('\n'.join(['| ' + ' | '.join(headers) + ' |',
                              '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                             ['| ' + ' | '.join(row) + ' |' for row in rows]))
        web.append('<div class="scroll"><table><thead><tr>' + ''.join('<th>' + html.escape(h) + '</th>' for h in headers)
                   + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + html.escape(v) + '</td>' for v in row)
                   + '</tr>' for row in rows) + '</tbody></table></div>')

    heading('MKH V4 evaluation baseline — 5 October 2026', 1)
    paragraph('Implemented and executed against the unchanged V4 test Hub. Release status: BASELINE ONLY — NOT QUALIFIED. No answer-pipeline optimization, source integration, deployment, n8n access or TGA operation was performed.')
    paragraph('The 75-case benchmark was frozen and committed at b298353 before the first live request. Evaluated live commit: ' + release['hub_commit'] + '. Correct GIZ project: hofoubbmepacdljeablj. The framework reuses the V3 citation validator, original packaged source records and shared GIZ document/chunk provenance. Evaluation persistence is separate JSON/SQLite; no production schema migration was needed.')
    heading('What is implemented')
    table(['Component', 'Implementation / status'], [
        ['Frozen regression set', '75 cases; immutable hashes; all 31 legacy development questions retained'],
        ['Rolling challenge set', '7 cases; versioned failure provenance; v1 transport fixture corrected in v2 without rewriting v1'],
        ['Held-out acceptance set', '18 cases including all 11 older held-out questions; explicit acceptance flag'],
        ['Deterministic validators', 'Citation IDs, original locators, numbers, dates, geographic checks, family presence and routing proxies; unknowns explicit'],
        ['Analytical scoring', 'Pinned independent gpt-5-mini-2025-08-07; 9 dimensions, atomic claims, immutable raw judgments and versioned coverage adjustments'],
        ['Telemetry / cost', 'Provider tokens, cached tokens, model calls, phase timing, evidence selection, failure retention and distributions'],
        ['Release scorecards', 'Protected 5 percentage-point gates; paired suite/repetition/configuration checks; acceptance prerequisites'],
        ['External verification', '13 frozen + 2 held-out checks, answer-hash bound; primary public evidence kept separate from Hub'],
        ['Seeded evaluator tests', '9 deliberate errors + 9 clean controls executed'],
        ['Human calibration', '10 review packets and blank Publisher rating sheet exported; real review pending'],
        ['Offline CI', '14 framework tests pass locally; workflow added, not run remotely'],
    ])
    heading('Benchmark composition and execution')
    table(['Category', 'Frozen cases'], sorted(baseline['composition']['categories'].items()))
    paragraph('French coverage: 22/75 frozen cases (29.3%) and 4/18 held-out (22.2%). The held-out set preserves 11 legacy adversarial cases, so its category balance is weaker than the frozen suite. Keep it out of active tuning; this run is an initial acceptance milestone, not optimization feedback for specific held-out cases.')
    table(['Suite', 'Unique cases', 'Attempts', 'Successful', 'Judged'], [[n, s['composition']['unique_cases'], s['composition']['attempts'], s['availability']['successes'], s['judged_attempts']] for n, s in runs.items()])
    paragraph('Four frozen cases received three repetitions: JOIN01, JOIN02 (joined Mopti/EU), JOIN03 (transport/funding), FUND04. The rolling ended-project example case also received three. No failed request was resampled. Baseline requests ran sequentially from 09:26:49 to 09:46:12 UTC; the frozen manifest predates them.')
    heading('Quality: provisional independent scores')
    table(['Dimension (1–5)', 'Frozen 75 unique cases', 'Frozen 83 attempts', 'Held-out 18'], [[d.replace('_', ' '), f'{unique_scores[d]:.3f}', f'{v["mean"]:.3f}', f'{runs["heldout"]["analytical_dimensions"][d]["mean"]:.3f}'] for d, v in baseline['analytical_dimensions'].items()])
    for n, s in runs.items():
        u, c = s['unsupported_claim_rate'], s['claim_assessment_coverage']
        paragraph(f'{n}: unsupported/contradicted claim labels {u["unsupported_or_contradicted"]}/{u["assessed_material_claims"]} ({u["value"]:.2%}); {u["unassessable_claims"]} unassessable; claim assessment coverage {c["value"]:.2%}. Citation entailment among assessed cited claims: {s["citation_entailment"]["value"]:.2%}. These are evaluator labels, not a calibrated estimate of the true error rate.')
    paragraph('Frozen citation-ID checks: 249/249 passed. Original source-locator checks: 758 passed, 0 failed, 288 unknown. This confirms reference validity where resolved, not semantic support for every claim. Required-family presence: 114/122 passed; missing families do not by themselves prove a routing error. French language match: 23/24 frozen judged attempts and 2/4 held-out; repeated cases explain 24 French attempts versus 22 unique questions.')
    paragraph('The external judge received independently downloaded government PDF pages and registered public aggregate evidence. Unverified HNRP/UNICEF document excerpts were withheld (374 evidence items across the frozen attempts). Coverage guard 1.1 marks missing material and omitted retrieval metadata as unassessable; raw outputs remain unchanged. Raw dimension ratings can still be affected by coverage. Reviewer cautions: the judge incorrectly treats COD 19 regions + 1 district as inconsistent with 20 admin1 units, and sometimes treats the separately stated Bamako exception as a missing hierarchy level. Do not publish geographic error claims from these flags without human adjudication.')
    heading('Frozen latency and cost')
    table(['Mode', 'n', 'Server median', 'P90', 'P95', 'Max', 'Client median', 'Median USD', 'Total USD'], [[mode, v['attempts'], *[f'{v["server_latency_seconds"][k]:.2f}s' for k in ['median', 'p90', 'p95', 'max']], f'{v["client_attempt_latency_seconds"]["median"]:.2f}s', f'{v["cost_usd"]["median"]:.6f}', f'{v["cost_usd"]["total"]:.6f}'] for mode, v in baseline['by_mode'].items()])
    paragraph('Quantiles use linear interpolation. Server latency excludes failed requests; all client attempt times and availability are retained. Requested mode is not identical to actual route. Fixed observer/network overhead makes client timings higher than server timings; use paired measurements from the same observer for future comparisons.')
    table(['Mode', 'Median input tokens', 'Median prompt characters', 'Maximum prompt characters'], [[mode, v['input_tokens']['median'], v['assembly_prompt_chars']['median'], v['assembly_prompt_chars']['max']] for mode, v in baseline['by_mode'].items()])
    heading('Joined Mopti and repeated cases')
    table(['Case', 'Rep', 'Server seconds', 'USD', 'Input tokens', 'Cached input tokens', 'Prompt characters'], [[r['case_id'], r['repetition'], r['telemetry']['server_seconds'], r['telemetry']['estimated_usd'], r['telemetry']['input_tokens'], r['telemetry']['cached_input_tokens'], r['telemetry']['evidence_assembly'].get('prompt_chars')] for r in sorted(raw, key=lambda r: (r['case_id'], r['repetition'])) if r['case_id'] in ['JOIN01', 'JOIN02', 'JOIN03', 'FUND04']])
    paragraph('JOIN02 selected 79 of 92 evidence items. Raw content was 125,759 characters; selected content 96,142; assembled prompt 156,153. Exact duplicate IDs were absent, but ID uniqueness does not prove absence of overlapping text or repeated facts. Provider caching made repeated cost much lower: this is baseline warm-cache behavior, not an implemented optimization. No cold/warm randomized experiment was performed.')
    heading('Routing, retrieval and model passes')
    table(['Actual route', 'Frozen attempts'], sorted(routes.items()))
    table(['Mode', 'Generation passes', 'Attempts'], [[mode, n, count] for (mode, n), count in sorted(calls.items())])
    table(['Model phase', 'Total estimated USD', 'Median per-call seconds'], [[phase, f'{cost:.6f}', f'{statistics.median(phase_times[phase]):.3f}'] for phase, cost in sorted(phase_cost.items())])
    paragraph('Most Deep attempts already use one generation pass (17/23); removing a universal extra pass is not justified. Balanced uses two passes in 28/51 cases. Measure planner necessity with an isolated ablation after this freeze. Model-call times can overlap and must not be added as wall-clock latency. Evidence ranks and per-family retrieval times are not exposed by the current API. Render usage logs enrich core source plans for 23/83 attempts, matched by request UUID; other family selection remains unknown. Existing synthesis selection, omissions and excerpt spans are captured rather than reimplemented.')
    heading('Important failures and review findings')
    table(['Finding', 'Observed behavior / implication'], [
        ['Fast follow-up repeats false context', 'Rolling synthetic prior answer claims 999 cercles and universal EU commune funding. Conversation-only shortening repeats both without qualification. Preserve fast routing, add provenance-aware handling for prior factual claims.'],
        ['Wrong route for a complex commune query', 'LEGACY-J12 asks what intervention presence can be established and where location data are uncertain; Hub gives a geography-only response. The geographic hierarchy is accurate but the operational question remains unanswered.'],
        ['Mopti evidence omitted', 'NEED03 returns Socoura 13,002 IDPs but misses original DTM source-labelled Mopti row 13,582. Neither is a regional total or approved commune join. Independent XLSX confirms the omission.'],
        ['Status/date example recall', 'FUND05 receives closed and future-ended examples rather than the requested active records with elapsed end dates. Its negative statement is scoped to returned evidence; retrieval selection still fails the task.'],
        ['French language mismatch', '1 frozen French attempt and 2 of 4 held-out French cases answered in English. Held-out evidence is reported at aggregate level for future tuning governance.'],
        ['Intermittent availability', 'One rolling transport/funding request returned HTTP503 after 12.03 client seconds; its cost is unknown. Three frozen repetitions of the transport query succeeded.'],
        ['Source details underused', 'LEGACY-D03 says component-by-component phasing is absent despite retrieved/public phasing tables; ACT02 cites an actor/sector list containing DRC while naming CICR as well. These need Publisher adjudication.'],
    ])
    heading('Independent web verification')
    table(['Suite', 'Cases checked', 'Consistent within checked scope', 'Hub incomplete', 'Not independently verifiable'], [[name, len(checks), sum(c['classification'] == 'consistent' for c in checks), sum(c['classification'] == 'Hub incomplete' for c in checks), sum(c['classification'] == 'not independently verifiable' for c in checks)] for name in ['baseline', 'heldout'] for checks in [json.loads((results / f'{name}-20261005/web_verification.json').read_text())['checks']]])
    paragraph('13/75 frozen cases (17.3%) and 2/18 held-out (11.1%) were checked after answer capture. INSTAT counts/population levels, selected EU commitments, EIB signature, and IEG target/rating distinctions were corroborated. Checks verify selected claims, not entire answers. The original NDICI annex and exact current FTS snapshot were not independently retrieved; partial corroboration is marked not independently verifiable.')
    paragraph('Version caveat: ECHO’s April 2026 country page shows an initial EUR25 million, while the September version5 HIP technical annex shows EUR32 million indicatively (30+2). Dates, versions and financial stages explain the difference; it is not evidence that a particular Hub claim is wrong. Source URLs, dates, scope, comparison and response hashes are in web_verification.json. The independently decoded DTM workbook shows the Mopti omission above. No answer was repaired using web checks.')
    heading('Cost accounting and acceptance limits')
    table(['Suite', 'Hub estimated USD', 'Independent judge USD'], [[n, f'{s["hub_estimated_cost_usd"]:.6f}', f'{s["evaluator_estimated_cost_usd"]:.6f}'] for n, s in runs.items()])
    paragraph(f'Seeded evaluator controls: {seeded["seeded_n"]}/9 errors caught, 0/9 clean controls falsely flagged; USD{seeded["evaluator_cost_usd"]:.6f}. A separate preliminary judge smoke cost USD0.003124. These tests measure the evaluator, not the production Hub verifier. Provider/token estimates are not invoices; the HTTP503 attempt has no cost receipt and is not silently priced at zero.')
    paragraph('Anonymous health/access-denial smoke passed 4/4. Signed-in cross-user authorization was not exercised, so the privacy audit remains incomplete. Ten Publisher calibration samples are ready but no human ratings have been invented. Held-out results are measured, not qualified. A GitHub workflow is present locally; remote CI and publication have not occurred. No measured before/after candidate or improvement frontier exists yet; this baseline is the first configuration point.')
    heading('Next optimization priorities, after this freeze')
    table(['Order', 'Change to test', 'Protection / measurement'], [
        ['1', 'Correct complex operational routing and fast follow-up provenance; enforce requested language', 'Keep simple geography fast; use frozen regressions and rolling failure cases'],
        ['2', 'Select task-specific DTM/FONGIM records and relevant document spans before synthesis', 'Preserve missed numeric/status rows, date/finance semantics and original citations'],
        ['3', 'Deduplicate overlapping text/facts and replace large source-family bulk with structured summaries', 'Version summaries; keep record/page locators and factual exceptions; measure JOIN02 input tokens and prompt size'],
        ['4', 'Cache stable structured evidence by release/version and retrieval parameters', 'Separate provider cache effects from evidence-cache effects; test warm and cold cases'],
        ['5', 'Parallelize independent retrieval and measure planner-pass ablations where present', 'Add candidate-only per-family timing/rank telemetry; no assumption that all current calls are redundant'],
        ['6', 'Paired benchmark, held-out milestone, Publisher calibration and authenticated privacy test', 'Accept only noticeable latency/token-cost improvement with protected quality; resume source integration afterwards'],
    ])
    heading('Reproduction and handover')
    paragraph('Use evaluation/README.md for commands. The implementation is isolated on an evaluation branch; production source files are unchanged. Apply the supplied patch to the unchanged live source tree, or use the code directory. Raw requests, immutable answers, judgments, public packets, locator oracle, source provenance, SQLite attempt stores, scorecards and calibration materials are in the evidence bundle. Runtime credentials and unrelated service data are excluded. Run from the repository root so relative public-PDF page paths resolve. Access to the configured GIZ project and an authorized judge key is required for new live runs; offline scoring and tests do not need secrets.')
    (output / 'MKH_V4_Baseline_Report.md').write_text('\n\n'.join(md) + '\n')
    style = 'body{font:16px/1.55 system-ui,sans-serif;color:#183044;margin:0;background:#f3f6f8}main{max-width:1100px;margin:auto;padding:48px;background:white}h1{font-size:32px;color:#073b4c}h2{margin-top:38px;border-top:2px solid #e4edf2;padding-top:20px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:10px;border-bottom:1px solid #dce6eb;vertical-align:top}th{background:#eaf3f6}tr:nth-child(even){background:#f7fafb}.scroll{overflow-x:auto}p{max-width:1050px}@media print{body{background:white}main{padding:0}h2{break-after:avoid}tr{break-inside:avoid}}'
    (output / 'MKH_V4_Baseline_Report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MKH V4 evaluation baseline</title><style>' + style + '</style><main>' + '\n'.join(web) + '</main></html>')
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.results, args.output)))
