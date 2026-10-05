"""Independent checks of referents against immutable preceding turns.

Conversation text supplies lookup identities, never proof of a project's status.
Missing identities remain unknown rather than becoming a successful subset check.
"""
import re

VERSION = 'conversation-evaluator-2.2'


def intent_matches(pattern, text):
    # Frozen expectations retain their original hash. Accept the equivalent
    # French adjective used by a correct answer; avoid male matching female.
    if pattern == 'hommes|male':
        pattern = r'\b(?:hommes|male|masculin(?:e|s|es)?)\b'
    return bool(re.search(pattern, text, re.I))


def project_ids(answer):
    ids = set(re.findall(r'\b(?:(?:project\s+)?ID|Project)\s*[:#]?\s*(\d+)\b', answer, re.I))
    # Recover only the explicitly labelled Project ID column. Dates, amounts
    # and unrelated numeric tables must not become project identities.
    lines = answer.splitlines()
    for index, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        columns = [i for i, c in enumerate(cells) if re.fullmatch(r'Project\s+ID', c, re.I)]
        if not columns or '|' not in line:
            continue
        for row in lines[index + 1:]:
            if '|' not in row:
                break
            values = [c.strip() for c in row.strip().strip('|').split('|')]
            for column in columns:
                if column < len(values) and re.fullmatch(r'\d+', values[column]):
                    ids.add(values[column])
    return ids


def validate_context(sequence, index, preceding_answer, answer):
    question = sequence['turns'][index]
    checks = []
    if re.search(r'\b(?:of those|of these|those projects|these projects)\b', question, re.I):
        previous, current = project_ids(preceding_answer), project_ids(answer)
        # An answer must address the selected subset explicitly. A status-free
        # response or one with no recoverable identifiers cannot establish this.
        status = 'unknown' if not previous or not current else ('pass' if current <= previous else 'fail')
        checks.append({'id': 'project_subset_preserved', 'status': status,
                       'prior_ids': sorted(previous), 'answer_ids': sorted(current),
                       'unexpected_ids': sorted(current - previous)})
    if re.search(r'\b(?:them|those|these)\b', question, re.I):
        prior_question = sequence['turns'][index - 1]
        for entity in ['cercle', 'commune', 'municipalit']:
            if re.search(r'\b' + entity, prior_question, re.I):
                checks.append({'id': 'administrative_referent_preserved',
                               'status': 'pass' if re.search(r'\b' + entity, answer, re.I) else 'fail',
                               'expected_entity': entity})
                break
    return checks
