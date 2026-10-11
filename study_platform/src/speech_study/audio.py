"""PCM WAV conversion shared by preparation and native transport."""

import array
import audioop
import base64
import io
import sys
import wave
from pathlib import Path


def read_pcm(path: Path, target_rate=16000):
    try:
        with wave.open(str(path), "rb") as wav:
            rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
            if channels not in (1, 2) or width not in (1, 2, 3, 4):
                raise ValueError("Use a mono or stereo PCM WAV file")
            if not 8000 <= rate <= 384000 or wav.getnframes() / rate > 300:
                raise ValueError("Use a WAV at 8–384 kHz, no longer than five minutes")
            pcm = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise ValueError("Use a valid uncompressed PCM WAV file") from exc
    if width == 1:
        pcm = audioop.bias(pcm, 1, -128)
    if channels == 2:
        pcm = audioop.tomono(pcm, width, 0.5, 0.5)
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if rate != target_rate:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, target_rate, None)
    if not pcm:
        raise ValueError("Audio file is empty")
    return pcm


def wav_bytes(pcm: bytes, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return output.getvalue()


def write_pcm(path: Path, pcm: bytes, rate=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(pcm, rate))


def float32_payload(pcm):
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    floats = array.array("f", (x / 32768 for x in samples))
    if sys.byteorder != "little":
        floats.byteswap()
    return base64.b64encode(floats.tobytes()).decode()


def payload_pcm(payload):
    floats = array.array("f")
    floats.frombytes(base64.b64decode(payload, validate=True))
    if sys.byteorder != "little":
        floats.byteswap()
    samples = array.array("h", (round(max(-1, min(1, x)) * 32767) for x in floats))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()
