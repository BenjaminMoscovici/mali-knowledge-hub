"""Professional radar v2: observed quality multiplied by demonstrated coverage.

Coverage is a conservative lower bound, not an assertion that unmatched evidence
does not exist. Typed, attributable observations count; prose mentioning a gap,
an indicative budget or a source name cannot satisfy an operational requirement.
The existing frozen benchmark and protected gates are never modified here.
"""
import gzip
import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path

from .common import ROOT, digest, now, write_json

VERSION = 'mkh-professional-capability-2.1'
REQUIREMENTS = Path(__file__).parent / 'benchmarks/professional_requirements_v2_1.json'


def requirements():
    value = json.loads(REQUIREMENTS.read_text())
    freeze = json.loads(REQUIREMENTS.with_name('professional_requirements_v2_1.freeze.json').read_text())
    if digest(value) != freeze['requirements_sha256']:
        raise ValueError('Frozen professional capability requirements changed')
    return value


def present(value):
    return value is not None and value is not False and value != '' and value != [] and value != {}


def field(obj, path):
    for part in path.split('.'):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def match(row, selector):
    for path, allowed in selector.get('equals', {}).items():
        if field(row, path) not in allowed:
            return False
    if not all(present(field(row, p)) for p in selector.get('required', [])):
        return False
    if not all(numeric(field(row, p)) for p in selector.get('numeric', [])):
        return False
    return True


def inventory(run, scorecard, measured):
    spec = requirements()
    run = Path(run)
    commit = scorecard['run_manifest']['hub_commit']
    rows, receipts = [], []
    # Read each version's immutable packaged data, not today's working snapshot.
    # A missing git object means unavailable coverage, never today's inventory.
    for filename in ['source_wave2.json.gz', 'source_wave3.json.gz',
                     'source_wave4.json.gz', 'source_wave5.json.gz']:
        try:
            blob = subprocess.check_output(['git', 'show', f'{commit}:v3/{filename}'],
                                           cwd=ROOT, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            return {'version': VERSION, 'status': 'UNAVAILABLE',
                    'reason': 'Immutable source snapshot not available for commit', 'hub_commit': commit}
        snapshot = json.loads(gzip.decompress(blob))
        rows.extend(snapshot['records'])
        receipts.append({'git_path': f'v3/{filename}', 'sha256': hashlib.sha256(blob).hexdigest(),
                         'records': len(snapshot['records'])})
    # Positive corpus capabilities can also be demonstrated by original captures.
    # Unobserved corpus capabilities remain not demonstrated, not proven absent.
    captures = []
    for path in sorted((run / 'raw').glob('*.json')):
        record = json.loads(path.read_text())
        captures.append({'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        for evidence in (record.get('response') or {}).get('evidence', []):
            rows.append({'source_type': evidence.get('source_type'), 'id': evidence.get('chunk_id') or evidence.get('record_id'),
                         'source_family': evidence.get('source_family'), 'locator': evidence.get('locator') or evidence.get('page'),
                         'version': evidence.get('version'), 'reference_end': evidence.get('valid_until') or evidence.get('reference_period_end'),
                         'payload': evidence, 'source_url': evidence.get('source_endpoint')})
    observed = {}
    for criterion in spec['evidence_requirements']:
        matched = [row for row in rows if any(match(row, s) for s in criterion['selectors'])]
        groups = {str(field(row, criterion['distinct_by'])) for row in matched} if criterion.get('distinct_by') else {str(row.get('id')) for row in matched}
        passed = len(groups) >= criterion.get('minimum_distinct', 1)
        observed[criterion['id']] = {'status': 'DEMONSTRATED' if passed else 'NOT_DEMONSTRATED',
                                    'layer': criterion['layer'], 'definition': criterion['definition'],
                                    'matching_rows': len(matched), 'distinct_entities': len(groups),
                                    'witnesses': [{'id': row.get('id'), 'locator': row.get('locator'),
                                                   'source_type': row.get('source_type'), 'source_family': row.get('source_family')}
                                                  for row in matched[:3]]}
    layers = {}
    for layer in spec['layers']:
        tests = [o for o in observed.values() if o['layer'] == layer]
        layers[layer] = sum(t['status'] == 'DEMONSTRATED' for t in tests) / len(tests)
    return {'version': VERSION, 'status': 'MEASURED_LOWER_BOUND', 'hub_commit': commit,
            'requirements_sha256': digest(spec), 'scorecard_sha256': digest(scorecard),
            'snapshot_receipts': receipts, 'capture_receipts_sha256': digest(captures),
            'criteria': observed, 'layers': layers,
            'limitations': ['Missing typed witnesses mean not demonstrated; they do not prove the source landscape is empty.',
                           'Coverage is a lower bound for the fixed professional requirements, not a percentage of every Mali document.',
                           'A historical observation remains useful for its period; it does not demonstrate current operational readiness.']}


def conversation_coverage(card):
    if not card or card.get('completed_sequences') != card.get('suite_sequences') or card.get('suite_sequences', 0) < 20:
        return None, {}
    suite = json.loads((REQUIREMENTS.parent / 'conversation_v1.json').read_text())
    freeze = json.loads((REQUIREMENTS.parent / 'conversation_freeze_manifest.json').read_text())
    if card.get('suite_sha256') != freeze['suite_sha256'] or digest(suite) != freeze['suite_sha256']:
        raise ValueError('Conversation coverage needs the original frozen suite')
    checks = card['checks']
    slots = {}
    for criterion in requirements()['conversation_requirements']:
        sequences = [s for s in suite['sequences'] if s['category'] in criterion['categories']]
        ids = {s['id'] for s in sequences}
        selected = [c for c in checks if c['sequence_id'] in ids]
        # A capability is demonstrated only if every expected turn succeeds.
        # This deliberately separates topic breadth from average reliability.
        expected = sum(len(s['turns']) - 1 for s in sequences)
        slots[criterion['id']] = bool(expected and len(selected) == expected and all(
            c['correct_interpretation'] and c['grounding_proxy_pass'] for c in selected))
    return sum(slots.values()) / len(slots), slots


def professional_inputs(card, run, old, conversation=None):
    if not (Path(run) / 'raw').exists():
        saved = old.get('professional_capability')
        path = Path(run) / 'professional_radar_inputs.json'
        if saved is None and path.exists():
            saved = json.loads(path.read_text())
        if saved:
            coverage = saved.get('coverage', {})
            if (coverage.get('scorecard_sha256') != digest(card) or coverage.get('version') != VERSION
                    or coverage.get('requirements_sha256') != digest(requirements())
                    or coverage.get('hub_commit') != card['run_manifest']['hub_commit']):
                raise ValueError('Exported professional inputs do not match scorecard, requirements or commit')
            # Recompute only the separately supplied, commit-verified full
            # conversation suite; never reconstruct evidence breadth from an
            # export without its original captures/provenance.
            if conversation is not None:
                value = json.loads(json.dumps(saved))
                value['conversation_coverage'], value['conversation_requirements'] = conversation_coverage(conversation)
                return value
            return saved
        return {'coverage': {'version': VERSION, 'status': 'UNAVAILABLE',
                             'reason': 'Original captures or bound professional aggregate inputs required'},
                'conversation_coverage': None, 'conversation_requirements': {},
                'assessable_fraction': None, 'availability': None,
                'performance_cells': {f'{m}/{s}': {'attempts':0} for m in ['quick','balanced','deep'] for s in ['cold','warm']}}
    if conversation is None and (Path(run) / 'conversation_scorecard.json').exists():
        conversation = json.loads((Path(run) / 'conversation_scorecard.json').read_text())
    coverage = inventory(run, card, old)
    turn_coverage, turn_checks = conversation_coverage(conversation)
    performance_cells = {}
    for mode in ['quick', 'balanced', 'deep']:
        for state in ['cold', 'warm']:
            cohort = []
            for path in sorted((Path(run) / 'raw').glob('*.json')):
                r = json.loads(path.read_text())
                # Explicit controlled application/cache state, never inferred
                # from provider token caching or first-call order.
                if r.get('request_payload', {}).get('analysis_mode') == mode and r.get('measurement_state') == state:
                    cohort.append(r)
            performance_cells[f'{mode}/{state}'] = {
                'attempts': len(cohort), 'client_median_seconds': statistics.median([r['client_seconds'] for r in cohort]) if cohort else None,
                'success_rate': sum(r['ok'] for r in cohort) / len(cohort) if cohort else None}
    return {'coverage': coverage, 'conversation_coverage': turn_coverage,
            'conversation_requirements': turn_checks,
            'assessable_fraction': card.get('claim_assessment_coverage', {}).get('value'),
            'availability': card.get('availability', {}).get('successes', 0) / sum(card.get('availability', {}).values()) if sum(card.get('availability', {}).values()) else None,
            'performance_cells': performance_cells}


def scores(old_scores, measured, extra):
    spec = requirements()
    layers = extra['coverage'].get('layers')
    result, components = {}, {}
    for axis, definition in spec['axes'].items():
        quality = old_scores[definition.get('quality_axis', axis)]
        coverage = statistics.mean([layers[l] for l in definition['layers']]) if layers and definition['layers'] else None
        if axis == 'Evidence reliability & completeness':
            assessable = extra['assessable_fraction']
            quality = quality * assessable if quality is not None and assessable is not None else None
        elif axis == 'Conversational ability':
            coverage = extra['conversation_coverage']
        elif axis == 'Performance':
            cells = extra['performance_cells']
            # All six cells are required. Cold/warm user experience was not
            # captured historically, so that axis is unavailable for that run.
            if any(not c['attempts'] for c in cells.values()):
                quality = None
            else:
                quality = 100 * statistics.mean(min(1, spec['latency_targets_seconds'][key.split('/')[0]] / c['client_median_seconds']) * c['success_rate'] for key, c in cells.items())
                quality = quality * statistics.mean([measured['route_efficiency'], measured['call_efficiency']]) if measured.get('route_efficiency') is not None and measured.get('call_efficiency') is not None else None
        elif axis == 'Cost efficiency':
            # Cheap queries cannot exceed quality-adjusted usefulness. V1's
            # efficiency saturates at 100, then this independent cap applies.
            usefulness = old_scores['Analytical usefulness']
            quality = min(quality, usefulness) if quality is not None and usefulness is not None else None
        availability = extra['availability']
        result[axis] = round(quality * coverage * availability, 2) if quality is not None and coverage is not None and availability is not None else None
        components[axis] = {'quality_points': quality, 'demonstrated_coverage_fraction': coverage,
                            'availability_fraction': availability, 'score': result[axis]}
    return result, components


def freeze():
    spec = json.loads(REQUIREMENTS.read_text())
    path = REQUIREMENTS.with_name('professional_requirements_v2_1.freeze.json')
    if path.exists():
        raise ValueError('Requirements already frozen; create a new version instead')
    write_json(path, {'version': VERSION, 'frozen_at': now(), 'requirements_sha256': digest(spec),
                      'purpose': 'Professional capability reporting calibration; original regression/acceptance benchmarks unchanged.'})
