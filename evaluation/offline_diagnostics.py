"""Replay currency checks and actual packaged DTM retrieval without model calls."""
import argparse
import json
from collections import Counter
from pathlib import Path
from .common import ROOT, load_cases, write_json, now
from .validators import VERSION
from money_integrity import validate as money


def replay(runs, output):
    output = Path(output)
    entries = []
    for label, directory in runs:
        rows, counter = [], Counter()
        for path in sorted((Path(directory) / 'raw').glob('*.json')):
            record = json.loads(path.read_text())
            response = record.get('response') or {}
            audit = money(response.get('answer', ''), response.get('evidence', []))
            status = ('REQUEST_FAILED' if not record['ok'] else 'FAIL' if audit['explicit_pair_mismatches'] else
                      'PARTIAL_PAIR_CHECK_PASS' if audit['checked_pairs'] else 'UNASSESSED')
            counter[status] += 1
            rows.append({'case_id': record['case_id'], 'repetition': record['repetition'],
                         'response_hash': record['response_hash'], 'status': status, 'audit': audit})
        entries.append({'label': label, 'attempts': len(rows), 'currency_checks': dict(counter)})
        write_json(output / f'{label}-currency.json', {'method': 'Conservative explicit amount/currency pairs within original cited paragraphs; no model, no conversion or full financial semantic certification.',
                                                     'validator_version': VERSION, 'rows': rows})
    from operational_sources import retrieve_operational_evidence
    case = next(c for c in load_cases('frozen') if c['id'] == 'NEED03')
    evidence = retrieve_operational_evidence(case['question'])
    write_json(output / 'need03-retrieval-proof.json', {'case_id': 'NEED03', 'question': case['question'],
               'method': 'Actual local packaged DTM retrieval; synthesis not executed.',
               'evidence': [{k:e.get(k) for k in ['record_id','locator','source_family','geographic_scope','content']} for e in evidence]})
    summary = {'generated_at': now(), 'validator_version': VERSION, 'currency_replay': entries,
               'model_calls': 0, 'external_calls': 0,
               'limitations': 'Offline repair evidence is not a new qualified candidate benchmark. Original captures and v1 scorecards unchanged.'}
    write_json(output / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', action='append', required=True, help='label=run directory')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    print(json.dumps(replay([item.split('=', 1) for item in args.run], args.output)))
