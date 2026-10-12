"""CPU checks for setup safety and generated shell commands; no GPU results."""

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import types
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


def load_script(name):
    specification = importlib.util.spec_from_file_location(name, PROJECT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


setup = load_script("setup_cuda125")
support = load_script("gpu_setup_support")


def configuration(tmp_path, **overrides):
    values = dict(root=tmp_path / "runtime", reference=tmp_path / "reference",
                  cuda_home=tmp_path / "cuda-12.5", jobs=2, architectures=None,
                  install_system_deps=False, download_models=True, dry_run=False)
    return setup.SetupConfiguration(**(values | overrides))


def git(directory, *args, check=True):
    return subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
                          text=True, check=check)


def repository(directory):
    directory.mkdir()
    git(directory, "init")
    git(directory, "config", "user.email", "fixture@example.invalid")
    git(directory, "config", "user.name", "Setup fixture")
    (directory / "source.txt").write_text("original\n")
    git(directory, "add", "source.txt")
    git(directory, "commit", "-m", "Fixture source")
    return git(directory, "rev-parse", "HEAD").stdout.strip()


def test_dry_run_does_not_create_installation(tmp_path):
    root = tmp_path / "must stay absent"
    result = subprocess.run([sys.executable, PROJECT / "scripts/setup_cuda125.py", "--dry-run",
                             "--with-platform", "--root", root], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "no files, packages or services will be changed" in result.stdout
    assert "separate venv" in result.stdout
    assert not root.exists()


def test_architecture_selection_rejects_unsupported_or_excluded_gpus(tmp_path):
    devices = [{"architecture": "80"}, {"architecture": "86"}]
    assert setup.select_architectures(None, devices, "sm_75\nsm_80\nsm_86") == "80;86"
    with pytest.raises(ValueError, match="cannot compile"):
        setup.select_architectures(None, [{"architecture": "100"}], "sm_80\nsm_90")
    with pytest.raises(ValueError, match="must include"):
        setup.select_architectures("80", devices, "sm_80\nsm_86")


def test_source_verification_preserves_real_index_and_rejects_extra_edits(tmp_path):
    directory = tmp_path / "native"
    revision = repository(directory)
    (directory / "source.txt").write_text("patched\n")
    patch = tmp_path / "context.patch"
    patch.write_text(git(directory, "diff").stdout)
    index_before = (directory / ".git/index").read_bytes()
    builder = setup.NativeBuilder(configuration(tmp_path), setup.CommandRunner(dict(os.environ)))
    builder.verify_changes(directory, revision, patch)
    builder.verify_changes(directory, revision, patch)
    assert (directory / ".git/index").read_bytes() == index_before
    assert (directory / "source.txt").read_text() == "patched\n"
    (directory / "source.txt").write_text("patched\nunexpected\n")
    with pytest.raises(RuntimeError, match="Unexpected tracked source changes"):
        builder.verify_changes(directory, revision, patch)
    assert git(directory, "rev-parse", "HEAD").stdout.strip() == revision
    assert (directory / ".git/index").read_bytes() == index_before


def test_existing_checkout_with_different_revision_is_never_reset(tmp_path):
    directory = tmp_path / "native"
    original = repository(directory)
    (directory / "source.txt").write_text("user work\n")
    builder = setup.NativeBuilder(configuration(tmp_path), setup.CommandRunner(dict(os.environ)))
    with pytest.raises(RuntimeError, match="different revision"):
        builder.checkout(directory, "https://example.invalid/never-fetch", "0" * 40)
    assert git(directory, "rev-parse", "HEAD").stdout.strip() == original
    assert (directory / "source.txt").read_text() == "user work\n"


@pytest.mark.parametrize("initialized", [False, True])
def test_checkout_resumes_after_interrupted_directory_or_git_initialization(tmp_path, initialized):
    origin = tmp_path / "origin"
    revision = repository(origin)
    directory = tmp_path / "interrupted"
    directory.mkdir()
    if initialized:
        git(directory, "init")
    builder = setup.NativeBuilder(configuration(tmp_path), setup.CommandRunner(dict(os.environ)))
    builder.checkout(directory, str(origin), revision)
    builder.checkout(directory, str(origin), revision)
    assert git(directory, "rev-parse", "HEAD").stdout.strip() == revision
    assert git(directory, "remote", "get-url", "origin").stdout.strip() == str(origin)
    assert (directory / "source.txt").read_text() == "original\n"


def test_generated_runtime_script_preserves_literal_paths_and_existing_environment(tmp_path):
    root = tmp_path / "runtime $(touch SHOULD_NOT_EXIST) 'quoted'"
    config = configuration(tmp_path, root=root)
    binary = root / "venv/bin"
    binary.mkdir(parents=True)
    (binary / "activate").write_text("export SETUP_ACTIVATED=yes\n")
    recorder = binary / "speech-runtime"
    recorder.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                        "print(json.dumps({'args': sys.argv[1:], 'hf': os.environ['HF_HOME'], "
                        "'libs': os.environ['LD_LIBRARY_PATH'], 'active': os.environ['SETUP_ACTIVATED']}))\n")
    recorder.chmod(0o755)
    setup.LaunchFiles(config, setup.CommandRunner(dict(os.environ))).write(
        {"library_paths": [str(root / "cublas/lib"), str(root / "cudnn/lib")], "devices": []}, None)
    result = subprocess.run(["bash", root / "bin/start_runtime.sh"], cwd=tmp_path,
                            env=dict(os.environ, LD_LIBRARY_PATH="/existing/libs"),
                            capture_output=True, text=True, check=True)
    recorded = json.loads(result.stdout)
    assert recorded["args"] == ["--host", "127.0.0.1", "--port", "8766", "--data", str(root / "data/runtime")]
    assert recorded["hf"] == str(root / "models/cache")
    assert recorded["libs"].endswith(":/existing/libs")
    assert recorded["active"] == "yes"
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert not (root / "bin/start_native.sh").exists()


def test_interrupted_download_retains_model_pin(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    resolved = []
    downloads = []
    interrupted = True

    class HubAPI:
        def model_info(self, repository):
            resolved.append(repository)
            return types.SimpleNamespace(sha="a" * 40)

    def snapshot(repository, revision, allow_patterns):
        nonlocal interrupted
        downloads.append((repository, revision))
        if interrupted:
            interrupted = False
            raise OSError("Interrupted fixture download")
        location = root / repository.replace("/", "-")
        location.mkdir(exist_ok=True)
        if repository == "openbmb/MiniCPM-o-4_5-gguf":
            for name in support.GGUF_FILES:
                path = location / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"layout fixture, not model weights")
        return str(location)

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(
        HfApi=HubAPI, snapshot_download=snapshot))
    with pytest.raises(OSError, match="Interrupted"):
        support.download_models(root)
    assert json.loads((root / "model-revisions.json").read_text())["native"]["revision"] == "a" * 40
    result = support.download_models(root)
    assert len(result) == 4
    assert resolved.count("openbmb/MiniCPM-o-4_5-gguf") == 1
    assert downloads[0] == downloads[1]


def test_settings_use_server_paths_and_one_gpu_device(tmp_path):
    patch = tmp_path / "patch"
    patch.write_text("fixture patch")
    models = {name: {"path": f"/srv/models/{name}", "revision": "a" * 40}
              for name in ("granite", "whisper", "tts")}
    settings = support.run_settings(models, Path("/srv/demo"), patch, 1)
    assert settings["granite_device"] == "cuda:0"
    assert settings["whisper_device_index"] == 0
    assert settings["tts_device"] == "cuda:0"
    assert settings["reference_audio"] == "/srv/demo/assets/ref_audio/ref_en_dlc_1.wav"
    assert settings["tts_revision"] == "a" * 40
    assert support.run_settings(models, Path("/srv/demo"), patch, 2)["granite_device"] == "cuda:1"
    assert support.run_settings(models, Path("/srv/demo"), patch, 2)["tts_device"] == "cuda:1"


def test_generated_native_and_study_scripts_have_valid_shell_and_frozen_settings(tmp_path):
    config = configuration(tmp_path, root=tmp_path / "runtime with spaces", with_platform=True)
    config.python.parent.mkdir(parents=True)
    config.python.write_text(f'#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} "$@"\n')
    config.python.chmod(0o755)
    config.patch.parent.mkdir(parents=True)
    config.patch.write_text("fixture patch")
    models = {name: {"path": str(tmp_path / f"{name} model"), "revision": "a" * 40}
              for name in ("native", "granite", "whisper", "tts")}
    setup.LaunchFiles(config, setup.CommandRunner(dict(os.environ))).write(
        {"library_paths": ["/fixture/cublas/lib", "/fixture/cudnn/lib"], "devices": [{}]}, models)
    for path in (config.root / "bin").glob("*.sh"):
        subprocess.run(["bash", "-n", path], check=True)
    restart_script = (config.root / "bin/restart_native.sh").read_text()
    assert "restart_native.sh" in restart_script
    assert shlex.quote(str(config.root)) in restart_script
    settings = json.loads((config.root / "run-settings.json").read_text())
    assert settings["granite_model"] == models["granite"]["path"]
    assert settings["granite_device"] == "cuda:0"
    assert settings["tts_revision"] == "a" * 40
    study_script = (config.root / "bin/start_study.sh").read_text()
    assert "study-venv/bin/speech-study" in study_script
    assert "activate.sh" not in study_script
    assert "LD_LIBRARY_PATH" not in study_script
    study_binary = config.root / "study-venv/bin/speech-study"
    study_binary.parent.mkdir(parents=True)
    study_binary.write_text(f'#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
    study_binary.chmod(0o755)
    launched = subprocess.run(["bash", config.root / "bin/start_study.sh"],
                              env=dict(os.environ, SPEECH_STUDY_PORT="8080"),
                              capture_output=True, text=True, check=True)
    assert json.loads(launched.stdout) == ["--data", str(config.root / "data/platform"), "--port", "8080"]
