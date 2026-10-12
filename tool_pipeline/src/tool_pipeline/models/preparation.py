"""Question synthesis and answer transcription outside inference timing."""

import hashlib
import importlib.metadata
from pathlib import Path

from ..audio import read_pcm, write_pcm
from ..telemetry import MemorySampler, TraceRecorder


def synthesize(question, settings, output_dir):
    trace = TraceRecorder()
    original = output_dir / "original.wav"
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from kokoro import KPipeline
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Kokoro is not installed. Install the models extra on the machine performing preparation."
        ) from exc
    with MemorySampler(trace, telemetry_path=output_dir / "telemetry.json") as sampler:
        with trace.span("preparation.tts"):
            with trace.span("tts.device_setup", requested_device=settings.tts_device):
                device = settings.tts_device
                if device.startswith("cuda"):
                    if not torch.cuda.is_available():
                        raise RuntimeError("CUDA was requested for Kokoro but is unavailable in this runtime")
                    index = int(device.split(":")[1]) if ":" in device else torch.cuda.current_device()
                    if index >= torch.cuda.device_count():
                        raise RuntimeError(f"Kokoro device cuda:{index} is not visible to this runtime")
                    device = f"cuda:{index}"
                    torch.cuda.synchronize(device)
            with trace.span("tts.resolve_snapshot"):
                source = Path(snapshot_download("hexgrad/Kokoro-82M", revision=settings.tts_revision))
            voice_path = source / "voices" / (settings.voice + ".pt")
            if not voice_path.is_file():
                raise ValueError("Voice is not present in the pinned Kokoro snapshot")
            with trace.span("tts.model_load", device=device):
                from kokoro import KModel
                model = KModel(
                    config=str(source / "config.json"), model=str(source / "kokoro-v1_0.pth")
                ).to(device=device, dtype=torch.float32).eval()
                pipeline = KPipeline(lang_code="a", model=model)
                if device.startswith("cuda"):
                    torch.cuda.synchronize(device)
            with trace.span("tts.synthesis", device=device, voice=settings.voice, speed=settings.tts_speed):
                chunks = []
                with torch.inference_mode():
                    for _, _, audio in pipeline(question, voice=str(voice_path), speed=settings.tts_speed):
                        chunk = audio.cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio)
                        chunks.append(chunk)
                if device.startswith("cuda"):
                    torch.cuda.synchronize(device)
                if not chunks:
                    raise ValueError("Kokoro produced no audio")
            with trace.span("tts.original_storage"):
                sf.write(original, np.concatenate(chunks), 24000, subtype="PCM_16")
            with trace.span("tts.resample_to_16khz"):
                write_pcm(output_dir / "input.wav", read_pcm(original))
    trace.write(output_dir / "telemetry.json")
    return {
        "status": "complete", "kind": "synthesis",
        "output_audio": "input.wav", "original_audio": "original.wav",
        "audio_sha256": hashlib.sha256((output_dir / "input.wav").read_bytes()).hexdigest(),
        "provenance": {
            "model": "hexgrad/Kokoro-82M", "resolved_revision": source.name,
            "voice": settings.voice, "speed": settings.tts_speed,
            "device": device, "dtype": "float32",
            "package_version": importlib.metadata.version("kokoro"),
            "sample_rate": 16000, "source_sample_rate": 24000,
        },
        "memory": sampler.report(),
    }


def transcribe_output(audio_path, settings, output_dir):
    from .whisper import InputTranscriber
    trace = TraceRecorder()
    with MemorySampler(trace, telemetry_path=output_dir / "telemetry.json") as sampler:
        with trace.span("analysis.output_transcription"):
            transcriber = InputTranscriber(settings, trace)
            text = transcriber.transcribe(audio_path)
    trace.write(output_dir / "telemetry.json")
    segments = next(
        (event["attributes"]["segments"] for event in trace.events
         if event["name"] == "transcript.committed"), []
    )
    return {
        "status": "complete", "kind": "transcription", "transcript": text,
        "segments": segments, "memory": sampler.report(),
    }
