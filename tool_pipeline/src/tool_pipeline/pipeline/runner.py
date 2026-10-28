"""Coordinate one experiment: initialize, replay, resolve context, finish, save."""

import asyncio
import hashlib
import time
from pathlib import Path

from speech_contracts import RunRequest

from ..audio import read_pcm
from ..models.factory import create_caller
from ..models.minicpm import NativeSession
from ..models.whisper import InputTranscriber
from ..telemetry import MemorySampler, TraceRecorder
from ..tools import ToolRegistry
from .context import resolve_oracle, resolve_tool
from .playback import finish_response, replay_input
from .results import RunState, build_result, save_result


class InferencePipeline:
    def __init__(
        self,
        request: RunRequest,
        output_dir: Path,
        *,
        native_factory=NativeSession,
        caller_factory=create_caller,
        transcriber_factory=InputTranscriber,
    ):
        self.request = request
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trace = TraceRecorder()
        self.state = RunState()
        self.native_factory = native_factory
        self.caller_factory = caller_factory
        self.transcriber_factory = transcriber_factory
        self.native = None
        self.caller = None
        self.transcriber = None
        self.tools = None
        self.context_task = None

    async def run(self) -> dict:
        settings = self.request.settings
        sampler = MemorySampler(
            self.trace, settings.memory_interval_ms, self.output_dir / "telemetry.json"
        )
        with sampler:
            try:
                async with asyncio.timeout(settings.timeout_seconds):
                    await self._infer()
                self.state.status = "complete" if self.native.audio_chunks else "silent"
            except BaseException as exc:
                self.state.error = f"{type(exc).__name__}: {exc}"
                self.trace.event("run.failed", error=self.state.error)
            finally:
                await self._finalize()

        revision = self.caller.model_revision if self.caller else None
        loading = getattr(self.caller, "loading_provenance", None)
        result = build_result(
            self.request, self.state, self.native, sampler.report(), revision, loading
        )
        save_result(self.output_dir, result, self.trace)
        return result

    async def _infer(self) -> None:
        pcm = await self._initialize()
        settings = self.request.settings
        with self.trace.span(
            "inference.pipeline", condition=self.request.condition, paced=settings.paced
        ):
            self.state.first_input_ns = time.perf_counter_ns()
            self.trace.event("input.started", duration_ms=len(pcm) / 32)
            await replay_input(pcm, self.native, self.trace, paced=settings.paced)
            self.state.input_end_ns = time.perf_counter_ns()
            self.trace.event("input.finished")
            self.trace.event(
                "input.recording_committed", policy="complete_recording_after_replay"
            )

            self.context_task = self._start_context()
            await finish_response(
                self.native,
                self.trace,
                self.context_task,
                paced=settings.paced,
                drain_seconds=settings.drain_seconds,
            )
            self.state.pipeline_end_ns = time.perf_counter_ns()

    async def _initialize(self) -> bytes:
        settings = self.request.settings
        with self.trace.span("initialization"):
            audio_path = Path(self.request.audio_path)
            with self.trace.span("audio.read_and_normalize"):
                pcm = read_pcm(audio_path)
            checksum = hashlib.sha256(audio_path.read_bytes()).hexdigest()
            if self.request.audio_sha256 and checksum != self.request.audio_sha256:
                raise ValueError("Input audio checksum does not match the frozen request")

            if self.request.condition == "B1":
                self.tools = ToolRegistry(self.request.tools, self.trace, self.output_dir)
                self.transcriber = await asyncio.to_thread(
                    self.transcriber_factory, settings, self.trace
                )
                self.caller = await asyncio.to_thread(
                    self.caller_factory, settings, self.tools, self.trace
                )
            self.native = self.native_factory(settings, self.trace, self.output_dir)
            await self.native.connect()
        return pcm

    def _start_context(self) -> asyncio.Task | None:
        if self.request.condition == "B1":
            return asyncio.create_task(resolve_tool(
                self.request, self.state, self.transcriber, self.caller, self.tools, self.trace
            ))
        if self.request.condition == "B2":
            return asyncio.create_task(resolve_oracle(self.request, self.state, self.trace))
        return None

    async def _finalize(self) -> None:
        if self.context_task and not self.context_task.done():
            self.context_task.cancel()
            await asyncio.gather(self.context_task, return_exceptions=True)

        if self.native:
            try:
                await self.native.close()
                self.state.output_audio = self.native.assemble()
            except Exception as exc:
                self.state.status = "failed"
                self.state.error = self.state.error or f"Native finalization failed: {exc}"
                self.trace.event("native.finalization_failed", error=str(exc))

        if self.caller:
            try:
                with self.trace.span("telemetry.gpu_finalize"):
                    self.state.gpu_metrics = self.caller.finalize_gpu_metrics()
            except Exception as exc:
                self.trace.event("telemetry.gpu_unavailable", error=str(exc))
