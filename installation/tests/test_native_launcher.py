"""Launcher path regression checks; no native models or GPU execution."""

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_launcher_fixture", PROJECT / "internal/launch_native.py")
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)


@pytest.mark.parametrize("relative", [False, True])
def test_cli_preserves_snapshot_model_path_for_companion_modules(tmp_path, monkeypatch, relative):
    blobs = tmp_path / "hub/blobs"
    snapshot = tmp_path / "hub/snapshots/pinned"
    blobs.mkdir(parents=True)
    (snapshot / "tts").mkdir(parents=True)
    main_blob = blobs / "main-hash"
    tts_blob = blobs / "tts-hash"
    main_blob.write_bytes(b"fixture, not model weights")
    tts_blob.write_bytes(b"fixture, not model weights")
    model = snapshot / "MiniCPM-o-4_5-Q4_K_M.gguf"
    model.symlink_to(main_blob)
    companion = snapshot / "tts/MiniCPM-o-4_5-tts-F16.gguf"
    companion.symlink_to(tts_blob)
    captured = []

    class Stack:
        def __init__(self, config):
            captured.append(config)

        def start(self):
            pass

        def close(self):
            pass

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, "NativeStack", Stack)
    argument = model.relative_to(tmp_path) if relative else model
    monkeypatch.setattr(sys, "argv", [
        "launch_native.py", "--model", str(argument), "--upstream", "native",
        "--demo", "demo", "--patch", "context.patch", "--logs", "logs",
    ])
    launcher.main()
    config = captured[0]
    assert config.model == model
    assert config.model.is_absolute() and config.model.is_symlink()
    assert (config.model.parent / "tts/MiniCPM-o-4_5-tts-F16.gguf").is_file()
    assert not (model.resolve().parent / "tts/MiniCPM-o-4_5-tts-F16.gguf").exists()
    assert config.upstream == (tmp_path / "native").resolve()


def test_cli_keeps_regular_model_file_path(tmp_path, monkeypatch):
    model = tmp_path / "MiniCPM-o-4_5-Q4_K_M.gguf"
    model.write_bytes(b"fixture, not model weights")
    captured = []
    monkeypatch.setattr(launcher.NativeStack, "start", lambda stack: captured.append(stack.config))
    monkeypatch.setattr(launcher.NativeStack, "close", lambda stack: None)
    monkeypatch.setattr(sys, "argv", [
        "launch_native.py", "--model", str(model), "--upstream", str(tmp_path),
        "--demo", str(tmp_path), "--patch", str(tmp_path / "patch"), "--logs", str(tmp_path / "logs"),
    ])
    launcher.main()
    assert captured[0].model == model
