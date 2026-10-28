import test from 'node:test';
import assert from 'node:assert/strict';
import { encodeRecording } from '../src/lib/recording.ts';

test('microphone samples encode to mono PCM16 WAV with clipping', async () => {
  const wav = encodeRecording([new Float32Array([-2, 0]), new Float32Array([0.5, 2])], 48000);
  const buffer = await wav.arrayBuffer();
  const view = new DataView(buffer);
  assert.equal(wav.type, 'audio/wav');
  assert.equal(buffer.byteLength, 52);
  assert.equal(view.getUint32(24, true), 48000);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(40, true), 8);
  assert.equal(view.getInt16(44, true), -32768);
  assert.equal(view.getInt16(46, true), 0);
  assert.equal(view.getInt16(48, true), 16384);
  assert.equal(view.getInt16(50, true), 32767);
});
