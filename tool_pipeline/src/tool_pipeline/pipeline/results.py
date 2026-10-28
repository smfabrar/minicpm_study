"""Collected run data and the result format consumed by the study application."""

import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from speech_contracts import RunRequest

from ..provenance import execution_environment


@dataclass
class RunState:
    status: str = "failed"
    error: str | None = None
    output_audio: str | None = None
    transcript: str = ""
    action: dict | None = None
    tool_result: dict | None = None
    tool_error: str | None = None
    first_input_ns: int | None = None
    input_end_ns: int | None = None
    pipeline_end_ns: int | None = None
    gpu_metrics: dict = field(default_factory=dict)


def elapsed_ms(end: int | None, begin: int | None) -> float | None:
    if end is None or begin is None:
        return None
    return (end - begin) / 1e6


def build_result(
    request: RunRequest,
    state: RunState,
    native,
    memory: dict,
    caller_revision: str | None,
) -> dict:
    missing_acks = sorted(set(native.submitted.values()) - native.acknowledged) if native else []
    if missing_acks:
        state.status = "failed"
        state.error = state.error or "Missing native evaluation acknowledgement"

    first_audio = native.first_audio_ns if native else None
    final_audio = native.final_audio_ns if native else None
    return {
        "status": state.status,
        "error": state.error,
        "condition": request.condition,
        "output_audio": state.output_audio,
        "assistant_text": "".join(native.text) if native else "",
        "input_transcript": state.transcript,
        "caller_action": state.action,
        "tool_result": state.tool_result,
        "tool_error": state.tool_error,
        "context_submitted": len(native.submitted) if native else 0,
        "context_evaluated": len(native.acknowledged) if native else 0,
        "missing_evaluation_acks": missing_acks,
        "metrics": {
            "input_start_to_first_audio_ms": elapsed_ms(first_audio, state.first_input_ns),
            "input_end_to_first_audio_ms": elapsed_ms(first_audio, state.input_end_ns),
            "input_start_to_final_audio_ms": elapsed_ms(final_audio, state.first_input_ns),
            "pipeline_elapsed_ms": elapsed_ms(state.pipeline_end_ns, state.first_input_ns),
            "gpu_allocator": state.gpu_metrics,
            "memory": memory,
        },
        "provenance": {
            **execution_environment(),
            "python": sys.version,
            "platform": platform.platform(),
            "hostname": platform.node(),
            "native_session_id": native.session_id if native else None,
            "caller_backend": request.settings.caller.backend if caller_revision else None,
            "caller_model": request.settings.caller.model if caller_revision else None,
            "caller_resolved_revision": caller_revision,
            "caller_calling_mode": "native" if caller_revision else None,
            "caller_enable_thinking": (
                False if caller_revision and request.settings.caller.backend == "qwen3" else None
            ),
            "granite_resolved_revision": (
                caller_revision if request.settings.caller.backend == "granite" else None
            ),
            "granite_calling_mode": (
                "native" if caller_revision and request.settings.caller.backend == "granite" else None
            ),
            "audio_sha256": request.audio_sha256,
            "settings": asdict(request.settings),
            "input_commit_policy": "complete_recording_after_replay",
        },
        "unavailable_metrics": {
            "native.audio_encoding": "Native backend does not emit structured operation timing",
            "native.prefill": "Requires native backend instrumentation",
            "native.decode": "Requires native backend instrumentation",
            "native.vocoding": "Requires native backend instrumentation",
            "whisper.preprocessing_and_gpu_substeps": (
                "faster-whisper exposes a combined iterator; no separate GPU events"
            ),
            "time_to_correct_spoken_fact": "Requires output-audio alignment and human review",
        },
    }


def save_result(output_dir: Path, result: dict, trace) -> None:
    trace.write(output_dir / "telemetry.json")
    (output_dir / "trace.chrome.json").write_text(json.dumps(trace.chrome_trace()))
    (output_dir / "result.json").write_text(json.dumps(result, indent=2))
