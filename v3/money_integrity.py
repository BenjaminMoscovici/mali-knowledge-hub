"""Conservative original-currency checks; never performs currency conversion.

Only explicit amount/currency pairs with the same normalized numeric quantity
are compared, within a cited paragraph. Unmatched facts are unassessed, not
asserted correct. Amounts in different financial stages require semantic review.
"""
import re
from decimal import Decimal, InvalidOperation

VERSION = 'explicit-money-integrity-1.0'
TOKEN = r'(?:USD|US\$|EUR|€|XOF|FCFA|CFA)'
NUMBER = r'\d+(?:[\s\u00a0\u202f]\d{3})*(?:[.,]\d+)?'
SCALE = r'(?:million(?:s)?|milliard(?:s)?|billion(?:s)?|m\b|bn\b)'
PAIR = re.compile(rf'(?P<prefix>{TOKEN})\s*(?P<n1>{NUMBER})\s*(?P<s1>{SCALE})?|(?P<n2>{NUMBER})\s*(?P<s2>{SCALE})?\s*(?P<suffix>{TOKEN})', re.I)


def amounts(text):
    result = []
    for match in PAIR.finditer(text or ''):
        before = text[max(0, match.start()-55):match.start()]
        after = text[match.end():match.end()+55]
        # Explicit corrections can mention a wrong currency without asserting
        # it. Leave quoted/negated pairs unassessed; never withhold that answer.
        if re.search(r'\b(?:not|not in|rather than|instead of|pas|pas en|non)\s*[\*\"\x27]*$', before, re.I) or re.match(r'[\*\"\x27]*\s+(?:is|was|serait|est)\s+(?:incorrect|erroneous|wrong|erron[eé])', after, re.I):
            continue
        raw = match.group('n1') or match.group('n2')
        number = re.sub(r'[\s\u00a0\u202f]', '', raw)
        # A single comma with three trailing digits is ambiguous (decimal vs
        # thousands); leave it unassessed instead of guessing a monetary unit.
        if ',' in number and '.' not in number and len(number.rsplit(',', 1)[1]) == 3:
            continue
        try:
            quantity = Decimal(number.replace(',', '.'))
        except InvalidOperation:
            continue
        scale = (match.group('s1') or match.group('s2') or '').lower()
        quantity *= Decimal(1000000000 if scale.startswith(('bn','billion','milliard')) else 1000000 if scale else 1)
        token = (match.group('prefix') or match.group('suffix')).upper()
        currency = 'USD' if token in {'USD','US$'} else 'EUR' if token in {'EUR','€'} else 'XOF'
        result.append({'amount': str(quantity.normalize()), 'currency': currency, 'quote': match.group(0)})
    return result


def validate(answer, evidence):
    source = {e['evidence_id']: amounts((e.get('content') or '') + '\n' + (e.get('source_excerpt') or '')) for e in evidence}
    checked, mismatches, unassessed = [], [], []
    for paragraph in re.split(r'\n\s*\n', answer or ''):
        cited = set(re.findall(r'\bE\d{2,}\b', paragraph))
        for actual in amounts(paragraph):
            witnesses = [(eid, fact) for eid in cited for fact in source.get(eid, []) if fact['amount'] == actual['amount']]
            if not witnesses:
                unassessed.append(actual)
                continue
            currencies = {fact['currency'] for _, fact in witnesses}
            row = actual | {'cited_ids': sorted(cited), 'source_currencies': sorted(currencies)}
            if actual['currency'] not in currencies:
                mismatches.append(row)
            else:
                checked.append(row)
    return {'version': VERSION, 'explicit_pair_mismatches': mismatches, 'checked_pairs': checked,
            'unassessed_pairs': unassessed, 'valid': not mismatches,
            'limitation': 'Checks same-amount explicit currency pairs only; no claim entailment, conversion or financial-stage certification.'}
