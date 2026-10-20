"""Produce B1 tool facts/response guidance or B2 saved oracle facts."""

import asyncio
import uuid
from pathlib import Path

from speech_contracts import RunRequest

from ..telemetry import TraceRecorder
from .results import RunState


async def resolve_tool(request: RunRequest, state: RunState, transcriber, caller, tools, trace):
    with trace.span("tool_pipeline"):
        state.transcript = await asyncio.to_thread(
            transcriber.transcribe, Path(request.audio_path)
        )
        state.action = await caller.decide(state.transcript)
        trace.event("caller.action", **state.action)
        if state.action["kind"] == "respond":
            context = {"event_id": uuid.uuid4().hex, "response_text": state.action["message"]}
            trace.event("caller.response", **context)
            return context
        if state.action["kind"] == "invalid":
            state.tool_error = state.action.get("message") or "Invalid native caller output"
            trace.event("caller.invalid", error=state.tool_error)
            return {"event_id": uuid.uuid4().hex,
                    "response_text": "I couldn't process that request. Could you try again?"}
        if state.action["kind"] != "call":
            return None

        name = state.action["tool"]
        arguments = state.action["arguments"]
        trace.event("tool.request", tool=name, arguments=arguments)
        try:
            state.tool_result = await tools.execute(name, arguments, state.transcript)
        except Exception as exc:
            state.tool_error = str(exc)
            trace.event("tool.rejected_or_failed", error=state.tool_error)
            return {"event_id": uuid.uuid4().hex,
                    "response_text": "I couldn't complete that request. Could you try again?"}

        context = {**state.tool_result, "event_id": uuid.uuid4().hex}
        trace.event("tool.completed", **context)
        return context


async def resolve_oracle(request: RunRequest, state: RunState, trace: TraceRecorder):
    if request.oracle_result is None:
        return None

    delay_ms = request.settings.oracle_delay_ms
    with trace.span("oracle.availability_delay", configured_ms=delay_ms, origin="input_end"):
        await asyncio.sleep(delay_ms / 1000)

    state.tool_result = {
        "event_id": uuid.uuid4().hex,
        "facts": request.oracle_result,
        "sources": ["study://frozen-oracle"],
    }
    trace.event("oracle.available", **state.tool_result)
    return state.tool_result
