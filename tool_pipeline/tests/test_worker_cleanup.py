"""Exercise real worker/process-group cleanup with an explicit ownership fixture."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from tool_pipeline.service.jobs import JobManager


def test_stopping_runtime_worker_kills_separate_python_tool_group(tmp_path, monkeypatch):
    source = '''import json, os, subprocess, sys, time
def execute(arguments):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(json.dumps({"pid": os.getpid(), "child": child.pid}), flush=True)
    time.sleep(60)
    return "late"
'''
    definition = {'name': 'clock', 'description': 'Get time', 'kind': 'python', 'parameter': 'query',
                  'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
                  'python_code': source, 'timeout_seconds': 60}
    request = tmp_path / 'definition.json'
    request.write_text(json.dumps(definition))
    program = '''import asyncio, json, sys
from pathlib import Path
from tool_pipeline.tools import ToolRegistry
from tool_pipeline.telemetry import TraceRecorder
registry = ToolRegistry([json.loads(Path(sys.argv[1]).read_text())], TraceRecorder(), Path(sys.argv[2]))
asyncio.run(registry.execute("clock", {}, "What time?"))
'''
    output = tmp_path / 'run'
    parent = subprocess.Popen([sys.executable, '-c', program, str(request), str(output)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    owned = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            logs = list(output.glob('*.log'))
            if logs and logs[0].read_text().strip():
                owned = json.loads(logs[0].read_text().splitlines()[0])
                break
            time.sleep(0.02)
        assert owned is not None
        assert os.getpgid(owned['pid']) == owned['pid']
        assert os.getpgid(owned['child']) == owned['pid']
        # Local venv lacks psutil. Supply only ownership enumeration; termination is real.
        children = [SimpleNamespace(pid=pid, kill=lambda pid=pid: os.kill(pid, signal.SIGKILL))
                    for pid in (owned['pid'], owned['child'])]
        def process(identifier):
            assert identifier == parent.pid
            return SimpleNamespace(children=lambda recursive: children)
        monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=process, NoSuchProcess=ProcessLookupError))
        JobManager._stop_worker(parent)
        assert parent.poll() is not None
        for pid in owned.values():
            deadline = time.monotonic() + 3
            running = True
            while time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    running = False
                    break
                # Minimal container init processes may retain a dead orphan as a zombie.
                stat = Path(f"/proc/{pid}/stat")
                if stat.is_file() and stat.read_text().split(")", 1)[1].split()[0] == "Z":
                    running = False
                    break
                time.sleep(0.02)
            assert not running, f'Owned process {pid} still running'
    finally:
        if parent.poll() is None:
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait()
        if owned:
            try:
                os.killpg(owned['pid'], signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_runtime_log_endpoint_returns_bounded_artifacts_and_requires_token(tmp_path):
    from fastapi.testclient import TestClient
    from tool_pipeline.service.api import create_app

    identifier = 'a' * 32
    directory = tmp_path / identifier
    directory.mkdir()
    (directory / 'job.json').write_text(json.dumps({'id': identifier, 'kind': 'inference', 'status': 'complete'}))
    (directory / 'worker.log').write_text('x' * 50000 + 'tail evidence')
    (directory / 'tool-output.log').write_text('function stdout')
    client = TestClient(create_app(tmp_path, token='test-token'))
    assert client.get(f'/jobs/{identifier}/logs').status_code == 403
    response = client.get(f'/jobs/{identifier}/logs', headers={'Authorization': 'Bearer test-token'})
    assert response.status_code == 200
    logs = response.json()
    assert len(logs['worker.log'].encode()) <= 32768
    assert logs['worker.log'].endswith('tail evidence')
    assert logs['tool-output.log'] == 'function stdout'
    assert client.get('/jobs/bad-id/logs', headers={'Authorization': 'Bearer test-token'}).status_code == 404
