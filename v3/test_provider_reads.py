from unittest.mock import Mock
import httpx
import pytest
from provider_reads import execute_read


def test_transport_disconnect_retry_preserves_read_and_bounds_attempts(monkeypatch,capsys):
    monkeypatch.setattr('provider_reads.time.sleep',lambda _:None)
    query=Mock();query.execute.side_effect=[httpx.RemoteProtocolError('private payload'),{'rows':[42]}]
    assert execute_read(query,'match_chunks')=={'rows':[42]}
    assert query.execute.call_count==2
    log=capsys.readouterr().out
    assert 'RemoteProtocolError' in log and 'private payload' not in log
    query.execute.side_effect=httpx.RemoteProtocolError('private payload')
    with pytest.raises(httpx.RemoteProtocolError):execute_read(query,'match_chunks')
    assert query.execute.call_count==4


def test_auth_validation_and_arbitrary_errors_not_retried():
    query=Mock();query.execute.side_effect=ValueError('invalid request')
    with pytest.raises(ValueError):execute_read(query,'read')
    assert query.execute.call_count==1
