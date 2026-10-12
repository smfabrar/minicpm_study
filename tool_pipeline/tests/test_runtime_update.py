"""Repository update dispatch and decoder verification; no GPU/model downloads."""

import importlib.util
import json
import os
import subprocess
import sys
import types
import wave
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / "update_runtime.sh"
spec = importlib.util.spec_from_file_location("update_support_fixture", PROJECT / "scripts/gpu_setup_support.py")
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


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "runtime with spaces"
    (root / "venv/bin").mkdir(parents=True)
    (root / "activate.sh").write_text("export UPDATE_ACTIVATED=yes\n")
    calls = tmp_path / "calls.jsonl"
    python = root / "venv/bin/python"
    python.write_text(f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "assert os.environ.get('UPDATE_ACTIVATED') == 'yes'\n"
        "with open(os.environ['UPDATE_CALLS'], 'a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:] == ['-m', 'pip', 'check'] and os.environ.get('FAIL_CHECK'):\n"
        "    print('fixture dependency conflict', file=sys.stderr); sys.exit(1)\n"
        "if sys.argv[1:] == ['-m', 'pip', 'freeze']: print('av==18.1.0')\n")
    python.chmod(0o755)
    return root, calls, dict(os.environ, UPDATE_CALLS=str(calls))


def test_updater_uses_committed_configuration_and_verifies_before_reporting_success(installation):
    root, calls, env = installation
    result = subprocess.run(["bash", SCRIPT, root], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    install = commands[0]
    assert install[:3] == ["-m", "pip", "install"]
    assert install[install.index("-c") + 1] == str(PROJECT / "scripts/constraints-cuda125.txt")
    assert str(PROJECT.parent / "speech_contracts") == str(Path(install[install.index("-e") + 1]).resolve())
    assert str(PROJECT) + "[models]" in install
    assert commands[1] == ["-m", "pip", "check"]
    assert commands[2] == [str(PROJECT / "scripts/gpu_setup_support.py"), "verify-audio"]
    assert commands[3] == ["-m", "pip", "freeze"]
    assert (root / "requirements-resolved.txt").read_text() == "av==18.1.0\n"
    assert "audio decoding verified" in result.stdout


def test_updater_stops_after_dependency_check_failure(installation):
    root, calls, env = installation
    result = subprocess.run(["bash", SCRIPT, root], env=env | {"FAIL_CHECK": "1"},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "fixture dependency conflict" in result.stderr
    assert len(calls.read_text().splitlines()) == 2
    assert not (root / "requirements-resolved.txt").exists()
    assert "audio decoding verified" not in result.stdout
