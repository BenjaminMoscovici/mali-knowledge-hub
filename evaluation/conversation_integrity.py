"""Independent checks of referents against immutable preceding turns.

Conversation text supplies lookup identities, never proof of a project's status.
Missing identities remain unknown rather than becoming a successful subset check.
"""
import re

VERSION = 'conversation-evaluator-2.0'


def project_ids(answer):
    return set(re.findall(r'\b(?:project\s+)?ID\s*[:#]?\s*(\d+)\b', answer, re.I))


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
