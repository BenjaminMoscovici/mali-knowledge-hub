"""Lossless packing must preserve nulls, nested fields and evidence scope."""
import copy
import json
from structured_summary import compact_text, decode, encode, json_ranges
from synthesis_context import prepare, serialize


def test_nested_observations_round_trip_without_null_zero_or_precision_loss():
    rows = [{'period': '2026-06/2026-08', 'scope': 'Mopti region; older boundaries',
             'value': value, 'unit': 'people', 'limits': {'flow': False, 'projected': True},
             'missing_a': None, 'missing_b': None, 'missing_c': None}
            for value in (0, 13582, 13002.0)]
    packed = encode(rows)
    assert decode(packed) == rows
    assert '__mkh_table' in packed
    assert '__mkh_missing_fields' in json.dumps(packed)
    assert decode(packed)[0]['value'] == 0
    assert decode(packed)[0]['missing_a'] is None


def test_text_packing_preserves_caveats_and_reserved_source_fields():
    rows = [{'period': '2025-09', 'unit': 'people', 'scope': 'commune', 'value': i}
            for i in range(8)]
    source = 'STOCK, not flow. No approved crosswalk.\n' + json.dumps(rows) + '\nNot people reached.'
    compact, changed = compact_text(source)
    assert changed and len(compact) < len(source)
    assert compact.startswith('STOCK, not flow. No approved crosswalk.\n')
    assert compact.endswith('\nNot people reached.')
    assert decode(next(json_ranges(compact))[2]) == rows
    collision = json.dumps({'__mkh_table': 'original source value', 'value': 0})
    assert compact_text(collision) == (collision, False)


def test_serialization_preserves_every_eid_and_originals_across_versions():
    rows = [{'period': '2025-09', 'unit': 'people', 'scope': 'commune', 'value': i}
            for i in range(6)]
    ledger = [dict(evidence_id=f'E{i:02d}', source_family='DTM', source_type='structured_data',
                   release_id=f'r{i}', locator=f'row {i}', geographic_scope='Socoura commune',
                   geographic_precision='no approved crosswalk', content=json.dumps(rows),
                   source_url='https://example.org/source') for i in (1, 2)]
    original = copy.deepcopy(ledger)
    audit = {}
    packed = serialize(ledger, audit)
    assert ledger == original
    assert audit['structured_summary_ids'] == ['E01', 'E02']
    for token in ('[E01]', '[E02]', 'r1', 'r2', 'row 1', 'row 2', 'no approved crosswalk'):
        assert token in packed
    assert 'https://example.org/source' in serialize(ledger, question='Give original source links')
    encoded = [value for _, _, value in json_ranges(packed) if isinstance(value, dict) and '__mkh_table' in value]
    assert len(encoded) == 2 and all(decode(value) == rows for value in encoded)


def test_same_document_chunk_duplicates_only_with_same_page_and_release():
    item = dict(evidence_id='E01', source_type='knowledge_base_document', source_family='HNRP',
                document_id='d1', release_id='r1', page=12, chunk_id='c1', record_id='c1',
                content='The same exact source paragraph. Not evidence of delivery.')
    ledger = [item, dict(item, evidence_id='E02', chunk_id='c2', record_id='c2'),
              dict(item, evidence_id='E03', page=13), dict(item, evidence_id='E04', release_id='r2')]
    selected, audit = prepare(ledger, 'Compare needs')
    assert [row['evidence_id'] for row in selected] == ['E01', 'E03', 'E04']
    assert audit['duplicate_ids'] == ['E02']


def test_shared_passages_keep_explicit_attribution_and_never_cross_periods():
    caveat = 'These are displacement stocks, never a flow or evidence of assistance delivered; no approved commune crosswalk.'
    rows = [dict(evidence_id=f'E{i:02d}', source_family='DTM', source_type='structured_data',
                 release_id='r1', reference_period_start='2025-09', geographic_scope='Socoura',
                 locator=f'row {i}', content=f'{caveat} Observation {i}: {i * 100} people.')
            for i in range(1, 4)]
    rows.append(dict(rows[0], evidence_id='E04', reference_period_start='2026-09'))
    audit = {}
    text = serialize(rows, audit)
    assert 'applies only to [E01], [E02], [E03]' in text
    assert 'applies only to [E01], [E02], [E03], [E04]' not in text
    assert text.count(caveat) == 2 and audit['shared_exact_passages'] == 1
    for i in range(1, 4):
        assert f'Observation {i}: {i * 100} people.' in text
