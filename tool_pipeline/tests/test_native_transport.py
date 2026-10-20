"""A local protocol fixture verifies transport; it does not emulate model quality."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import websockets
from tool_pipeline.audio import float32_payload, write_pcm
from speech_contracts import RunSettings
from tool_pipeline.models.minicpm import NativeSession
from tool_pipeline.telemetry import TraceRecorder
from tool_pipeline.pipeline import InferencePipeline
from speech_contracts import RunRequest


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_caller_reply_is_sent_as_response_guidance(self):
        from unittest.mock import AsyncMock

        with tempfile.TemporaryDirectory() as directory:
            session = NativeSession(RunSettings(), TraceRecorder(), Path(directory))
            session.ws = AsyncMock()
            await session.send(bytes(32000), context={
                'event_id': 'reply', 'response_text': 'Which seminar do you mean?',
            })
            message = json.loads(session.ws.send.call_args.args[0])
            payload = message['input']['tool_context']
            assert 'Which seminar do you mean?' in payload
            assert 'Say' in payload
            assert not payload.startswith('External information')
            assert session.submitted == {1: 'reply'}

    async def test_reference_errors_distinguish_empty_settings_from_missing_files(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for value in ('', '   ', str(output / 'missing voice.wav')):
                with self.subTest(reference_audio=value):
                    session = NativeSession(RunSettings(reference_audio=value), TraceRecorder(), output)
                    with patch('websockets.connect') as connect:
                        with self.assertRaises(ValueError) as error:
                            await session.connect()
                        connect.assert_not_called()
                    message = str(error.exception)
                    if not value.strip():
                        self.assertIn('empty reference_audio', message)
                        self.assertIn('start a new run', message)
                    else:
                        self.assertIn(repr(value), message)
                        self.assertIn('runtime host', message)

    async def test_native_audio_and_context_acknowledgement(self):
        received = []
        async def fixture(ws):
            await ws.send(json.dumps({'type': 'session.queue_done'}))
            initialization = json.loads(await ws.recv())
            self.assertEqual(initialization['type'], 'session.init')
            await ws.send(json.dumps({'type': 'session.created', 'session_id': 'fixture'}))
            unit = 0
            async for raw in ws:
                message = json.loads(raw)
                if message['type'] == 'session.close':
                    await ws.send(json.dumps({'type': 'session.closed'}))
                    return
                unit += 1
                received.append(message)
                if 'tool_context' in message['input']:
                    await ws.send(json.dumps({'type': 'tool_context.evaluated', 'unit': unit + 1, 'ok': True}))
                await ws.send(json.dumps({'type': 'response.output.delta', 'kind': 'audio', 'response_id': f'fixture_resp_{unit}', 'audio': float32_payload(bytes(480))}))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_pcm(output / 'reference.wav', bytes(32000))
            try:
                server = await websockets.serve(fixture, '127.0.0.1', 0)
            except PermissionError:
                self.skipTest("Environment disallows listening sockets; run this check on the GPU server")
            async with server:
                port = server.sockets[0].getsockname()[1]
                settings = RunSettings(native_url=f'ws://127.0.0.1:{port}', reference_audio=str(output / 'reference.wav'))
                trace = TraceRecorder()
                session = NativeSession(settings, trace, output)
                await session.connect()
                await session.send(bytes(32000), context={'event_id': 'test-event', 'facts': 'Room B742'})
                await session.drain(5)
                await session.close()
                self.assertEqual(session.acknowledged, {'test-event'})
                self.assertEqual(session.assemble(), 'output.wav')
                self.assertTrue((output / 'output.wav').is_file())
                self.assertIn('Room B742', received[0]['input']['tool_context'])
                self.assertTrue(any(event['name'] == 'context.evaluated' for event in trace.snapshot()['events']))

    async def test_unpaced_drain_is_bounded_by_audio_units(self):
        class RecordingNative:
            def __init__(self, settings, trace, output):
                self.sent_units = 0
                self.audio_chunks = []
                self.error = None
            async def connect(self): pass
            async def send(self, audio, **kwargs): self.sent_units += 1
            async def drain(self, timeout): pass
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'input.wav'
            write_pcm(audio, bytes(32000))
            request = RunRequest('B0', str(audio), settings=RunSettings(paced=False, drain_seconds=3))
            pipeline = InferencePipeline(request, Path(directory), native_factory=RecordingNative)
            await pipeline._infer()
            self.assertEqual(pipeline.native.sent_units, 4)

    async def test_in_memory_transport_handshake_audio_and_ack(self):
        from unittest.mock import patch
        class WireFixture:
            def __init__(self):
                self.events = asyncio.Queue()
                self.events.put_nowait(json.dumps({'type': 'session.queue_done'}))
                self.unit = 0
                self.inputs = []
            async def recv(self): return await self.events.get()
            def __aiter__(self): return self
            async def __anext__(self): return await self.recv()
            async def close(self): pass
            async def send(self, raw):
                message = json.loads(raw)
                if message['type'] == 'session.init':
                    self.events.put_nowait(json.dumps({'type': 'session.created', 'session_id': 'fixture'}))
                elif message['type'] == 'session.close':
                    self.events.put_nowait(json.dumps({'type': 'session.closed'}))
                else:
                    self.unit += 1
                    self.inputs.append(message['input'])
                    if 'tool_context' in message['input']:
                        self.events.put_nowait(json.dumps({'type': 'tool_context.evaluated', 'unit': self.unit + 1, 'ok': True}))
                    self.events.put_nowait(json.dumps({'type': 'response.output.delta', 'kind': 'audio', 'response_id': f'fixture_resp_{self.unit}', 'audio': float32_payload(bytes(480))}))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_pcm(output / 'reference.wav', bytes(32000))
            wire = WireFixture()
            async def connect(*args, **kwargs): return wire
            session = NativeSession(RunSettings(reference_audio=str(output / 'reference.wav')), TraceRecorder(), output)
            with patch('websockets.connect', connect):
                await session.connect()
                await session.send(bytes(32000), context={'event_id': 'fact', 'facts': 'Room B742'})
                await session.drain(5)
                await session.close()
            self.assertEqual(session.acknowledged, {'fact'})
            self.assertEqual(session.assemble(), 'output.wav')
            self.assertIn('Room B742', wire.inputs[0]['tool_context'])

    async def test_late_oracle_receives_full_post_injection_drain(self):
        class RecordingNative:
            def __init__(self, settings, trace, output):
                self.sent_units = 0
                self.audio_chunks = []
                self.error = None
                self.contexts = []
            async def connect(self): pass
            async def send(self, audio, **kwargs):
                self.sent_units += 1
                self.contexts.append(bool(kwargs.get('context')))
            async def drain(self, timeout): pass
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / 'input.wav'
            write_pcm(audio, bytes(32000))
            request = RunRequest('B2', str(audio), settings=RunSettings(paced=False, drain_seconds=1, oracle_delay_ms=1001), oracle_result='Room B742')
            pipeline = InferencePipeline(request, Path(directory), native_factory=RecordingNative)
            await pipeline._infer()
            contexts = pipeline.native.contexts
            injection = contexts.index(True)
            self.assertEqual(sum(contexts), 1)
            self.assertEqual(len(contexts) - injection - 1, 1)

    async def test_reference_snapshot_is_used_if_original_changes_while_waiting(self):
        from unittest.mock import patch
        from tool_pipeline.audio import read_pcm

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            reference = Path(directory) / 'voice.wav'
            write_pcm(reference, bytes(32000))
            original = reference.read_bytes()
            class Wire:
                async def send(self, raw):
                    message = json.loads(raw)
                    self.initialization = message
                async def close(self):
                    pass
            wire = Wire()
            async def connect(*args, **kwargs):
                return wire
            session = NativeSession(RunSettings(reference_audio=str(reference)), TraceRecorder(), output)
            async def control(expected, timeout):
                if expected == 'session.queue_done':
                    write_pcm(reference, b'\x01\x00' * 16000)
                return {'session_id': 'fixture'}
            async def reader():
                await asyncio.sleep(60)
            with patch('websockets.connect', connect), patch.object(session, '_wait_control', control), patch.object(session, '_read', reader):
                await session.connect()
                session.reader.cancel()
                await asyncio.gather(session.reader, return_exceptions=True)
            assert (output / 'reference.wav').read_bytes() == original
            voice = wire.initialization['payload']['voice']['ref_audio_base64']
            assert voice == float32_payload(read_pcm(output / 'reference.wav'))
            assert voice != float32_payload(read_pcm(reference))
