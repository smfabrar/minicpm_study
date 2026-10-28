import assert from 'node:assert/strict';
import test from 'node:test';
import { parseStudySettings, verifySavedSettings } from '../src/lib/settings.ts';

test('rejects duplicate reference paths instead of silently choosing the empty value', () => {
  assert.throws(() => parseStudySettings('{"reference_audio":"/server/voice.wav","reference_audio":""}'), /Duplicate setting/);
});

test('detects duplicate keys expressed with Unicode escapes', () => {
  assert.throws(() => parseStudySettings('{"reference_audio":"a","reference_\\u0061udio":"b"}'), /Duplicate setting/);
});

test('accepts quoted key-like text inside the system prompt', () => {
  const settings = { reference_audio: '/server/voice.wav', system_prompt: 'Use "reference_audio": "example" as text.' };
  assert.deepEqual(parseStudySettings(JSON.stringify(settings)), settings);
});

test('rejects arrays and nested settings', () => {
  assert.throws(() => parseStudySettings('[]'), /JSON object/);
  assert.throws(() => parseStudySettings('{"seed":{}}'), /Each runtime setting/);
});

test('does not report success if the backend readback lost the reference path', () => {
  assert.throws(() => verifySavedSettings({ reference_audio: '/server/voice.wav' }, { reference_audio: '' }), /reference_audio/);
});

test('accepts a verified save with server-provided additional defaults', () => {
  verifySavedSettings({ reference_audio: '/server/voice.wav' }, { reference_audio: '/server/voice.wav', seed: 42 });
});

test('switches a legacy study to Qwen without losing GPU or reference settings', async () => {
  const { callerSettings, selectCaller } = await import('../src/lib/settings.ts');
  const legacy = { granite_model: '/models/granite', granite_revision: 'granite-sha', granite_device: 'cuda:0', reference_audio: '/server/voice.wav' };
  assert.equal(callerSettings(legacy).model, '/models/granite');
  const qwen = parseStudySettings(JSON.stringify(selectCaller(legacy, 'qwen3')));
  assert.deepEqual(callerSettings(qwen), { backend: 'qwen3', model: 'Qwen/Qwen3-1.7B', revision: 'main', device: 'cuda:0' });
  assert.equal(qwen.reference_audio, '/server/voice.wav');
  const granite = selectCaller(qwen, 'granite');
  assert.deepEqual(callerSettings(granite), { backend: 'granite', model: '/models/granite', revision: 'granite-sha', device: 'cuda:0' });
});

test('explicit caller fields override legacy defaults after save readback', async () => {
  const { callerSettings } = await import('../src/lib/settings.ts');
  const settings = { caller_backend: 'qwen3', caller_model: '/models/qwen', caller_revision: 'qwen-sha', caller_device: 'cpu', granite_device: 'cuda:0' };
  assert.deepEqual(callerSettings(settings), { backend: 'qwen3', model: '/models/qwen', revision: 'qwen-sha', device: 'cpu' });
  assert.throws(() => verifySavedSettings(settings, { ...settings, caller_backend: 'granite' }), /caller_backend/);
});
