"""Attempt-preserving performance cohorts; expected difficulty defines complex.

A fast but incorrectly routed answer cannot leave the complex denominator.
Cold/warm state is never inferred from request order or cached provider tokens.
"""
import statistics


def summarize(records, cases, judgments):
    from .scorecard import distribution
    selections = {
        'complex': [r for r in records if cases[r['case_id']]['difficulty'] in {'balanced', 'deep'}],
        'joined_analysis': [r for r in records if cases[r['case_id']]['category'] == 'joined_analysis'],
    }
    # Per-case repeated cohorts support the requested joined Mopti comparison
    # without special product logic or replacing a failed attempt.
    for cid in sorted({r['case_id'] for r in selections['complex']}):
        selections['case/'+cid] = [r for r in records if r['case_id'] == cid]
    outputs = {}
    for name, rows in selections.items():
        successful = [r for r in rows if r['ok']]
        identities = {(r['case_id'], r['repetition']) for r in rows}
        scores = [j['result']['scores']['decision_usefulness'] for _, j in judgments
                  if (j['case_id'], j['repetition']) in identities
                  and j['result']['scores']['decision_usefulness'] is not None]
        result = {'attempts': len(rows), 'successes': len(successful),
                  'failures': len(rows)-len(successful),
                  'client_attempt_latency_seconds': distribution([r['client_seconds'] for r in rows]),
                  'server_success_latency_seconds': distribution([r['telemetry']['server_seconds'] for r in successful
                                                                  if r['telemetry'].get('server_seconds') is not None]),
                  'decision_usefulness_mean': statistics.mean(scores) if scores else None,
                  'decision_usefulness_judged_attempts': len(scores),
                  'cost_unknown_attempts': sum(not r['ok'] or r['telemetry'].get('estimated_usd') is None
                                               or bool(r['telemetry'].get('unpriced_calls')) for r in rows)}
        for field in ['input_tokens', 'output_tokens', 'estimated_usd', 'synthesis_seconds']:
            values = [r['telemetry'][field] for r in successful if r['telemetry'].get(field) is not None]
            result[field] = distribution(values)
        for field, endpoint in [('model_calls', 'responses'), ('embedding_calls', 'embeddings')]:
            result[field] = distribution([sum(c.get('endpoint') == endpoint for c in r['telemetry'].get('model_calls', []))
                                          for r in successful])
        outputs[name] = result
    return {'version': 'expected-difficulty-cohorts-1.0',
            'complex_definition': 'Frozen expected difficulty balanced or deep, regardless of observed route.',
            'limitations': ['Server latency, tokens and price distributions are for successful attempts with observed values; all client attempts and failure/unknown-cost counts remain explicit.',
                           'Independent evaluator cost is separate from Hub cost. Provider contention and caching can affect estimates; these are not invoices.',
                           'No cold/warm or deployment latency is inferred. Compare only matching immutable case/repetition configurations and protocols.'],
            'cohorts': outputs}
