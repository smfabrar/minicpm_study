"""Regression checks for the independently deployable study distribution."""
import subprocess
import sys
import tomllib
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
CONTRACTS = PROJECT.parent / 'speech_contracts' / 'src'


def test_study_loads_with_pipeline_and_model_imports_blocked():
    program = f'''
import importlib.abc
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, {str(CONTRACTS)!r})
sys.path.insert(0, {str(PROJECT / 'src')!r})
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'tool_pipeline', 'duplex_tools', 'torch', 'kokoro', 'transformers', 'faster_whisper'}}:
            raise AssertionError('Unexpected execution dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from fastapi.testclient import TestClient
from speech_study.app import create_app
with tempfile.TemporaryDirectory() as directory:
    with TestClient(create_app(Path(directory))) as client:
        study = client.post('/api/studies', json={{'name': 'Independent'}}).json()
        assert len(client.get('/api/studies/' + study['id']).json()['tools']) == 3
        assert client.post('/api/studies/' + study['id'] + '/template').json()['case_count'] == 48
'''
    result = subprocess.run([sys.executable, '-I', '-c', program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_study_distribution_has_no_model_extra_or_runtime_entry_points():
    configuration = tomllib.loads((PROJECT / 'pyproject.toml').read_text())['project']
    assert set(configuration['scripts']) == {'speech-study'}
    assert 'models' not in configuration.get('optional-dependencies', {})
    dependencies = ' '.join(configuration['dependencies'])
    for name in ('tool-pipeline', 'torch', 'transformers', 'kokoro', 'faster-whisper', 'websockets'):
        assert name not in dependencies
    assert not (PROJECT / 'src/speech_study/runtime').exists()
