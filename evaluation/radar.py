"""Versioned capability summaries. Missing measurements are never zero or passes.

The radar is deliberately independent of release qualification. All inputs are
derived from immutable benchmark attempts, validator checks and judge receipts.
SVG generation needs only Python's standard library, including in offline CI.
"""
import argparse
import csv
import html
import json
import math
import statistics
from pathlib import Path

from .common import digest, load_cases, now, write_json
from .scorecard import distribution
from .telemetry import enriched

VERSION = "mkh-capability-radar-1.0"
AXES = ["Evidence accuracy", "Geographic intelligence", "Source coverage",
        "Joined analysis", "Analytical usefulness", "Conversational ability",
        "Performance", "Cost efficiency"]
ANCHORS = {"complex_median_seconds": 5.0, "complex_p95_seconds": 15.0,
           "complex_median_usd": 0.003, "quality_points": 90.0}
FORMULAS = {
    AXES[0]: "100 × mean(deterministic factual-grounding pass rate, min(citation-ID validity, claim citation entailment), 1 − unsupported-or-contradicted claim rate)",
    AXES[1]: "100 × mean(deterministic geographic-discipline pass rate, (mean judge geographic discipline − 1)/4)",
    AXES[2]: "100 × mean(required relevant source-family presence rate, (mean judge evidence completeness − 1)/4)",
    AXES[3]: "100 × mean((joined-case mean cross-source synthesis − 1)/4, (joined-case mean inference discipline − 1)/4, (joined-case mean evidence-gap handling − 1)/4)",
    AXES[4]: "100 × mean((mean decision usefulness − 1)/4, (mean evidence completeness − 1)/4, (mean writing quality − 1)/4, (mean inference discipline − 1)/4)",
    AXES[5]: "100 × mean(follow-up correct-interpretation rate, 1 − unnecessary-clarification rate, follow-up factual-grounding proxy rate); requires every frozen sequence/turn to have been attempted",
    AXES[6]: "100 × [0.45 × min(1,5/complex median seconds) + 0.25 × min(1,15/complex P95 seconds) + 0.15 × explicit route-assertion pass rate + 0.15 × explicit zero-call-budget pass rate]",
    AXES[7]: "100 × min(1, (normalized complex-query decision-usefulness points/90) × (0.003/complex median USD)); all complex success costs must be priced",
}


def fraction(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return float(value)


def rubric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 1 <= value <= 5:
        return None
    return (value - 1) / 4


def combine(values, weights=None):
    if any(v is None for v in values):
        return None
    weights = weights or [1 / len(values)] * len(values)
    return round(100 * sum(v * w for v, w in zip(values, weights)), 2)


def observed_rate(checks):
    # An unknown assertion cannot silently improve the denominator.
    if not checks or any(c['status'] not in {'pass', 'fail'} for c in checks):
        return None
    return sum(c['status'] == 'pass' for c in checks) / len(checks)


def inputs(scorecard, run, conversation=None):
    run = Path(run)
    cases = {c['id']: c for c in load_cases(scorecard['split'], scorecard['split'] == 'heldout')}
    records = [enriched(run, json.loads(p.read_text())) for p in sorted((run / 'raw').glob('*.json'))]
    groups = {'route': [], 'zero_calls': []}
    joined, complex_quality = [], []
    complex_rows = []
    for record in records:
        case = cases[record['case_id']]
        validation = run / 'validation' / f"{record['case_id']}--{record['repetition']}.json"
        checks = json.loads(validation.read_text())['checks'] if validation.exists() else []
        for kind in groups:
            for assertion in case.get('deterministic_assertions', []):
                if assertion['type'] == kind:
                    check = next((c for c in checks if c['id'] == assertion['id']), None)
                    groups[kind].append(check or {'status': 'unknown'})
        # Use the observed research cohort consistently, preserving the route
        # assertion metric so an incorrect fast route cannot qualify a release.
        complex_query = record['telemetry'].get('route') in {'complex_research', 'deep_research'}
        if complex_query:
            complex_rows.append(record)
        jp = run / 'judgments' / f"{record['case_id']}--{record['repetition']}.json"
        if jp.exists():
            judgment = json.loads(jp.read_text())
            if judgment['response_hash'] != record['response_hash']:
                raise ValueError('Radar judgment does not match captured answer')
            scores = judgment['result']['scores']
            if case['category'] == 'joined_analysis':
                joined.append(scores)
            if complex_query:
                complex_quality.append(scores.get('decision_usefulness'))
    ok = [r for r in complex_rows if r['ok']]
    latency = distribution([r['telemetry']['server_seconds'] for r in ok if r['telemetry'].get('server_seconds') is not None])
    costs = [r['telemetry'].get('estimated_usd') for r in ok]
    priced = bool(ok) and all(c is not None and c >= 0 and not r['telemetry'].get('unpriced_calls') for c, r in zip(costs, ok))
    dims = scorecard.get('analytical_dimensions', {})
    deterministic = scorecard.get('deterministic_metrics', {})
    values = {
        'grounding': fraction(deterministic.get('factual_grounding', {}).get('value')),
        'citation_ids': fraction(deterministic.get('citation_validity', {}).get('value')),
        'citation_entailment': fraction(scorecard.get('citation_entailment', {}).get('value')),
        'unsupported_claim_rate': fraction(scorecard.get('unsupported_claim_rate', {}).get('value')),
        'geography': fraction(deterministic.get('geographic_discipline', {}).get('value')),
        'geographic_quality': rubric(dims.get('geographic_discipline', {}).get('mean')),
        'family_recall': fraction(deterministic.get('retrieval_family_coverage', {}).get('value')),
        'completeness': rubric(dims.get('evidence_completeness', {}).get('mean')),
        'usefulness': rubric(dims.get('decision_usefulness', {}).get('mean')),
        'clarity': rubric(dims.get('writing_quality', {}).get('mean')),
        'inference': rubric(dims.get('inference_discipline', {}).get('mean')),
        'route_efficiency': observed_rate(groups['route']),
        'call_efficiency': observed_rate(groups['zero_calls']),
        'complex_latency': latency,
        'complex_priced': priced,
        'complex_median_usd': statistics.median(costs) if priced else None,
        'complex_usefulness': rubric(statistics.mean(complex_quality)) if complex_quality and all(s is not None for s in complex_quality) else None,
        'joined_attempts': len(joined),
        'complex_attempts': len(complex_rows),
        'complex_failures': len(complex_rows) - len(ok),
    }
    for key in ['cross_source_synthesis', 'inference_discipline', 'evidence_gap_handling']:
        scored = [s.get(key) for s in joined]
        values['joined_' + key] = rubric(statistics.mean(scored)) if scored and all(s is not None for s in scored) else None
    full_suite = scorecard.get('composition', {}).get('unique_cases') == scorecard.get('composition', {}).get('expected_unique_cases') and bool(scorecard.get('composition', {}).get('unique_cases'))
    judging_complete = scorecard.get('judged_attempts', 0) >= scorecard.get('availability', {}).get('successes', 0)
    values['benchmark_complete'] = full_suite
    values['judging_complete'] = judging_complete
    if not full_suite or not judging_complete:
        # Partial benchmark means cannot masquerade as whole-release capability.
        for key in ['grounding','citation_ids','citation_entailment','unsupported_claim_rate',
                    'geography','geographic_quality','family_recall','completeness','usefulness',
                    'clarity','inference','complex_usefulness','joined_cross_source_synthesis',
                    'joined_inference_discipline','joined_evidence_gap_handling']:
            values[key] = None
    if not full_suite:
        values['route_efficiency'] = values['call_efficiency'] = None
    complete = conversation and conversation.get('completed_sequences') == conversation.get('suite_sequences') and conversation.get('suite_sequences', 0) >= 20
    for key in ['correct_interpretation_rate', 'unnecessary_clarification_rate', 'factual_grounding_proxy_rate']:
        values[key] = fraction(conversation.get(key)) if complete else None
    values['conversation_complete'] = bool(complete)
    values['assertion_denominators'] = {k: len(v) for k, v in groups.items()}
    return values


def scores(v):
    citation = min(v['citation_ids'], v['citation_entailment']) if v['citation_ids'] is not None and v['citation_entailment'] is not None else None
    clean = 1 - v['unsupported_claim_rate'] if v['unsupported_claim_rate'] is not None else None
    clarifications = 1 - v['unnecessary_clarification_rate'] if v['unnecessary_clarification_rate'] is not None else None
    latency = v['complex_latency']
    def speed(key, anchor):
        measured = latency.get(key)
        return min(1, anchor / measured) if measured is not None and measured > 0 else (1 if measured == 0 else None)
    cost = v['complex_median_usd']
    quality = v['complex_usefulness']
    efficiency = None
    if v['complex_priced'] and quality is not None and cost is not None:
        efficiency = min(1, quality * 100 / ANCHORS['quality_points'] * ANCHORS['complex_median_usd'] / cost) if cost > 0 else (1 if quality > 0 else 0)
    return dict(zip(AXES, [
        combine([v['grounding'], citation, clean]),
        combine([v['geography'], v['geographic_quality']]),
        combine([v['family_recall'], v['completeness']]),
        combine([v['joined_' + k] for k in ['cross_source_synthesis', 'inference_discipline', 'evidence_gap_handling']]),
        combine([v[k] for k in ['usefulness', 'completeness', 'clarity', 'inference']]),
        combine([v['correct_interpretation_rate'], clarifications, v['factual_grounding_proxy_rate']]),
        combine([speed('median', 5), speed('p95', 15), v['route_efficiency'], v['call_efficiency']], [.45, .25, .15, .15]),
        None if efficiency is None else round(100 * efficiency, 2),
    ]))


def signature(scorecard):
    return {k: scorecard.get(k) for k in ['split', 'attempt_configuration_hash', 'evaluator_configuration']} | {
        k: scorecard.get('run_manifest', {}).get(k) for k in ['benchmark_manifest_sha256', 'suite_hash']}


def comparable(a, b):
    sa, sb = signature(a), signature(b)
    return all(v is not None for v in sa.values()) and sa == sb


def gates(scorecard, live=None):
    from .scorecard import PROTECTED
    def get(obj, path):
        for key in path:
            obj = obj.get(key) if isinstance(obj, dict) else None
        return obj
    result = {}
    compatible = live is not None and comparable(scorecard, live)
    for name, path in PROTECTED.items():
        value = get(scorecard, path)
        previous = get(live, path) if compatible else None
        loss = value - previous if name == 'grounding' and value is not None and previous is not None else (previous - value if value is not None and previous is not None else None)
        status = 'UNKNOWN' if value is None else 'BASELINE_ONLY'
        if live is not None:
            status = 'NOT_COMPARABLE' if not compatible else ('UNKNOWN' if loss is None else ('REGRESSION' if loss > .05 + 1e-12 else 'WITHIN_TOLERANCE'))
        if name == 'citation_validity' and value is not None and value < 1:
            status = 'FAIL'
        result[name] = {'status': status, 'value': value, 'live': previous, 'regression': loss}
    # Explicitly expose factual grounding separately from the unsupported-claim gate.
    fact = scorecard.get('deterministic_metrics', {}).get('factual_grounding', {})
    result['factual_grounding_checks'] = {'status': 'FAIL' if fact.get('fail', 0) else ('MEASURED' if fact.get('value') is not None else 'UNKNOWN'), 'value': fact.get('value'), 'failures': fact.get('fail')}
    prereqs = scorecard.get('release_prerequisites', {})
    for key in ['privacy_audit_pass', 'human_calibrated', 'heldout_qualified', 'live_smoke_pass', 'target_improvement_verified']:
        value = prereqs.get(key)
        result[key] = {'status': 'PASS' if value is True else ('NOT_ESTABLISHED' if value is False else 'UNKNOWN'), 'value': value}
    return result


def svg(series):
    cx, cy, radius = 440, 350, 230
    def point(index, value):
        angle = -math.pi / 2 + index * math.pi / 4
        return cx + radius * value / 100 * math.cos(angle), cy + radius * value / 100 * math.sin(angle)
    def coords(points):
        return ' '.join(f'{x:.2f},{y:.2f}' for x, y in points)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="790" viewBox="0 0 1000 790" role="img" aria-labelledby="title desc">',
           '<title id="title">MKH capability radar</title><desc id="desc">Eight capabilities on a fixed zero to one hundred scale. Missing measurements break the lines, and are labelled unavailable. This chart does not certify a release.</desc>',
           '<rect width="1000" height="790" fill="white"/>',
           '<g font-family="system-ui,Arial,sans-serif" fill="#143b46"><text x="40" y="38" font-size="25" font-weight="700">MKH capability radar</text><text x="40" y="64" font-size="14" fill="#586e75">Measured capabilities · 0–100 · provisional judge scores · gates remain separate</text>']
    for value in [20, 40, 60, 80, 100]:
        out.append(f'<polygon points="{coords([point(i,value) for i in range(8)])}" fill="none" stroke="#dbe5e7"/>')
        out.append(f'<text x="{cx+6}" y="{cy-radius*value/100+15:.2f}" font-size="11" fill="#789096">{value}</text>')
    for i, axis in enumerate(AXES):
        x, y = point(i, 100)
        tx, ty = point(i, 122)
        anchor = 'start' if tx > cx + 20 else ('end' if tx < cx - 20 else 'middle')
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.2f}" y2="{y:.2f}" stroke="#dbe5e7"/>')
        out.append(f'<text x="{tx:.2f}" y="{ty:.2f}" text-anchor="{anchor}" font-size="14" font-weight="600">{html.escape(axis)}</text>')
    colors = ['#007f86', '#ce7130', '#6549a2', '#5875a4']
    drawn = [s for s in series if any(s['scores'][a] is not None for a in AXES)]
    for j, s in enumerate(drawn):
        color = colors[j % len(colors)]
        vals = [s['scores'][a] for a in AXES]
        if all(v is not None for v in vals):
            out.append(f'<polygon points="{coords([point(i,v) for i,v in enumerate(vals)])}" fill="{color}" fill-opacity="0.06" stroke="none"/>')
        for i, v in enumerate(vals):
            if v is None:
                continue
            x, y = point(i, v)
            nxt = (i + 1) % 8
            if vals[nxt] is not None:
                nx, ny = point(nxt, vals[nxt])
                out.append(f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{nx:.2f}" y2="{ny:.2f}" stroke="{color}" stroke-width="2.5"/>')
            out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}"><title>{html.escape(s["label"])} — {html.escape(AXES[i])}: {v:.2f}</title></circle>')
        ly = 660 + j * 23
        missing = ', '.join(a for a,v in s['scores'].items() if v is None)
        caption = s['label'] + (' · unavailable: ' + missing if missing else '')
        out.append(f'<line x1="40" y1="{ly}" x2="66" y2="{ly}" stroke="{color}" stroke-width="3"/><text x="77" y="{ly+5}" font-size="13">{html.escape(caption)}</text>')
    out.append('<text x="40" y="758" font-size="12" fill="#586e75">Missing ≠ zero. Historical versions without comparable measurements are listed in the table.</text></g></svg>')
    return '\n'.join(out)


def png(series, output):
    """Optional standard plotting export; the dependency-free SVG always exists."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return
    angles = [i * math.pi / 4 for i in range(8)]
    figure, ax = plt.subplots(figsize=(10, 8.7), subplot_kw={'projection': 'polar'})
    ax.set_theta_offset(math.pi / 2); ax.set_theta_direction(-1)
    ax.set_ylim(0, 100); ax.set_yticks([20,40,60,80,100]); ax.set_rlabel_position(12)
    ax.tick_params(axis='y', labelsize=9, colors='#789096')
    ax.set_xticks(angles, [a.replace(' ', '\n', 1) for a in AXES])
    ax.tick_params(axis='x', pad=18, labelsize=11, colors='#143b46')
    ax.grid(color='#dbe5e7'); ax.spines['polar'].set_color('#dbe5e7')
    colors=['#007f86','#ce7130','#6549a2','#5875a4']
    drawn=[s for s in series if any(v is not None for v in s['scores'].values())]
    for i,s in enumerate(drawn):
        values=[s['scores'][a] if s['scores'][a] is not None else float('nan') for a in AXES]
        ax.plot(angles+[angles[0]], values+[values[0]], marker='o', linewidth=2.2, color=colors[i%len(colors)], label=s['label'])
        if all(s['scores'][a] is not None for a in AXES):
            ax.fill(angles,values,color=colors[i%len(colors)],alpha=.06)
    ax.legend(loc='lower center',bbox_to_anchor=(.5,-.22),frameon=False,ncol=2)
    figure.suptitle('MKH capability radar',fontsize=21,color='#143b46',fontweight='bold',y=.98)
    figure.text(.5,.936,'Measured capabilities · 0–100 · provisional judge scores · gates remain separate',ha='center',fontsize=11,color='#586e75')
    missing='; '.join(s['label']+': '+', '.join(a for a,v in s['scores'].items() if v is None) for s in drawn if any(v is None for v in s['scores'].values()))
    figure.text(.5,.026,'Unavailable measurements break the line; missing ≠ zero.\n'+missing,ha='center',fontsize=10,color='#586e75',wrap=True)
    figure.subplots_adjust(top=.84,bottom=.2,left=.15,right=.85)
    figure.savefig(Path(output)/'capability_radar.png',dpi=170,facecolor='white',bbox_inches='tight')
    plt.close(figure)


def generate(run, output=None, label='Current candidate', live=None, conversation=None, historical=None):
    run = Path(run); output = Path(output) if output else run / 'release'
    output.mkdir(parents=True, exist_ok=True)
    scorecard = json.loads((run / 'scorecard.json').read_text())
    measured = inputs(scorecard, run, conversation)
    current = {'label': label, 'scores': scores(measured), 'input_metrics': measured, 'scorecard_sha256': digest(scorecard), 'benchmark_signature': signature(scorecard)}
    series = [current]
    live_card = None
    if live:
        live = Path(live)
        live_card = json.loads((live / 'scorecard.json').read_text())
        if comparable(scorecard, live_card):
            metrics = inputs(live_card, live)
            series.insert(0, {'label': 'Current live V4', 'scores': scores(metrics), 'scorecard_sha256': digest(live_card), 'input_metrics': metrics, 'benchmark_signature': signature(live_card)})
        else:
            series.insert(0, {'label': 'Current live V4', 'scores': dict.fromkeys(AXES), 'unavailable_reason': 'Missing or incompatible benchmark, repetition or evaluator configuration'})
    for version in ['v0.3', 'V1', 'V2', 'V3', 'V4', 'Current candidate']:
        if version == label or version == 'V4' and live or version == 'Current candidate' and label.lower().endswith('candidate'):
            continue
        path = (historical or {}).get(version)
        if path:
            old = json.loads((Path(path) / 'scorecard.json').read_text())
            if comparable(old, scorecard):
                metrics = inputs(old, path)
                series.append({'label': version, 'scores': scores(metrics), 'scorecard_sha256': digest(old), 'input_metrics': metrics, 'benchmark_signature': signature(old)})
                continue
        series.append({'label': version, 'scores': dict.fromkeys(AXES), 'unavailable_reason': 'No comparable measured benchmark supplied'})
    protected = gates(scorecard, live_card)
    weaknesses = []
    for name, gate in protected.items():
        if gate['status'] in {'FAIL', 'REGRESSION', 'UNKNOWN', 'NOT_ESTABLISHED'}:
            priority = 0 if gate['status'] in {'FAIL', 'REGRESSION'} else (1 if name == 'privacy_audit_pass' else 3)
            weaknesses.append({'priority_class': priority, 'area': name, 'status': gate['status'], 'measured_value': gate.get('value')})
    for axis, value in sorted(current['scores'].items(), key=lambda p: -1 if p[1] is None else p[1]):
        weaknesses.append({'priority_class': 1 if value is None else 2, 'area': axis, 'status': 'UNAVAILABLE' if value is None else 'MEASURED_CAPABILITY', 'measured_value': value})
    weaknesses.sort(key=lambda w:(w['priority_class'], -1 if w['measured_value'] is None else w['measured_value']))
    comparison = {a: {'live': series[0]['scores'][a] if live else None, 'candidate': current['scores'][a] if live else None,
                       'change': round(current['scores'][a] - series[0]['scores'][a], 2) if live and current['scores'][a] is not None and series[0]['scores'][a] is not None else None} for a in AXES}
    result = {'formula_version': VERSION, 'formula_sha256': digest({'formulas': FORMULAS, 'anchors': ANCHORS}), 'generated_at': now(), 'axes': AXES,
              'formulas': FORMULAS, 'anchors': ANCHORS, 'series': series, 'protected_gates': protected, 'comparison_against_live': comparison,
              'top_5_remaining_weaknesses': weaknesses[:5], 'release_qualification': 'Use the protected scorecard and all release prerequisites; radar scores never authorize release.',
              'limitations': ['Judge scores are provisional until Publisher calibration.', 'Unassessable claims and missing historical data are not passes or zero capability.', 'Required-family presence is a relevant-source recall proxy; unrelated source families do not earn extra points.', 'Conversational grounding is a deterministic presence/number proxy, not semantic entailment.', 'Performance and cost use the observed complex-research cohort; incorrect fast routing is separately gated.', 'Repeated attempts have the same weighting as in the paired release scorecard.']}
    write_json(output / 'capability_table.json', result)
    write_json(output / 'protected_gates.json', protected)
    write_json(output / 'comparison_against_live.json', comparison)
    write_json(output / 'top_5_weaknesses.json', weaknesses[:5])
    quality = {k: scorecard.get(k) for k in ['composition', 'availability', 'analytical_dimensions', 'unsupported_claim_rate', 'citation_entailment', 'claim_assessment_coverage', 'by_mode', 'hub_estimated_cost_usd', 'evaluator_estimated_cost_usd', 'release_prerequisites']}
    quality['complex_cohort'] = {k:v for k,v in measured.items() if k.startswith('complex_')}
    write_json(output / 'quality_latency_cost.json', quality)
    (output / 'capability_radar.svg').write_text(svg(series))
    png(series,output)
    with (output / 'capability_table.csv').open('w', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(['Capability'] + [s['label'] for s in series])
        writer.writerows([[a] + ['Unavailable' if s['scores'][a] is None else s['scores'][a] for s in series] for a in AXES])
    rows = ''.join('<tr><th>'+html.escape(a)+'</th>'+''.join('<td>'+('Unavailable' if s['scores'][a] is None else f"{s['scores'][a]:.2f}")+'</td>' for s in series)+'</tr>' for a in AXES)
    details = ''.join('<dt>'+html.escape(a)+'</dt><dd>'+html.escape(FORMULAS[a])+'</dd>' for a in AXES)
    gate_rows = ''.join(f'<tr><th>{html.escape(k)}</th><td>{html.escape(v["status"])}</td><td>{html.escape(str(v.get("value")))}</td></tr>' for k,v in protected.items())
    weakness_rows = ''.join('<li>'+html.escape(w['area']+' — '+w['status'])+'</li>' for w in weaknesses[:5])
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MKH capability release report</title><style>body{font:15px/1.6 system-ui;color:#143b46;background:#f4f8f8}main{max-width:1160px;background:white;margin:24px auto;padding:36px}img{width:100%;max-width:1000px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;text-align:left;border-bottom:1px solid #dbe5e7}th{background:#f1f7f7}dd{margin-bottom:16px}.scroll{overflow:auto}h2{margin-top:32px}</style><main><h1>MKH capability release report</h1><p>Visual summary only. Provisional analytical scores; unavailable measurements remain explicit. The radar cannot qualify a release.</p><img src="capability_radar.svg" alt="MKH eight-axis capability radar"><h2>Capability table · 0–100</h2><div class="scroll"><table><tr><th>Capability</th>'+''.join('<th>'+html.escape(s['label'])+'</th>' for s in series)+'</tr>'+rows+'</table></div><h2>Protected gates</h2><table><tr><th>Metric</th><th>Status</th><th>Measured value</th></tr>'+gate_rows+'</table><h2>Top five remaining weaknesses</h2><ol>'+weakness_rows+'</ol><h2>Fixed formulas</h2><p>'+VERSION+' · Rates are fractions. Judge means use (score−1)/4. Any missing required component makes the axis unavailable; weights are never redistributed.</p><dl>'+details+'</dl><p>Fixed reference targets: median complex latency 5 seconds; P95 15 seconds; USD0.003 per complex query at 90/100 usefulness. These are scoring anchors, not measured facts or release acceptance thresholds.</p><h2>Quality, latency and cost</h2><p>Complete distributions, token counts and costs: <a href="quality_latency_cost.json">quality_latency_cost.json</a>. Paired live comparison: <a href="comparison_against_live.json">comparison_against_live.json</a>. Full metric inputs and provenance: <a href="capability_table.json">capability_table.json</a>.</p></main></html>'
    (output / 'release_report.html').write_text(page)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True); parser.add_argument('--output'); parser.add_argument('--label', default='Current candidate')
    parser.add_argument('--live'); parser.add_argument('--conversation'); parser.add_argument('--historical', action='append', default=[])
    args = parser.parse_args()
    conversation = json.loads(Path(args.conversation).read_text()) if args.conversation else None
    historical = dict(item.split('=', 1) for item in args.historical)
    result = generate(args.run, args.output, args.label, args.live, conversation, historical)
    print(json.dumps({'formula_version': VERSION, 'scores': result['series'][-1]['scores'] if len(result['series']) == 1 else next(s['scores'] for s in result['series'] if s['label'] == args.label)}))
