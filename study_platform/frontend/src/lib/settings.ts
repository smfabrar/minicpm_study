import type { Settings } from './types';

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
