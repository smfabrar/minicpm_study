"""Restart ownership checks with process doubles and real shell startup fixtures."""

import fcntl
import os
import shlex
import shutil
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "restart_native.sh"
STOP_CODE = SCRIPT.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


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
    monkeypatch.setitem(sys.modules, "psutil", fake)
    clock = iter(range(0, 200, 20))
    monkeypatch.setitem(sys.modules, "time", types.SimpleNamespace(
        monotonic=lambda: next(clock), sleep=lambda seconds: None,
    ))
    monkeypatch.setattr(sys, "argv", ["-", str(root)])
    exec(compile(STOP_CODE, str(SCRIPT), "exec"), {})
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
        "def wait_procs(items, timeout): return ([], [])\n"
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    if shutil.which("flock") is None:
        # Exercise an actual file lock on macOS, where the Linux flock CLI is absent.
        flock = tools / "flock"
        flock.write_text(f"#!{sys.executable}\nimport fcntl, sys\n"
                         "try: fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                         "except BlockingIOError: sys.exit(1)\n")
        flock.chmod(0o755)
    env = dict(os.environ, PYTHONPATH=str(modules), PATH=str(tools) + os.pathsep + os.environ["PATH"])
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
        result = subprocess.run(["bash", SCRIPT, root], env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert "Native services started" in result.stdout
        assert (root / "logs/native-service.log.previous").read_text() == "previous diagnostics\n"
        pid = int((root / "logs/native.pid").read_text())
        os.kill(pid, 0)
        # The detached process must not retain the restart lock descriptor.
        with (root / "logs/native-restart.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        pid_file = root / "logs/native.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_failed_launcher_reports_its_log(installed_runtime):
    root, env = installed_runtime
    launcher = root / "bin/start_native.sh"
    launcher.write_text('#!/usr/bin/env bash\necho "fixture startup failure" >&2\nexit 12\n')
    launcher.chmod(0o755)
    result = subprocess.run(["bash", SCRIPT, root], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "Native launcher exited" in result.stderr
    assert "fixture startup failure" in result.stderr


def test_concurrent_restart_is_rejected_before_stopping(installed_runtime):
    root, env = installed_runtime
    launcher = root / "bin/start_native.sh"
    launcher.write_text('#!/usr/bin/env bash\nexit 99\n')
    launcher.chmod(0o755)
    (root / "logs").mkdir()
    with (root / "logs/native-restart.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(["bash", SCRIPT, root], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "Another native restart" in result.stderr
    assert "Stopping" not in result.stdout
