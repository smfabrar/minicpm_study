"""Repository update dispatch and decoder verification; no GPU/model downloads."""

import importlib.util
import subprocess
import sys
import types
import wave
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_support_fixture", PROJECT / "internal/gpu_setup_support.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def test_decoder_check_uses_temporary_pcm_recording(monkeypatch):
    recordings = []

    def decode_audio(path, sampling_rate):
        recordings.append(Path(path))
        with wave.open(path) as audio:
            assert audio.getframerate() == sampling_rate == 16000
            assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
            return [0.0] * audio.getnframes()

    monkeypatch.setitem(sys.modules, "faster_whisper.audio", types.SimpleNamespace(decode_audio=decode_audio))
    monkeypatch.setattr(support.importlib.metadata, "version", lambda name: "fixture")
    result = support.verify_audio_decoder()
    assert result["sample_count"] == 1600
    assert not recordings[0].exists()


def test_incompatible_decoder_error_is_not_hidden(monkeypatch):
    def decode_audio(*args, **kwargs):
        raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

    monkeypatch.setitem(sys.modules, "faster_whisper.audio", types.SimpleNamespace(decode_audio=decode_audio))
    with pytest.raises(TypeError, match="metadata_errors"):
        support.verify_audio_decoder()


def test_update_reuses_installer_options_without_changes(tmp_path):
    result = subprocess.run(["bash", PROJECT / "update.sh", "--dry-run", "--prefix", str(tmp_path / "absent")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Dry run: no changes" in result.stdout
    assert not (tmp_path / "absent").exists()
