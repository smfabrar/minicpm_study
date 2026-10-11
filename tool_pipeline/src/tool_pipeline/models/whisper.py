"""Whisper transcription shared by input and output analysis."""

from pathlib import Path

from speech_contracts import RunSettings

from ..telemetry import TraceRecorder


class InputTranscriber:
    def __init__(self, settings: RunSettings, trace: TraceRecorder):
        self.trace = trace
        with trace.span("initialization.whisper"):
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "Whisper dependencies missing. Install tool-pipeline[models] on the GPU server."
                ) from exc
            self.model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                device_index=settings.whisper_device_index,
                compute_type=settings.whisper_compute_type,
            )

    def transcribe(self, path: Path) -> str:
        # faster-whisper executes lazily while the segment iterator is consumed.
        with self.trace.span("whisper.transcribe_setup"):
            segments, _ = self.model.transcribe(
                str(path), beam_size=1, language="en", vad_filter=False
            )
        with self.trace.span("whisper.inference_and_segment_decode"):
            decoded = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
        text = " ".join(s["text"].strip() for s in decoded).strip()
        self.trace.event("transcript.committed", text=text, segments=decoded)
        return text
