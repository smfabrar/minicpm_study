"""Device routing checks with model doubles; these do not execute CUDA or Kokoro."""

import json
import sys
import types
import wave
from contextlib import nullcontext

import pytest
from speech_contracts import RunSettings
from tool_pipeline.models import preparation

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")


@pytest.fixture
def model_runtime(tmp_path, monkeypatch):
    source = tmp_path / "snapshot"
    (source / "voices").mkdir(parents=True)
    (source / "voices/af_heart.pt").write_bytes(b"fixture")
    calls = []

    class Model:
        def __init__(self, **kwargs):
            calls.append(("load", kwargs))

        def to(self, **kwargs):
            calls.append(("placement", kwargs))
            return self

        def eval(self):
            return self

    class Pipeline:
        def __init__(self, **kwargs):
            assert isinstance(kwargs["model"], Model)

        def __call__(self, question, **kwargs):
            calls.append(("synthesize", question))
            yield question, "fixture phonemes", np.zeros(2400, dtype=np.float32)

    cuda = types.SimpleNamespace(
        is_available=lambda: True, device_count=lambda: 2, current_device=lambda: 1,
        synchronize=lambda device: calls.append(("synchronize", device)),
    )
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        cuda=cuda, float32="float32", inference_mode=nullcontext,
    ))
    monkeypatch.setitem(sys.modules, "kokoro", types.SimpleNamespace(KModel=Model, KPipeline=Pipeline))
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(
        snapshot_download=lambda *args, **kwargs: str(source),
    ))
    monkeypatch.setattr(preparation.importlib.metadata, "version", lambda name: "fixture")
    output = tmp_path / "output"
    output.mkdir()
    return calls, cuda, output


@pytest.mark.parametrize("requested,actual", [("cpu", "cpu"), ("cuda:0", "cuda:0"), ("cuda", "cuda:1")])
def test_synthesis_uses_requested_device_and_records_completed_spans(model_runtime, requested, actual):
    calls, _, output = model_runtime
    result = preparation.synthesize("Hello", RunSettings(tts_device=requested), output)
    assert ("placement", {"device": actual, "dtype": "float32"}) in calls
    assert result["provenance"]["device"] == actual
    assert result["provenance"]["dtype"] == "float32"
    synchronizations = [call for call in calls if call[0] == "synchronize"]
    assert synchronizations == ([] if actual == "cpu" else [("synchronize", actual)] * 3)
    trace = json.loads((output / "telemetry.json").read_text())
    for name in ("tts.model_load", "tts.synthesis"):
        span = next(span for span in trace["spans"] if span["name"] == name)
        assert span["attributes"]["device"] == actual
        assert span["status"] == "ok" and span["duration_ns"] > 0
    for filename, rate in (("original.wav", 24000), ("input.wav", 16000)):
        with wave.open(str(output / filename)) as audio:
            assert audio.getframerate() == rate
            assert audio.getnframes() > 0


@pytest.mark.parametrize("available,device,message", [
    (False, "cuda:0", "CUDA was requested"),
    (True, "cuda:2", "not visible"),
])
def test_unavailable_gpu_fails_without_loading_cpu_model(model_runtime, available, device, message):
    calls, cuda, output = model_runtime
    cuda.is_available = lambda: available
    with pytest.raises(RuntimeError, match=message):
        preparation.synthesize("Hello", RunSettings(tts_device=device), output)
    assert not calls
    assert not (output / "input.wav").exists()
