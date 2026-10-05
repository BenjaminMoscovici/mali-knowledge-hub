"""Import observed conversation UI answers without inventing API metadata.

The browser runner captures only actual visible answers, their source drawers,
and the application's public console telemetry. It never sends expectations.
Paired runs must use this same protocol; API-only fields remain unavailable.
"""
import argparse
import json
from pathlib import Path
from .common import digest, now, write_json
from .conversations import ROOT, summarize
from .runner import capture_telemetry


def import_conversation(source, output, hub_commit):
    observed = json.loads(Path(source).read_text())
    suite = json.loads((ROOT / 'conversation_v1.json').read_text())
    freeze = json.loads((ROOT / 'conversation_freeze_manifest.json').read_text())
    if digest(suite) != freeze['suite_sha256']:
        raise ValueError('Frozen conversation suite modified')
    sequences = {seq['id']: seq for seq in suite['sequences']}
    out = Path(output)
    seen = set()
    for item in observed:
        key = item['sequence_id'], item['turn']
        if key in seen:
            raise ValueError('Duplicate UI capture; do not replace an attempted turn')
        seen.add(key)
        seq = sequences[key[0]]
        question = seq['turns'][key[1]]
        answer = item.get('answer')
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('UI capture has no observed answer')
        response = {'answer': answer, 'evidence': item.get('evidence', []),
                    'metrics': item.get('metrics', {})}
        record = {'sequence_id': key[0], 'turn': key[1], 'ok': True,
                  'http_status': None, 'sequence_hash': digest(seq),
                  'response': response, 'response_hash': digest(response),
                  'request_payload': {'question': question, 'analysis_mode': seq['difficulty']},
                  'client_seconds': item.get('metrics', {}).get('client_seconds'),
                  'captured_at': item['captured_at'], 'ui_capture_hash': digest(item),
                  'capture_method': item['capture_method'],
                  'capture_correction': item.get('capture_correction'),
                  'unavailable_fields': ['standalone_question', 'complete_api_evidence_metadata', 'http_status']}
        record['telemetry'] = capture_telemetry(record)
        path = out / 'raw' / f'{key[0]}--{key[1]}.json'
        if path.exists() and json.loads(path.read_text()) != record:
            raise ValueError('Existing observed turn differs; use a new run directory')
        write_json(path, record)
    write_json(out / 'run_manifest.json', {
        'suite_sha256': digest(suite), 'hub_commit': hub_commit,
        'endpoint': 'https://mali-knowledge-hub-v4-test.onrender.com',
        'measurement_protocol': 'visible-ui-and-public-console-v1',
        'capture_source_sha256': digest(observed), 'imported_at': now(),
        'automatic_retries': 0, 'observed_turns': len(observed),
        'limitations': ['Interpretation checks use visible answers; resolved standalone questions are unavailable.',
                        'Citation and number presence is a grounding proxy, not semantic entailment.',
                        'Source drawers expose only displayed source metadata; unavailable API fields remain unknown.']})
    result = summarize(out)
    result['measurement_protocol'] = 'visible-ui-and-public-console-v1'
    result['limitations'] = json.loads((out / 'run_manifest.json').read_text())['limitations']
    write_json(out / 'scorecard.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--hub-commit', required=True)
    args = parser.parse_args()
    result = import_conversation(args.input, args.output, args.hub_commit)
    print(json.dumps({key: value for key, value in result.items() if key != 'checks'}))
