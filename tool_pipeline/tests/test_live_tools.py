"""External-tool contracts with recorded HTTP responses; no API credits required."""

import asyncio
import io
import json
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest

from speech_contracts import RunRequest, RunSettings
from tool_pipeline import live_tools
from tool_pipeline.pipeline.context import resolve_oracle
from tool_pipeline.pipeline.results import RunState
from tool_pipeline.telemetry import TraceRecorder


def test_clock_returns_one_instant_in_server_timezone_and_utc():
    before = datetime.now(timezone.utc)
    result = live_tools.server_datetime_result()
    after = datetime.now(timezone.utc)
    instant = datetime.fromisoformat(result['evidence']['utc'])
    assert before <= instant <= after
    assert instant == datetime.fromisoformat(result['evidence']['server_local'])
    assert result['evidence']['timezone']
    assert result['sources'] == ['system://server-clock']
    assert 'UTC date and time:' in result['facts']


def test_search_preserves_evidence_but_bounds_injected_excerpts(monkeypatch, capsys):
    monkeypatch.setenv('EXA_API_KEY', 'test-key-not-a-secret')
    results = [{'title': f'Source {i}', 'url': f'https://source{i}.example/article',
                'publishedDate': '2026-11-02', 'highlights': ['ö' * 400]} for i in range(3)]
    payload = {'results': results, 'requestId': 'request-1', 'costDollars': {'total': 0.007}}
    calls = []

    def respond(request, timeout):
        calls.append(request)
        assert timeout == 10
        assert request.get_header('X-api-key') == 'test-key-not-a-secret'
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(live_tools, 'urlopen', respond)
    result = live_tools.ExaSearch().search('Who is the current prime minister of Sweden?')
    assert len(calls) == 1
    assert json.loads(calls[0].data)['contents'] == {'highlights': True}
    assert len(result['facts'].encode()) <= 540
    assert len(result['sources']) == 3
    assert result['evidence']['results'][0]['excerpt'] == 'ö' * 400
    assert result['evidence']['request_id'] == 'request-1'
    assert result['evidence']['cost_dollars'] == {'total': 0.007}
    assert 'test-key-not-a-secret' not in json.dumps(result)
    log = capsys.readouterr().out
    entries = [json.loads(line) for line in log.splitlines()]
    assert [entry['event'] for entry in entries] == ['exa.started', 'exa.request', 'exa.response', 'exa.completed']
    assert entries[1]['body']['query'] == 'Who is the current prime minister of Sweden?'
    assert entries[2]['body'] == payload
    assert entries[2]['http_status'] == 200
    assert entries[3]['facts'] == result['facts']
    assert entries[3]['elapsed_ms'] == result['evidence']['elapsed_ms']
    assert all('at' in entry for entry in entries)
    assert 'test-key-not-a-secret' not in log


@pytest.mark.parametrize('status,message', [(401, 'key was rejected'), (402, 'budget exhausted'), (429, 'rate limit')])
def test_search_reports_provider_errors_without_retry_or_credentials(monkeypatch, capsys, status, message):
    monkeypatch.setenv('EXA_API_KEY', 'test-key-not-a-secret')
    calls = []

    def fail(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, status, 'private provider detail', {}, None)

    monkeypatch.setattr(live_tools, 'urlopen', fail)
    with pytest.raises(RuntimeError, match=message) as error:
        live_tools.ExaSearch().search('current events')
    assert len(calls) == 1
    assert 'private provider detail' not in str(error.value)
    log = capsys.readouterr().out
    entries = [json.loads(line) for line in log.splitlines()]
    assert entries[-2]['http_status'] == status
    assert entries[-1]['event'] == 'exa.failed'
    assert entries[-1]['elapsed_ms'] >= 0
    assert 'test-key-not-a-secret' not in log
    assert 'private provider detail' not in log


def test_search_requires_credentials_and_usable_evidence(monkeypatch):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='EXA_API_KEY'):
        live_tools.ExaSearch().search('current events')
    monkeypatch.setenv('EXA_API_KEY', 'test-key-not-a-secret')
    monkeypatch.setattr(live_tools, 'urlopen', lambda *a, **k: io.BytesIO(b'{"results": []}'))
    with pytest.raises(LookupError, match='no usable excerpts'):
        live_tools.ExaSearch().search('current events')


def test_clock_oracle_is_read_after_delay_and_uses_normal_context(monkeypatch):
    import tool_pipeline.pipeline.context as context
    order = []

    async def delay(seconds):
        order.append(('delay', seconds))

    def clock():
        order.append(('clock',))
        return {'facts': 'Server time 12:34 UTC', 'sources': ['system://server-clock'], 'evidence': {'utc': 'fixture'}}

    monkeypatch.setattr(context.asyncio, 'sleep', delay)
    monkeypatch.setattr(context, 'server_datetime_result', clock)
    request = RunRequest('B2', '/input.wav', settings=RunSettings(oracle_delay_ms=1000), oracle_mode='server_clock')
    state = RunState()
    trace = TraceRecorder()
    result = asyncio.run(resolve_oracle(request, state, trace))
    assert order == [('delay', 1.0), ('clock',)]
    assert state.tool_result == result
    assert result['evidence']['utc'] == 'fixture'
    assert result['facts'] == 'Server time 12:34 UTC'
    for condition in ('B0', 'B1'):
        payload = RunRequest(condition, '/input.wav').to_payload()
        assert 'oracle_mode' not in payload
        with pytest.raises(ValueError, match='exclusive to B2'):
            RunRequest.from_dict({**payload, 'oracle_mode': 'server_clock'})

