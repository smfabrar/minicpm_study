"""Audio replay and the silence boundaries used to deliver context."""

import asyncio
import time

from ..models.minicpm import NativeSession
from ..telemetry import TraceRecorder

BYTES_PER_SECOND = 16000 * 2  # Mono PCM16 at 16 kHz.
SILENCE = bytes(BYTES_PER_SECOND)


async def replay_input(
    pcm: bytes, native: NativeSession, trace: TraceRecorder, *, paced: bool
) -> None:
    scheduled = time.monotonic()
    for offset in range(0, len(pcm), BYTES_PER_SECOND):
        with trace.span("audio.chunk_prepare", unit=native.sent_units + 1):
            chunk = pcm[offset:offset + BYTES_PER_SECOND]
            duration = len(chunk) / BYTES_PER_SECOND
            chunk = chunk.ljust(BYTES_PER_SECOND, b"\x00")
        scheduled += duration
        if paced:
            with trace.span("audio.replay_wait"):
                await asyncio.sleep(max(0, scheduled - time.monotonic()))
        await native.send(chunk)


async def finish_response(
    native: NativeSession,
    trace: TraceRecorder,
    context_task: asyncio.Task | None,
    *,
    paced: bool,
    drain_seconds: int,
) -> None:
    remaining_units = drain_seconds
    while remaining_units > 0 or context_task is not None:
        context = None
        if context_task is not None and context_task.done():
            context = await context_task
            context_task = None  # Consume the result once, even when it contains no fact.
            if context:
                # The injection unit is followed by a full drain budget.
                remaining_units = max(remaining_units, drain_seconds + 1)

        with trace.span("audio.silence_boundary_wait"):
            pending = context_task is not None and not context_task.done()
            await asyncio.sleep(1 if paced or pending else 0)
        await native.send(SILENCE, context=context, silence=True)
        remaining_units = max(0, remaining_units - 1)
        if native.error:
            raise RuntimeError(native.error)

    await native.drain(max(10, drain_seconds * 2))
