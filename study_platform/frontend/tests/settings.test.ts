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
