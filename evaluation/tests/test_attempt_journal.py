import json
from unittest.mock import Mock
from unittest.mock import patch
import pytest
from evaluation.runner import journaled_request
from evaluation.scorecard import distribution


def test_interruption_is_retained_without_retry_or_fabricated_measurement(tmp_path):
    case={'question':'Synthetic needs question','difficulty':'balanced'}
    first=Mock(side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        journaled_request(tmp_path,'CASE--0',case,'https://example.invalid',first)
    pending=json.loads((tmp_path/'attempt_journal/CASE--0.json').read_text())
    retry=Mock()
    interrupted=journaled_request(tmp_path,'CASE--0',case,'https://example.invalid',retry)
    retry.assert_not_called()
    assert interrupted['started_at']==pending['started_at']
    assert interrupted['ok'] is False and interrupted['cost_unknown'] is True
    assert interrupted['client_seconds'] is None and interrupted['response'] is None
    with pytest.raises(ValueError):
        journaled_request(tmp_path,'CASE--0',{'question':'Different question','difficulty':'deep'},'https://example.invalid',retry)


def test_unknown_latency_is_explicit_and_does_not_become_a_zero():
    result=distribution([None,10,20])
    assert result['n']==2 and result['missing']==1
    assert result['median']==15 and result['total']==30
    assert distribution([None])['median'] is None


def test_legacy_interruption_reaches_cost_ledger_and_radar_without_erasing_observed_cost(tmp_path):
    from evaluation.common import write_json, digest
    from evaluation.runner import capture_telemetry
    from evaluation.scorecard import summarize
    from evaluation.radar import inputs
    response={'answer':'Evidence remains incomplete.', 'evidence':[],
              'metrics':{'route':'deep_research','server_seconds':10,
                         'estimated_usd':.003,'research_api_usage':{'calls':[]}}}
    record={'case_id':'JOIN02','repetition':0,'ok':True,'response':response,
            'response_hash':digest(response),'client_seconds':11,
            'started_at':'2026-10-06T00:00:00Z',
            'request_payload':{'analysis_mode':'deep'}}
    record['telemetry']=capture_telemetry(record)
    write_json(tmp_path/'raw/JOIN02--0.json',record)
    write_json(tmp_path/'run_manifest.json',{'hub_commit':'a'*40,
               'capture_interruption_cost_unknown':True,
               'completed_at':'2026-10-06T00:01:00Z'})
    with patch('evaluation.radar.generate'):
        card=summarize(tmp_path,'frozen')
    assert card['hub_cost_is_lower_bound'] is True
    assert card['hub_estimated_cost_usd']==.003
    measured=inputs(card,tmp_path)
    assert measured['complex_priced'] is False
    assert measured['complex_median_usd'] is None
    assert measured['performance_measurement_complete'] is False
