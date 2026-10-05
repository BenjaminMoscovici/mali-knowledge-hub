"""Lossless, deterministic packing of repeated structured evidence fields.

No observations are dropped, rounded, or aggregated. Original evidence stays
unchanged. The bounded cache contains source content, never conversation state.
"""
from functools import lru_cache
import json
import re

TABLE = '__mkh_table'
MISSING = '__mkh_missing_fields'


def partition(rows):
    common, rest = {}, [dict(row) for row in rows]
    keys = set.intersection(*(set(row) for row in rows))
    for key in sorted(keys):
        values = [row[key] for row in rows]
        if all(value == values[0] for value in values):
            common[key] = values[0]
            for row in rest:
                row.pop(key)
        elif all(isinstance(value, dict) for value in values):
            nested, differences = partition(values)
            if nested:
                common[key] = nested
                for row, difference in zip(rest, differences):
                    row[key] = difference
    return common, rest


def encode(value):
    if isinstance(value, list):
        if len(value) >= 3 and all(isinstance(row, dict) for row in value):
            shared, rows = partition(value)
            if shared:
                return {TABLE: {'shared_fields': encode(shared),
                                'rows': [encode(row) for row in rows]}}
        return [encode(row) for row in value]
    if isinstance(value, dict):
        missing = [key for key, item in value.items() if item is None]
        if len(missing) >= 3:
            return {**{key: encode(item) for key, item in value.items() if item is not None},
                    MISSING: missing}
        return {key: encode(item) for key, item in value.items()}
    return value


def merge(shared, row):
    result = dict(shared)
    for key, value in row.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def decode(value):
    if isinstance(value, list):
        return [decode(row) for row in value]
    if isinstance(value, dict):
        if TABLE in value:
            table = value[TABLE]
            shared = decode(table['shared_fields'])
            return [merge(shared, decode(row)) for row in table['rows']]
        result = {key: decode(item) for key, item in value.items() if key != MISSING}
        result.update({key: None for key in value.get(MISSING, [])})
        return result
    return value


def has_reserved(value):
    if isinstance(value, dict):
        return any(str(key).startswith('__mkh_') or has_reserved(item)
                   for key, item in value.items())
    return isinstance(value, list) and any(has_reserved(item) for item in value)


def json_ranges(text):
    decoder, position = json.JSONDecoder(), 0
    while position < len(text):
        match = re.search(r'[\[{]', text[position:])
        if not match:
            break
        start = position + match.start()
        try:
            value, size = decoder.raw_decode(text[start:])
        except ValueError:
            position = start + 1
            continue
        yield start, start + size, value
        position = start + size


@lru_cache(maxsize=128)
def compact_text(text):
    parts, cursor, changed = [], 0, False
    for start, end, value in json_ranges(text):
        original = text[start:end]
        if has_reserved(value):
            packed = original
        else:
            encoded = encode(value)
            if decode(encoded) != value:
                raise ValueError('Structured summary failed lossless round-trip')
            packed = json.dumps(encoded, ensure_ascii=False, separators=(',', ':'))
        if len(packed) >= len(original):
            packed = original
        changed |= packed != original
        parts.extend((text[cursor:start], packed))
        cursor = end
    parts.append(text[cursor:])
    return ''.join(parts), changed


def exact_sentences(text):
    protected = [(start, end) for start, end, _ in json_ranges(text)]
    cursor = 0
    for match in re.finditer(r'(?<=[.!?])\s+(?=[A-ZÀ-Ö])|\n\s*\n', text):
        if any(start <= match.start() < end for start, end in protected):
            continue
        yield text[cursor:match.end()]
        cursor = match.end()
    yield text[cursor:]
