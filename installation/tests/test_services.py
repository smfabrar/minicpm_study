"""Restart ownership checks with process doubles and real shell startup fixtures."""

import fcntl
import importlib.util
import os
import shlex
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "restart.sh"
spec = importlib.util.spec_from_file_location("services_fixture", SCRIPT.parent / "internal/services.py")
services = importlib.util.module_from_spec(spec)
# The local CPU test environment need not install runtime dependencies.
previous = sys.modules.get("psutil")
sys.modules["psutil"] = types.SimpleNamespace()
spec.loader.exec_module(services)
if previous is None:
    del sys.modules["psutil"]
else:
    sys.modules["psutil"] = previous


def test_stop_targets_selected_installation_and_descendants(tmp_path, monkeypatch):
    root = tmp_path / "runtime with spaces"
    calls = []

    class Process:
        def __init__(self, pid, args, cwd=None, children=(), stubborn=False):
            self.pid = pid
            self.info = {"cmdline": args, "cwd": cwd}
            self.descendants = children
            self.stubborn = stubborn
            self.stopped = False

        def children(self, recursive):
            assert recursive
            return self.descendants

        def terminate(self):
            calls.append(("terminate", self.pid))
            self.stopped = not self.stubborn

        def kill(self):
            calls.append(("kill", self.pid))
            self.stubborn = False
            self.stopped = True

        def is_running(self):
            # A zombie can still be present in the container's process table.
            return True

        def status(self):
            return "zombie" if self.stopped else "running"

    child = Process(11, ["helper"])
    launcher = Process(10, ["python", "/repo/launch_native.py", "--logs", str(root / "logs/native-old")], children=[child])
    backend = Process(12, [str(root / "sources/llama.cpp-omni/build/bin/llama-omni-server")], stubborn=True)
    demo = root / "sources/MiniCPM-o-Demo"
    worker = Process(13, ["python", "worker.py"], cwd=str(demo))
    gateway = Process(14, ["python", str(demo / "gateway.py")], cwd=str(demo))
    study = Process(20, ["python", "/venv/bin/speech-study"], cwd=str(root))
    pipeline = Process(21, ["python", "-m", "tool_pipeline.service.worker"], cwd=str(root))
    other = Process(22, ["python", "/repo/launch_native.py", "--logs", str(tmp_path / "other/logs/native-old")])
    other_worker = Process(23, ["python", "worker.py"], cwd=str(tmp_path / "other/demo"))
    processes = [launcher, backend, worker, gateway, study, pipeline, other, other_worker]
    fake = types.SimpleNamespace(
        process_iter=lambda fields: processes,
        STATUS_ZOMBIE="zombie",
        NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError,
    )
    monkeypatch.setattr(services, "psutil", fake)
    clock = iter(range(0, 200, 20))
    monkeypatch.setattr(services.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    services.Services(root).stop("native")
    assert {pid for action, pid in calls if action == "terminate"} == {10, 11, 12, 13, 14}
    assert calls.index(("terminate", 11)) < calls.index(("terminate", 10))
    assert ("kill", 12) in calls


@pytest.fixture
def installed_runtime(tmp_path):
    root = tmp_path / "runtime with spaces"
    (root / "bin").mkdir(parents=True)
    (root / "venv/bin").mkdir(parents=True)
    python = root / "venv/bin/python"
    python.write_text(f'#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    modules = tmp_path / "modules"
    modules.mkdir()
    # Shell fixtures contain no running native processes; matching is checked above.
    (modules / "psutil.py").write_text(
        "def process_iter(fields): return []\n"
        "STATUS_ZOMBIE = 'zombie'\n"
        "NoSuchProcess = ProcessLookupError\n"
        "AccessDenied = PermissionError\n"
        "class Process:\n"
        "    def __init__(self, pid): self.pid = pid\n"
        "    def is_running(self): return True\n"
        "    def status(self): return 'running'\n"
    )
    env = dict(os.environ, PYTHONPATH=str(modules))
    return root, env


def test_restart_detaches_launcher_and_preserves_previous_log(installed_runtime):
    root, env = installed_runtime
    launcher = root / "bin/start_native.sh"
    launcher.write_text('#!/usr/bin/env bash\nset -eu\n'
                        'root="$(cd "$(dirname "$0")/.." && pwd)"\n'
                        'mkdir -p "$root/logs/native-fixture-$$"\n'
                        'echo "{}" >"$root/logs/native-fixture-$$/manifest.json"\n'
                        'exec sleep 60\n')
    launcher.chmod(0o755)
    (root / "logs").mkdir()
    (root / "logs/native-service.log").write_text("previous diagnostics\n")
    try:
        result = subprocess.run(["bash", SCRIPT, root, "native"], env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert "native: ready" in result.stdout
        assert (root / "logs/native-service.log.previous").read_text() == "previous diagnostics\n"
        pid = int(next((root / "logs").glob("native-fixture-*" )).name.rsplit("-", 1)[1])
        os.kill(pid, 0)
        # The detached process must not retain the restart lock descriptor.
        with (root / "logs/services.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        manifests = list((root / "logs").glob("native-fixture-*"))
        if manifests:
            try:
                os.kill(int(manifests[0].name.rsplit("-", 1)[1]), signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_failed_launcher_reports_its_log(installed_runtime):
    root, env = installed_runtime
    launcher = root / "bin/start_native.sh"
    launcher.write_text('#!/usr/bin/env bash\necho "fixture startup failure" >&2\nexit 12\n')
    launcher.chmod(0o755)
    result = subprocess.run(["bash", SCRIPT, root, "native"], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "native launcher exited" in result.stderr
    assert "fixture startup failure" in result.stderr


def test_concurrent_restart_is_rejected_before_stopping(installed_runtime):
    root, env = installed_runtime
    launcher = root / "bin/start_native.sh"
    launcher.write_text('#!/usr/bin/env bash\nexit 99\n')
    launcher.chmod(0o755)
    (root / "logs").mkdir()
    with (root / "logs/services.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(["bash", SCRIPT, root, "native"], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "Another service command" in result.stderr
    assert "Stopping" not in result.stdout


def test_repeated_start_does_not_launch_duplicate(tmp_path, monkeypatch, capsys):
    manager = services.Services(tmp_path)
    monkeypatch.setattr(manager, "processes", lambda name: [object()])
    monkeypatch.setattr(manager, "ready", lambda name, processes: True)
    monkeypatch.setattr(services.subprocess, "Popen", lambda *a, **kw: pytest.fail("duplicate launch"))
    manager.start("study")
    assert "already running" in capsys.readouterr().out


def test_partial_stack_is_not_claimed_ready(tmp_path, monkeypatch):
    manager = services.Services(tmp_path)
    monkeypatch.setattr(manager, "processes", lambda name: [object()])
    monkeypatch.setattr(manager, "ready", lambda name, processes: False)
    with pytest.raises(RuntimeError, match="existing processes but is not ready"):
        manager.start("native")


def test_runtime_stop_does_not_match_other_installations_or_command_substrings(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    executable = str(root / "venv/bin/speech-runtime")
    class Process:
        def __init__(self, pid, args):
            self.pid = pid
            self.info = {"cmdline": args, "cwd": str(root)}
        def children(self, recursive):
            return []
    matching = Process(1, ["python", executable])
    processes = [matching, Process(2, ["python", executable + "-other"]),
                 Process(3, ["python", str(tmp_path / "other/venv/bin/speech-runtime")]),
                 Process(4, ["editor", f"notes about {executable}"])]
    fake = types.SimpleNamespace(process_iter=lambda fields: processes,
                                 NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
    monkeypatch.setattr(services, "psutil", fake)
    assert services.Services(root).processes("runtime") == [matching]


def test_port_owned_by_other_process_is_rejected(tmp_path, monkeypatch):
    manager = services.Services(tmp_path)
    monkeypatch.setattr(manager, "processes", lambda name: [])
    class OccupiedSocket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect_ex(self, address): return 0
    monkeypatch.setattr(services.socket, "socket", OccupiedSocket)
    with pytest.raises(RuntimeError, match="Port 8765 is occupied"):
        manager.start("study")
