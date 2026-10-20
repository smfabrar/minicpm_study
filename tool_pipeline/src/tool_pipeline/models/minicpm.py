"""Pinned OpenBMB realtime transport with tool-context ACK attribution."""

import asyncio
import contextvars
import hashlib
import json
import shutil
import re
import socket
import time
from pathlib import Path

from speech_contracts import RunSettings

from ..audio import float32_payload, payload_pcm, read_pcm, write_pcm
from ..telemetry import TraceRecorder


class NativeSession:
    def __init__(self, settings: RunSettings, trace: TraceRecorder, output_dir: Path):
        self.settings = settings
        self.trace = trace
        self.output_dir = output_dir
        self.ws = None
        self.reader = None
        self.closed = asyncio.Event()
        self.text = []
        self.audio_chunks = []
        self.sent_units = 0
        self.last_response_unit = 0
        self.last_event_ns = time.perf_counter_ns()
        self.submitted = {}
        self.acknowledged = set()
        self.session_id = None
        self.error = None
        self.first_audio_ns = None
        self.final_audio_ns = None

    async def connect(self):
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "Native transport requires websockets. Install tool-pipeline[models] on the GPU server."
            ) from exc
        if not self.settings.reference_audio.strip():
            raise ValueError(
                "This run has empty reference_audio. Set the reference WAV in Study > Settings, "
                "save the configuration, and start a new run."
            )
        reference = Path(self.settings.reference_audio)
        if not reference.is_file():
            raise ValueError(
                f"reference_audio is not a file on runtime host {socket.gethostname()}: "
                f"saved value {self.settings.reference_audio!r}, checked path {str(reference.absolute())!r}. "
                "Set a WAV path accessible to the pipeline worker and start a new run."
            )
        with self.trace.span("native.reference_audio_snapshot"):
            copy = self.output_dir / "reference.wav"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            if reference.resolve() != copy.resolve():
                shutil.copyfile(reference, copy)
            self.trace.event("native.reference_audio", path=str(reference), artifact=copy.name,
                             sha256=hashlib.sha256(copy.read_bytes()).hexdigest())
        with self.trace.span("native.connection"):
            self.ws = await websockets.connect(
                self.settings.native_url,
                max_size=128 * 1024 * 1024, open_timeout=30, close_timeout=10,
            )
            await self._wait_control("session.queue_done", 120)
        with self.trace.span("native.session_initialization"):
            voice = float32_payload(read_pcm(copy))
            await self.ws.send(json.dumps({
                "type": "session.init",
                "payload": {
                    "system_prompt": self.settings.system_prompt,
                    "config": {"length_penalty": 1.1},
                    "voice": {"ref_audio_base64": voice, "tts_ref_audio_base64": voice},
                },
            }))
            event = await self._wait_control("session.created", 180)
            self.session_id = event.get("session_id")
        self.reader = asyncio.create_task(
            self._read(), name="native-output", context=contextvars.Context()
        )

    async def _wait_control(self, expected, timeout):
        async with asyncio.timeout(timeout):
            while True:
                event = json.loads(await self.ws.recv())
                self.trace.event("native.control", event=event)
                if event.get("type") == expected:
                    return event
                if event.get("type") in {"session.closed", "error"}:
                    raise RuntimeError(f"Native initialization failed: {event}")

    async def send(self, pcm, *, context=None, silence=False):
        self.sent_units += 1
        unit = self.sent_units
        with self.trace.span("audio.serialize", unit=unit):
            payload = {"audio": float32_payload(pcm)}
            if context:
                if "response_text" in context:
                    prefix = "Response guidance for the current request. Say the following to the user: "
                    text = prefix + " ".join(context["response_text"].split())
                else:
                    prefix = "External information for the current request: "
                    text = prefix + " ".join(context["facts"].split())
                delivered = text.encode("utf-8")[:640].decode("utf-8", "ignore")
                payload["tool_context"] = delivered
                self.submitted[unit] = context["event_id"]
                self.trace.event(
                    "context.payload", event_id=context["event_id"], unit=unit,
                    exact_payload=delivered, truncated=delivered != text,
                    kind="response" if "response_text" in context else "facts",
                )
        with self.trace.span("native.input_send", unit=unit, silence=silence):
            await self.ws.send(json.dumps({"type": "input.append", "input": payload}))
        self.trace.event("audio.input_sent", unit=unit, silence=silence)
        if context:
            self.trace.event("context.submitted", unit=unit, event_id=context["event_id"])

    async def _read(self):
        try:
            async for raw in self.ws:
                event = json.loads(raw)
                self.last_event_ns = time.perf_counter_ns()
                response_id = str(event.get("response_id", ""))
                match = re.search(r"_resp_(\d+)$", response_id)
                if match:
                    self.last_response_unit = max(self.last_response_unit, int(match.group(1)))
                self.trace.event(
                    "native.event",
                    event={key: value for key, value in event.items()
                           if key not in {"audio", "audio_data"}},
                )
                if event.get("type") == "tool_context.evaluated":
                    self._receive_ack(event)
                elif event.get("type") == "response.output.delta":
                    if event.get("kind") == "text":
                        self.text.append(str(event.get("text", "")))
                    elif event.get("kind") == "audio" and event.get("audio"):
                        self._receive_audio(event, response_id)
                elif event.get("type") == "error":
                    self.error = str(event)
                elif event.get("type") == "session.closed":
                    self.closed.set()
                    return
        except Exception as exc:
            self.error = f"Native receive failed: {exc}"
        finally:
            self.closed.set()

    def _receive_ack(self, event):
        unit = int(event.get("unit", -1)) - 1  # Pinned C++ input-index offset.
        event_id = self.submitted.get(unit)
        if event_id and event.get("ok"):
            self.acknowledged.add(event_id)
            self.trace.event("context.evaluated", unit=unit, event_id=event_id)
        else:
            self.error = (
                f"Rejected or unmatched tool acknowledgement at native unit {event.get('unit')}"
            )

    def _receive_audio(self, event, response_id):
        at = time.perf_counter_ns()
        self.first_audio_ns = self.first_audio_ns or at
        self.final_audio_ns = at
        with self.trace.span("audio.output_decode", response_id=response_id):
            pcm = payload_pcm(event["audio"])
        with self.trace.span("audio.chunk_storage", chunk=len(self.audio_chunks)):
            path = self.output_dir / f"speaker_{len(self.audio_chunks):04d}.wav"
            write_pcm(path, pcm, 24000)
            self.audio_chunks.append(pcm)
        self.trace.event(
            "audio.output_emitted", chunk=len(self.audio_chunks),
            duration_ms=len(pcm) / 48, response_id=response_id,
        )

    async def drain(self, timeout):
        with self.trace.span("native.output_drain", timeout_seconds=timeout):
            async with asyncio.timeout(timeout):
                while True:
                    if self.error:
                        raise RuntimeError(self.error)
                    if self.closed.is_set():
                        raise RuntimeError("Native session closed before output drain completed")
                    quiet = (time.perf_counter_ns() - self.last_event_ns) / 1e9
                    all_units_received = self.last_response_unit >= self.sent_units
                    all_context_acknowledged = set(self.submitted.values()) <= self.acknowledged
                    if all_units_received and all_context_acknowledged and quiet >= 2:
                        return
                    await asyncio.sleep(0.05)

    async def close(self):
        if not self.ws:
            return
        try:
            if not self.closed.is_set():
                await self.ws.send(json.dumps({"type": "session.close", "reason": "experiment_complete"}))
                await asyncio.wait_for(self.closed.wait(), 5)
        except Exception as exc:
            self.trace.event("native.close_error", error=str(exc))
        finally:
            await self.ws.close()
            if self.reader:
                await asyncio.gather(self.reader, return_exceptions=True)

    def assemble(self):
        if not self.audio_chunks:
            return None
        with self.trace.span("audio.output_assembly"):
            path = self.output_dir / "output.wav"
            write_pcm(path, b"".join(self.audio_chunks), 24000)
            return path.name
