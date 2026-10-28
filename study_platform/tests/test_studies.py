"""CPU integration checks for API, persistence and experiment boundaries."""
import io
import tempfile
import unittest
import wave
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from speech_study.app import create_app
from speech_study.domain.models import Condition, Review, RunStatus
from speech_study.infrastructure.unit_of_work import UnitOfWork


def recording():
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(32000))
    return output.getvalue()


class StudyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app(Path(self.directory.name))
        # Do not start background execution: these checks inspect persisted requests.
        self.client = TestClient(self.app)
        self.services = self.app.state.services
        self.study = self.client.post('/api/studies', json={'name': 'Room experiment'}).json()
        self.base = '/api/studies/' + self.study['id']

    def case(self, category='room', split='evaluation'):
        response = self.client.post(self.base + '/cases', json={'question': 'Where is the robotics seminar?', 'category': category, 'split': split, 'expected_answer': 'B742', 'oracle_result': 'Room B742'})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def prepared_case(self, category='room', split='evaluation'):
        case = self.case(category, split)
        response = self.client.post(f"{self.base}/cases/{case['id']}/audio", files={'audio': ('input.wav', recording(), 'audio/wav')})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def start(self, case, conditions):
        with patch('speech_study.services.runs.RuntimeClient.health', return_value={'status': 'ready'}):
            response = self.client.post(self.base + '/runs', json={'case_id': case['id'], 'conditions': conditions})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_partial_settings_preserve_gpu_configuration(self):
        self.client.put(self.base, json={'settings': {'reference_audio': '/server/voice.wav', 'granite_device': 'cuda:0', 'tts_device': 'cuda:0'}})
        result = self.client.put(self.base, json={'settings': {'seed': 99}})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['settings']['reference_audio'], '/server/voice.wav')
        self.assertEqual(result.json()['settings']['granite_device'], 'cuda:0')
        self.assertEqual(result.json()['settings']['tts_device'], 'cuda:0')
        self.assertEqual(result.json()['settings']['seed'], 99)
        self.assertEqual(self.client.put(self.base, json={'settings': {'unknown': 1}}).status_code, 400)

    def test_reference_settings_persist_per_study_after_backend_restart(self):
        other = self.client.post('/api/studies', json={'name': 'Second study'}).json()
        references = {self.study['id']: '/server/first.wav', other['id']: '/server/second.wav'}
        for study_id, reference in references.items():
            response = self.client.put('/api/studies/' + study_id, json={'settings': {'reference_audio': reference}})
            self.assertEqual(response.status_code, 200, response.text)
        restarted = TestClient(create_app(Path(self.directory.name)))
        for study_id, reference in references.items():
            self.assertEqual(restarted.get('/api/studies/' + study_id).json()['settings']['reference_audio'], reference)
        item = self.prepared_case()
        for run in self.start(item, ['B0', 'B1', 'B2']):
            self.assertEqual(run['request']['settings']['reference_audio'], '/server/first.wav')

    def test_freeze_checks_audio_and_locks_cases(self):
        self.case()
        self.assertEqual(self.client.post(self.base + '/freeze').status_code, 400)
        other = self.client.post('/api/studies', json={'name': 'Ready'}).json()
        self.base = '/api/studies/' + other['id']
        item = self.prepared_case()
        self.assertEqual(self.client.post(self.base + '/freeze').status_code, 200)
        self.assertEqual(self.client.put(self.base + '/cases/' + item['id'], json={'question': 'Changed'}).status_code, 409)
        self.assertEqual(self.client.put(self.base, json={'name': 'Changed'}).status_code, 409)

    def test_qwen_settings_survive_restart_clone_and_frozen_run_request(self):
        settings = {
            'caller_backend': 'qwen3', 'caller_model': 'Qwen/Qwen3-1.7B',
            'caller_revision': 'qwen-sha', 'caller_device': 'cuda:0',
        }
        response = self.client.put(self.base, json={'settings': settings})
        self.assertEqual(response.status_code, 200, response.text)
        restarted = TestClient(create_app(Path(self.directory.name)))
        saved = restarted.get(self.base).json()['settings']
        for key, value in settings.items():
            self.assertEqual(saved[key], value)
        item = self.prepared_case()
        self.assertEqual(self.client.post(self.base + '/freeze').status_code, 200)
        run = self.start(item, ['B1'])[0]
        for key, value in settings.items():
            self.assertEqual(run['request']['settings'][key], value)
        self.assertEqual(self.client.put(self.base, json={'settings': {'caller_backend': 'granite'}}).status_code, 409)
        clone = self.client.post(self.base + '/clone').json()
        self.assertEqual(clone['settings']['caller_backend'], 'qwen3')
        self.assertEqual(clone['settings']['caller_revision'], 'qwen-sha')
        self.assertEqual(self.client.put('/api/studies/' + clone['id'], json={'settings': {'caller_backend': 'unsupported'}}).status_code, 400)

    def test_conditions_reuse_identical_audio_and_do_not_leak_answers(self):
        item = self.prepared_case()
        runs = self.start(item, ['B0', 'B1', 'B2'])
        self.assertEqual(len({run['request']['audio_sha256'] for run in runs}), 1)
        b1 = next(run['request'] for run in runs if run['condition'] == 'B1')
        for key in ['oracle_result', 'expected_answer', 'question', 'category', 'expected_tool']:
            self.assertNotIn(key, b1)
        self.assertEqual(next(run['request'] for run in runs if run['condition'] == 'B2')['oracle_result'], 'Room B742')
        no_tool = self.prepared_case('none')
        self.assertIsNone(self.start(no_tool, ['B2'])[0]['request']['oracle_result'])

    def test_clone_copies_cases_and_tools_without_run_history(self):
        item = self.prepared_case()
        self.start(item, ['B0'])
        clone = self.client.post(self.base + '/clone').json()
        detail = self.client.get('/api/studies/' + clone['id']).json()
        self.assertEqual(len(detail['cases']), 1)
        self.assertNotEqual(detail['cases'][0]['id'], item['id'])
        self.assertEqual(detail['runs'], [])
        self.assertEqual(len(detail['tools']), 3)

    def test_development_runs_do_not_enter_frozen_evaluation(self):
        development = self.prepared_case(split='development')
        evaluation = self.prepared_case()
        self.client.post(self.base + '/freeze')
        runs = self.start(development, ['B0']) + self.start(evaluation, ['B0'])
        with UnitOfWork(self.services.runs.database) as work:
            for item in runs:
                run = work.runs.get(item['id'])
                run.status = RunStatus.COMPLETE
                run.review = Review(verdict='correct')
                work.runs.save(run)
        report = self.client.get(self.base + '/analysis').json()['conditions'][0]
        self.assertEqual(report['attempted'], 2)
        self.assertEqual(report['evaluation_attempts'], 1)
        self.assertEqual(report['primary_attempts'], 1)
        self.assertEqual(report['confirmed_correct'], 1)

    def test_matrix_checks_health_once_and_preserves_seed_order(self):
        self.prepared_case()
        self.client.post(self.base + '/freeze')
        with patch('speech_study.services.runs.RuntimeClient.health', return_value={}) as health:
            response = self.client.post(self.base + '/matrix')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(health.call_count, 1)
        self.assertEqual({run['condition'] for run in response.json()}, {'B0', 'B1', 'B2'})

    def test_audio_mutation_and_artifact_traversal_are_rejected(self):
        item = self.prepared_case()
        self.services.artifacts.write(item['audio_path'], b'changed')
        self.assertEqual(self.client.post(self.base + '/freeze').status_code, 400)
        with self.assertRaises(ValueError):
            self.services.artifacts.resolve('../study.sqlite')

    def test_case_ownership_and_review_update(self):
        item = self.prepared_case()
        other = self.client.post('/api/studies', json={'name': 'Other'}).json()
        self.assertEqual(self.client.put(f"/api/studies/{other['id']}/cases/{item['id']}", json={'question': 'Overwrite'}).status_code, 404)
        run = self.start(item, ['B0'])[0]
        for verdict in ['incorrect', 'correct']:
            self.assertEqual(self.client.put('/api/runs/' + run['id'] + '/review', json={'verdict': verdict}).status_code, 200)
        self.assertEqual(self.client.get('/api/runs/' + run['id']).json()['review']['verdict'], 'correct')
        self.assertEqual(len(self.client.get(self.base).json()['runs']), 1)
