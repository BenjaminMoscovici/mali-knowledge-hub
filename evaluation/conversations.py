"""Run frozen actual multi-turn exchanges and deterministic interpretation checks."""
import argparse
import json
import re
from pathlib import Path
from .common import digest, now, write_json
from .runner import request_case, capture_telemetry
from .scorecard import distribution
from .validators import contains_number

ROOT = Path(__file__).parent / 'benchmarks'
CLARIFY = r'which (?:place|metric|measure|project|entity|indicator|answer)|what (?:place|metric|measure|project|indicator) do you mean|please (?:specify|clarify)|do you mean|de quel|quel(?:le)? (?:lieu|mesure|projet|indicateur)|pr[eé]cisez|voulez.vous parler|souhaitez.vous|pourriez.vous pr[eé]ciser'


def run(args):
    suite = json.loads((ROOT / 'conversation_v1.json').read_text())
    freeze = json.loads((ROOT / 'conversation_freeze_manifest.json').read_text())
    assert digest(suite) == freeze['suite_sha256'], 'Frozen conversation suite modified'
    out = Path(args.output)
    manifest = {'suite_sha256': digest(suite), 'hub_commit': args.hub_commit,
                'endpoint': args.base, 'started_at': now(), 'automatic_retries': 0}
    existing = out / 'run_manifest.json'
    if existing.exists():
        old = json.loads(existing.read_text())
        for key in ['suite_sha256', 'hub_commit', 'endpoint']:
            assert old[key] == manifest[key], 'Cannot resume different run'
        manifest = old
    else:
        write_json(existing, manifest)
    for sequence in suite['sequences']:
        if args.ids and sequence['id'] not in args.ids.split(','):
            continue
        history = []
        for index, question in enumerate(sequence['turns']):
            path = out / 'raw' / f'{sequence["id"]}--{index}.json'
            if path.exists():
                record = json.loads(path.read_text())
            else:
                record = request_case({'question': question, 'difficulty': sequence['difficulty'],
                                       'prior_messages': history}, args.base)
                record.update(sequence_id=sequence['id'], turn=index,
                              sequence_hash=digest(sequence), response_hash=digest(record['response']))
                record['telemetry'] = capture_telemetry(record)
                write_json(path, record)
                print(json.dumps({'sequence': sequence['id'], 'turn': index, 'ok': record['ok'],
                                  'seconds': record['telemetry']['server_seconds']}), flush=True)
            if not record['ok']:
                break  # A failed sequence is retained, never replaced or continued on fake context.
            response = record['response']
            history += [{'role': 'user', 'content': question,
                         'standalone_question': response['standalone_question']},
                        {'role': 'assistant', 'content': response['answer'],
                         'evidence_refs': response.get('evidence', [])}]
    manifest['completed_at'] = now()
    write_json(existing, manifest)
    return summarize(out)


def summarize(out):
    out = Path(out)
    suite = json.loads((ROOT / 'conversation_v1.json').read_text())
    checks, attempts = [], []
    for sequence in suite['sequences']:
        for index in range(len(sequence['turns'])):
            path = out / 'raw' / f'{sequence["id"]}--{index}.json'
            if not path.exists():
                continue
            r = json.loads(path.read_text()); attempts.append(r)
            if not index:
                continue
            expected = sequence['followup_expectations'][index - 1]
            response = r.get('response') or {}
            answer = response.get('answer', '')
            text = response.get('standalone_question', '') + '\n' + answer
            clarify = bool(response.get('metrics', {}).get('clarification_required') or re.search(CLARIFY, answer, re.I))
            grounded = bool(response.get('evidence')) and bool(re.search(r'\[E\d+', answer))
            intent = all(re.search(p, text, re.I) for p in expected['intent_patterns'])
            numeric = all(contains_number(answer, n) for n in expected['answer_numbers'])
            correct = r['ok'] and (clarify if expected['clarification_required'] else not clarify and intent)
            checks.append({'sequence_id': sequence['id'], 'turn': index, 'correct_interpretation': bool(correct),
                           'expected_clarification': expected['clarification_required'],
                           'clarification_observed': clarify, 'numeric_check': numeric,
                           'grounded_required': expected['grounded_answer_required'], 'grounded': grounded,
                           'grounding_proxy_pass': not expected['grounded_answer_required'] or grounded and numeric,
                           'response_hash': r['response_hash']})
    straightforward = [c for c in checks if not c['expected_clarification']]
    factual = [c for c in checks if c['grounded_required']]
    success = [r for r in attempts if r['ok']]
    result = {'method': 'Deterministic intent/clarification and explicit-number checks; grounding proxy is evidence presence plus citations and numbers, not full semantic entailment.',
              'suite_sequences': len(suite['sequences']), 'completed_sequences': sum(all((out / 'raw' / f'{s["id"]}--{i}.json').exists() for i in range(len(s['turns']))) for s in suite['sequences']),
              'attempts': len(attempts), 'failed_attempts': len(attempts) - len(success),
              'followups': len(checks), 'correct_interpretation_rate': sum(c['correct_interpretation'] for c in checks) / len(checks) if checks else None,
              'unnecessary_clarification_rate': sum(c['clarification_observed'] for c in straightforward) / len(straightforward) if straightforward else None,
              'factual_grounding_proxy_rate': sum(c['grounding_proxy_pass'] for c in factual) / len(factual) if factual else None,
              'latency_seconds': distribution([r['telemetry']['server_seconds'] for r in success if r['telemetry']['server_seconds'] is not None]),
              'followup_latency_seconds': distribution([r['telemetry']['server_seconds'] for r in success if r['turn'] and r['telemetry']['server_seconds'] is not None]),
              'input_tokens': distribution([r['telemetry']['input_tokens'] for r in success]),
              'output_tokens': distribution([r['telemetry']['output_tokens'] for r in success]),
              'model_calls': sum(sum(c['endpoint'] == 'responses' for c in r['telemetry']['model_calls']) for r in success),
              'embedding_calls': sum(sum(c['endpoint'] == 'embeddings' for c in r['telemetry']['model_calls']) for r in success),
              'cost_usd': sum(r['telemetry']['estimated_usd'] or 0 for r in success), 'checks': checks}
    write_json(out / 'scorecard.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--base', default='https://mali-knowledge-hub-v4-test.onrender.com')
    p.add_argument('--hub-commit', required=True)
    p.add_argument('--ids')
    args = p.parse_args()
    print(json.dumps(run(args)))
