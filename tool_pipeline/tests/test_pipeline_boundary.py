"""The service, CLI and worker must not depend on the study application."""
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CONTRACTS = PROJECT.parent / 'speech_contracts' / 'src'


def test_pipeline_loads_with_study_imports_blocked():
    program = f'''
import importlib.abc
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, {str(CONTRACTS)!r})
sys.path.insert(0, {str(PROJECT / 'src')!r})
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'speech_study':
            raise AssertionError('Unexpected study dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from fastapi.testclient import TestClient
from tool_pipeline.service.api import create_app
from tool_pipeline.pipeline import InferencePipeline
from tool_pipeline.service.worker import main
from tool_pipeline.models.preparation import synthesize, transcribe_output
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_app(Path(directory))) as client:
        assert client.get('/health').status_code == 200
'''
    result = subprocess.run([sys.executable, '-I', '-c', program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_pipeline_declares_its_own_runtime_entry_points():
    project = tomllib.loads((PROJECT / 'pyproject.toml').read_text())['project']
    assert project['scripts']['speech-runtime'] == 'tool_pipeline.service.api:main'
    assert project['scripts']['speech-infer'] == 'tool_pipeline.cli:main'
    assert 'speech-study' not in ' '.join(project['dependencies'])
    worker_source = (PROJECT / 'src/tool_pipeline/service/jobs.py').read_text()
    assert '"tool_pipeline.service.worker"' in worker_source
    assert 'speech_study' not in worker_source


def test_core_import_does_not_load_service_or_model_libraries():
    program = '''
import importlib.abc
import sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {'fastapi', 'uvicorn', 'torch', 'transformers', 'kokoro', 'faster_whisper'}
        if fullname.startswith('tool_pipeline.service') or fullname.split('.')[0] in blocked:
            raise AssertionError('Unexpected dependency while importing core: ' + fullname)
sys.meta_path.insert(0, Boundary())
from tool_pipeline.pipeline import InferencePipeline
'''
    result = subprocess.run([sys.executable, '-I', '-c', program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_real_worker_process_uses_standalone_package_and_retains_failure(tmp_path):
    import base64
    import io
    import time
    import wave
    from tool_pipeline.service.jobs import JobManager

    audio = io.BytesIO()
    with wave.open(audio, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(32000))
    jobs = JobManager(tmp_path)
    try:
        job = jobs.create({
            'job_kind': 'inference',
            'condition': 'B0',
            'audio_base64': base64.b64encode(audio.getvalue()).decode(),
            # An intentionally absent reference file fails before any GPU/network use.
            'settings': {'reference_audio': str(tmp_path / 'missing-reference.wav')},
        })
        deadline = time.monotonic() + 15
        while job['status'] in {'queued', 'running'} and time.monotonic() < deadline:
            time.sleep(0.05)
            job = jobs.get(job['id'])
        assert job['status'] == 'failed', job
        assert 'reference_audio is not a file' in job['error']
        assert str(tmp_path / 'missing-reference.wav') in job['error']
        assert {'telemetry.json', 'result.json', 'worker.log'} <= set(job['artifacts'])
        assert job['result']['condition'] == 'B0'
    finally:
        jobs.close()
