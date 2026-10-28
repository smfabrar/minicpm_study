import type { Settings } from './types';

export type CallerBackend = 'granite' | 'qwen3';

export function callerSettings(settings: Settings) {
  const backend = settings.caller_backend === 'qwen3' ? 'qwen3' : 'granite';
  return {
    backend,
    model: String(settings.caller_model || (backend === 'granite'
      ? settings.granite_model || 'ibm-granite/granite-4.0-350m' : 'Qwen/Qwen3-1.7B')),
    revision: String(settings.caller_revision || (backend === 'granite' ? settings.granite_revision || 'main' : 'main')),
    device: String(settings.caller_device || settings.granite_device || 'cuda:0'),
    quantization: String(settings.caller_quantization || 'none'),
  };
}

export function selectCaller(settings: Settings, backend: CallerBackend): Settings {
  return {
    ...settings,
    caller_backend: backend,
    caller_model: backend === 'qwen3' ? 'Qwen/Qwen3-1.7B'
      : String(settings.granite_model || 'ibm-granite/granite-4.0-350m'),
    caller_revision: backend === 'qwen3' ? 'main' : String(settings.granite_revision || 'main'),
    caller_device: callerSettings(settings).device,
    caller_quantization: 'none',
  };
}

export function parseStudySettings(text: string): Settings {
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Runtime settings must be a JSON object.');
  }
  if (Object.values(value).some(item => !['string', 'number', 'boolean'].includes(typeof item))) {
    throw new Error('Each runtime setting must be text, a number, or a boolean.');
  }

  // Tokenize whole strings so quoted text inside a value cannot look like a key.
  const tokens = text.match(/"(?:\\.|[^"\\])*"|:/g) ?? [];
  const keys = new Set<string>();
  for (let index = 0; index < tokens.length - 1; index++) {
    if (tokens[index + 1] !== ':') continue;
    const key: string = JSON.parse(tokens[index]);
    if (keys.has(key)) throw new Error(`Duplicate setting "${key}". Keep one entry for each setting.`);
    keys.add(key);
  }
  return value as Settings;
}

export function verifySavedSettings(expected: Settings, persisted: Settings): void {
  const changed = Object.keys(expected).filter(key => expected[key] !== persisted[key]);
  if (changed.length) {
    throw new Error(`Save verification failed for: ${changed.join(', ')}. Reload the study before trying again.`);
  }
}
