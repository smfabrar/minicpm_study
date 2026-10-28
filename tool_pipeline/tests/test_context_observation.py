import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from speech_contracts import RunSettings
from tool_pipeline.audio import read_pcm, write_pcm
from tool_pipeline.models.minicpm import NativeSession
from tool_pipeline.pipeline.observation import observe_context
from tool_pipeline.pipeline.playback import finish_response
from tool_pipeline.telemetry import TraceRecorder


def test_result_ready_during_wait_uses_current_boundary(monkeypatch):
    async def scenario():
        pending = asyncio.get_running_loop().create_future()
        waits = []
        async def wait(seconds):
            waits.append(seconds)
            if not pending.done():
                pending.set_result({'event_id': 'fact', 'facts': 'Room B742'})
        monkeypatch.setattr('tool_pipeline.pipeline.playback.asyncio.sleep', wait)
        native = AsyncMock()
        native.error = None
        await finish_response(native, TraceRecorder(), pending, paced=True, drain_seconds=2)
        calls = native.send.call_args_list
        assert calls[0].kwargs['context']['facts'] == 'Room B742'
        assert len(calls) == 3  # Injection plus the full two-second window.
        assert all(c.kwargs['context'] is None for c in calls[1:])
        assert waits == [1, 1, 1]
    asyncio.run(scenario())


@pytest.mark.parametrize('mode,prefix', [
    ('facts', 'External information for the current request: '),
    ('answer_now', 'Use this result to answer the user now: '),
])
def test_fact_wording_is_sent_and_recorded(tmp_path, mode, prefix):
    async def scenario():
        trace = TraceRecorder()
        native = NativeSession(RunSettings(context_payload_mode=mode), trace, tmp_path)
        native.ws = AsyncMock()
        await native.send(bytes(32000), context={'event_id': 'fact', 'facts': 'Room B742'})
        payload = json.loads(native.ws.send.call_args.args[0])['input']['tool_context']
        assert payload == prefix + 'Room B742'
        recorded = next(e for e in trace.snapshot()['events'] if e['name'] == 'context.payload')
        assert recorded['attributes']['exact_payload'] == payload
    asyncio.run(scenario())


def event(name, seconds, **attributes):
    return {'name': name, 'at_ns': int(seconds * 1e9), 'attributes': attributes}


def test_buffered_audio_is_not_a_new_answer(tmp_path):
    write_pcm(tmp_path / 'speaker_0000.wav', bytes(480), 24000)
    write_pcm(tmp_path / 'speaker_0001.wav', b'\x01\x00' * 240, 24000)
    events = [event('context.submitted', 1, event_id='fact'),
              event('audio.output_emitted', 1.5, chunk=1, duration_ms=10),
              event('native.event', 1.8, event={'type': 'response.output.delta', 'kind': 'text', 'text': 'Old answer'}),
              event('context.evaluated', 2, event_id='fact'),
              event('audio.output_emitted', 3, chunk=2, duration_ms=10)]
    report = observe_context({'events': events}, tmp_path, int(14e9))
    assert report['status'] == 'evaluated_no_new_text'
    assert report['new_text'] == ''
    assert report['audio_chunks'] == 1
    assert report['observation_ms'] == 12000
    assert report['spoken_correctness'] == 'requires_listening_review'
    assert read_pcm(tmp_path / report['output_audio'], 24000) == b'\x01\x00' * 240


def test_new_text_and_missing_ack_are_distinct(tmp_path):
    events = [event('context.submitted', 1, event_id='fact')]
    assert observe_context({'events': events}, tmp_path, None)['status'] == 'not_evaluated'
    events.append(event('context.evaluated', 2, event_id='other'))
    assert observe_context({'events': events}, tmp_path, None)['status'] == 'not_evaluated'
    events.extend([event('context.evaluated', 3, event_id='fact'),
                   event('native.event', 4, event={'type': 'response.output.delta', 'kind': 'text', 'text': 'Room B742'})])
    report = observe_context({'events': events}, tmp_path, int(15e9))
    assert report['status'] == 'evaluated_with_new_text'
    assert report['new_text'] == 'Room B742'
    assert report['first_text_after_evaluation_ms'] == 1000
    assert report['audio_chunks'] == 0
    assert report['spoken_correctness'] == 'requires_listening_review'


def test_payload_setting_is_backward_compatible_and_validated():
    assert RunSettings.from_dict({}).context_payload_mode == 'facts'
    with pytest.raises(ValueError, match='Context payload mode'):
        RunSettings(context_payload_mode='invalid')


@pytest.mark.parametrize('delay', [0, 4000])
@pytest.mark.parametrize('mode', ['facts', 'answer_now'])
def test_b2_comparison_preserves_delay_and_wording(delay, mode, monkeypatch):
    from tool_pipeline.pipeline.context import resolve_oracle
    from tool_pipeline.pipeline.results import RunState
    from speech_contracts import RunRequest
    async def scenario():
        settings = RunSettings(oracle_delay_ms=delay, context_payload_mode=mode)
        request = RunRequest('B2', 'input.wav', settings=settings, oracle_result='Room B742')
        restored = RunRequest.from_dict(request.to_payload())
        assert restored.settings == settings
        wait = AsyncMock()
        monkeypatch.setattr('tool_pipeline.pipeline.context.asyncio.sleep', wait)
        trace = TraceRecorder()
        context = await resolve_oracle(restored, RunState(), trace)
        wait.assert_awaited_once_with(delay / 1000)
        assert context['facts'] == 'Room B742'
        assert trace.snapshot()['spans'][0]['attributes']['origin'] == 'input_end'
    asyncio.run(scenario())


def test_missing_audio_retains_evaluation_and_literal_text(tmp_path):
    events = [event('context.submitted', 1, event_id='fact'),
              event('context.evaluated', 2, event_id='fact')]
    for i, text in enumerate(['Room', ' ', 'B742']):
        events.append(event('native.event', 3 + i, event={
            'type': 'response.output.delta', 'kind': 'text', 'text': text}))
    events.append(event('audio.output_emitted', 6, chunk=1, duration_ms=1000))
    report = observe_context({'events': events}, tmp_path, int(10e9))
    assert report['evaluated'] is True
    assert report['new_text'] == 'Room B742'
    assert report['audio_chunks'] == 1
    assert report['clip_error']
    assert report['output_audio'] is None
    report = observe_context({'events': events}, tmp_path, int(2.5e9))
    assert report['new_text'] == ''
    assert report['audio_chunks'] == 0
    assert report['observation_ms'] == 500
