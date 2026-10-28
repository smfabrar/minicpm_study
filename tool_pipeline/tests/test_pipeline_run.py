"""Full run lifecycle with CPU transport/model fixtures, never study measurements."""

import asyncio
import json
import time
from dataclasses import replace

import pytest

from speech_contracts import RunRequest, RunSettings
from tool_pipeline.audio import write_pcm
from tool_pipeline.pipeline import InferencePipeline


class RecordingNative:
    def __init__(self, settings, trace, output):
        self.output = output
        self.trace = trace
        self.sent_units = 0
        self.inputs = []
        self.audio_chunks = []
        self.text = []
        self.submitted = {}
        self.acknowledged = set()
        self.first_audio_ns = None
        self.final_audio_ns = None
        self.session_id = "cpu-fixture"
        self.error = None
        self.closed = False
        self.acknowledge = True

    async def connect(self):
        pass

    async def send(self, audio, *, context=None, silence=False):
        self.sent_units += 1
        self.inputs.append((audio, context, silence))
        if context:
            self.submitted[self.sent_units] = context["event_id"]
            if self.acknowledge:
                self.acknowledged.add(context["event_id"])
        self.audio_chunks.append(bytes(480))
        self.first_audio_ns = self.first_audio_ns or time.perf_counter_ns()
        self.final_audio_ns = time.perf_counter_ns()

    async def drain(self, timeout):
        pass

    async def close(self):
        self.closed = True

    def assemble(self):
        if not self.audio_chunks:
            return None
        write_pcm(self.output / "output.wav", b"".join(self.audio_chunks), 24000)
        return "output.wav"


class TranscriptFixture:
    def __init__(self, settings, trace):
        self.trace = trace

    def transcribe(self, path):
        names = [event["name"] for event in self.trace.snapshot()["events"]]
        assert "input.finished" in names
        assert "input.recording_committed" in names
        return "Where is the robotics seminar?"


class CallerFixture:
    action = {"kind": "call", "tool": "room_lookup", "arguments": {"name": "robotics seminar"}}
    model_revision = "cpu-fixture"

    def __init__(self, settings, registry, trace):
        self.registry = registry

    async def decide(self, transcript):
        return self.action

    def finalize_gpu_metrics(self):
        return {}


def make_pipeline(tmp_path, condition="B1", *, caller=CallerFixture, native=RecordingNative):
    audio = tmp_path / "input.wav"
    write_pcm(audio, bytes(32000))
    tools = [{
        "name": "room_lookup", "description": "Find a seminar room", "parameter": "name",
        "kind": "room", "records": {"robotics seminar": "Room B742"},
    }]
    request = RunRequest(
        condition, str(audio),
        settings=RunSettings(paced=False, drain_seconds=1, oracle_delay_ms=0),
        tools=tools if condition == "B1" else [],
        oracle_result="Room B742" if condition == "B2" else None,
    )
    return InferencePipeline(
        request, tmp_path / "run", native_factory=native,
        caller_factory=caller, transcriber_factory=TranscriptFixture,
    )


@pytest.mark.parametrize("condition", ["B0", "B1", "B2"])
def test_full_run_preserves_condition_results_and_artifacts(tmp_path, condition):
    pipeline = make_pipeline(tmp_path, condition)
    result = asyncio.run(pipeline.run())
    contexts = [context for _, context, _ in pipeline.native.inputs if context]
    assert result["status"] == "complete"
    assert result["condition"] == condition
    assert len(contexts) == (0 if condition == "B0" else 1)
    assert result["context_submitted"] == result["context_evaluated"] == len(contexts)
    assert result["missing_evaluation_acks"] == []
    assert bool(result["input_transcript"]) == (condition == "B1")
    assert bool(result["caller_action"]) == (condition == "B1")
    assert pipeline.native.closed
    for name in ("output.wav", "result.json", "telemetry.json", "trace.chrome.json"):
        assert (pipeline.output_dir / name).is_file()
    assert json.loads((pipeline.output_dir / "result.json").read_text()) == result
    assert result["metrics"]["pipeline_elapsed_ms"] >= 0
    if contexts:
        assert contexts[0]["facts"] == result["tool_result"]["facts"] == "Room B742"
        injection = next(i for i, (_, context, _) in enumerate(pipeline.native.inputs) if context)
        assert len(pipeline.native.inputs) - injection - 1 >= 1


@pytest.mark.parametrize("kind", ["none", "clarify"])
def test_legacy_non_call_fixture_finishes_without_injection(tmp_path, kind):
    class NoCall(CallerFixture):
        action = {"kind": kind}

    pipeline = make_pipeline(tmp_path, caller=NoCall)
    result = asyncio.run(pipeline.run())
    assert result["status"] == "complete"
    assert result["caller_action"]["kind"] == kind
    assert result["tool_result"] is None
    assert result["context_submitted"] == 0


def test_rejected_tool_preserves_error_and_audio_with_failure_guidance(tmp_path):
    class UngroundedCall(CallerFixture):
        action = {"kind": "call", "tool": "room_lookup", "arguments": {"name": "invented event"}}

    pipeline = make_pipeline(tmp_path, caller=UngroundedCall)
    result = asyncio.run(pipeline.run())
    assert result["status"] == "complete"
    assert "grounded" in result["tool_error"]
    assert result["context_submitted"] == 1
    contexts = [context for _, context, _ in pipeline.native.inputs if context]
    assert contexts[0]["response_text"]
    assert "invented event" not in contexts[0]["response_text"]
    assert result["tool_result"] is None
    assert result["output_audio"] == "output.wav"


def test_native_clarification_text_is_delivered_without_executing_a_tool(tmp_path):
    class Reply(CallerFixture):
        action = {"kind": "respond", "message": "Which seminar do you mean?", "raw": "Which seminar do you mean?"}

    pipeline = make_pipeline(tmp_path, caller=Reply)
    result = asyncio.run(pipeline.run())
    contexts = [context for _, context, _ in pipeline.native.inputs if context]
    assert result["status"] == "complete"
    assert result["tool_result"] is None
    assert result["tool_error"] is None
    assert result["context_submitted"] == result["context_evaluated"] == 1
    assert contexts[0]["response_text"] == "Which seminar do you mean?"
    assert "facts" not in contexts[0]


def test_invalid_native_call_delivers_failure_guidance_and_preserves_error(tmp_path):
    class Invalid(CallerFixture):
        action = {"kind": "invalid", "message": "malformed tool call", "raw": "<tool_call>{"}

    pipeline = make_pipeline(tmp_path, caller=Invalid)
    result = asyncio.run(pipeline.run())
    contexts = [context for _, context, _ in pipeline.native.inputs if context]
    assert result["tool_error"] == "malformed tool call"
    assert result["tool_result"] is None
    assert result["context_submitted"] == 1
    assert contexts[0]["response_text"]
    assert "<tool_call>" not in contexts[0]["response_text"]


@pytest.mark.parametrize("quantization", ["none", "nf4"])
def test_qwen_pipeline_retains_generic_provenance_and_native_ack(tmp_path, quantization):
    from tool_pipeline.models.qwen import QwenCaller

    def qwen_fixture(settings, registry, trace):
        caller = QwenCaller.__new__(QwenCaller)
        caller.registry = registry
        caller.trace = trace
        caller.model_revision = 'qwen-fixture-sha'
        caller.loading_provenance = {'quantization': quantization, 'compute_dtype': 'float16'}
        caller.gpu_pairs = []
        caller.generate = lambda messages, schemas: (
            '<tool_call>{"name":"room_lookup","arguments":{"name":"robotics seminar"}}</tool_call><|im_end|>'
        )
        return caller

    pipeline = make_pipeline(tmp_path, caller=qwen_fixture)
    pipeline.request = replace(pipeline.request, settings=replace(
        pipeline.request.settings, caller_backend='qwen3', caller_device='cuda:0', caller_quantization=quantization
    ))
    result = asyncio.run(pipeline.run())
    assert result['status'] == 'complete'
    assert result['tool_result']['facts'] == 'Room B742'
    assert result['context_submitted'] == result['context_evaluated'] == 1
    provenance = result['provenance']
    assert provenance['caller_backend'] == 'qwen3'
    assert provenance['caller_model'] == 'Qwen/Qwen3-1.7B'
    assert provenance['caller_resolved_revision'] == 'qwen-fixture-sha'
    assert provenance['caller_enable_thinking'] is False
    assert provenance['caller_loading']['quantization'] == quantization
    assert provenance['settings']['caller_quantization'] == quantization
    assert provenance['granite_resolved_revision'] is None


def test_missing_ack_marks_run_failed_and_retains_audio(tmp_path):
    def without_ack(*args):
        native = RecordingNative(*args)
        native.acknowledge = False
        return native

    result = asyncio.run(make_pipeline(tmp_path, "B2", native=without_ack).run())
    assert result["status"] == "failed"
    assert "acknowledgement" in result["error"]
    assert len(result["missing_evaluation_acks"]) == 1
    assert result["output_audio"] == "output.wav"


def test_timeout_closes_native_and_saves_partial_trace(tmp_path, monkeypatch):
    class StalledNative(RecordingNative):
        async def send(self, *args, **kwargs):
            await asyncio.Event().wait()

    original_timeout = asyncio.timeout
    monkeypatch.setattr(asyncio, "timeout", lambda _: original_timeout(0.02))
    pipeline = make_pipeline(tmp_path, "B0", native=StalledNative)
    result = asyncio.run(pipeline.run())
    assert result["status"] == "failed"
    assert "TimeoutError" in result["error"]
    assert pipeline.native.closed
    assert result["metrics"]["pipeline_elapsed_ms"] is None
    trace = json.loads((pipeline.output_dir / "telemetry.json").read_text())
    assert any(event["name"] == "run.failed" for event in trace["events"])
