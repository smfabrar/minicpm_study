import { useEffect, useRef, useState } from 'react';
import { Mic, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { encodeRecording } from '@/lib/recording';
import { useAction } from '@/hooks/use-data';

export function VoiceRecorder({ endpoint }: { endpoint: string }) {
  const [recording, setRecording] = useState(false);
  const [preview, setPreview] = useState<{ blob: Blob; url: string } | null>(null);
  const [error, setError] = useState('');
  const action = useAction();
  const capture = useRef<{ stream: MediaStream; context: AudioContext; node?: AudioWorkletNode; chunks: Float32Array[] } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = useRef(false);
  const attempt = useRef(0);
  const mounted = useRef(true);

  function release() {
    attempt.current += 1;
    active.current = false;
    if (timer.current) clearTimeout(timer.current);
    capture.current?.stream.getTracks().forEach(track => track.stop());
    capture.current?.node?.disconnect();
    void capture.current?.context.close();
    capture.current = null;
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; release(); }; }, []);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);

  function stop() {
    const session = capture.current;
    if (!session) { release(); setRecording(false); return; }
    const blob = encodeRecording(session.chunks, session.context.sampleRate);
    release();
    setRecording(false);
    if (blob.size > 44) setPreview({ blob, url: URL.createObjectURL(blob) });
    else setError('No microphone audio was captured. Try recording again.');
  }

  async function start() {
    if (active.current) return;
    active.current = true;
    const id = ++attempt.current;
    setError('');
    setPreview(null);
    setRecording(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone recording requires HTTPS or localhost.');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 }, video: false });
      if (!mounted.current || id !== attempt.current) { stream.getTracks().forEach(track => track.stop()); return; }
      const context = new AudioContext();
      const session = { stream, context, chunks: [] as Float32Array[], node: undefined as AudioWorkletNode | undefined };
      capture.current = session;
      const source = new Blob([`class Capture extends AudioWorkletProcessor {
        process(inputs) { if (inputs[0]?.[0]) this.port.postMessage(inputs[0][0]); return true; }
      } registerProcessor('voice-capture', Capture);`], { type: 'application/javascript' });
      const url = URL.createObjectURL(source);
      try { await context.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
      if (id !== attempt.current) { stream.getTracks().forEach(track => track.stop()); void context.close(); return; }
      const node = new AudioWorkletNode(context, 'voice-capture');
      session.node = node;
      node.port.onmessage = event => { if (id === attempt.current) session.chunks.push(new Float32Array(event.data)); };
      context.createMediaStreamSource(stream).connect(node);
      // Processor outputs silence, keeping capture active without microphone feedback.
      node.connect(context.destination);
      await context.resume();
      if (id === attempt.current) timer.current = setTimeout(stop, 120000);
    } catch (exc) {
      if (id !== attempt.current) return;
      release();
      if (mounted.current) { setRecording(false); setError(String(exc)); }
    }
  }

  return <div className="flex flex-wrap items-center gap-2">
    <Button variant="outline" size="sm" disabled={action.isPending} onClick={recording ? stop : start}>
      {recording ? <Square className="size-4" /> : <Mic className="size-4" />}
      {recording ? 'Stop recording' : 'Record voice'}
    </Button>
    {recording && <span role="status" className="text-xs">Recording · maximum 2 minutes</span>}
    {preview && <><audio controls className="h-9 max-w-full" src={preview.url} />
      <Button size="sm" disabled={action.isPending} onClick={() => action.mutate(async () => {
        const body = new FormData(); body.append('audio', preview.blob, 'recording.wav');
        await api.request(`${endpoint}?origin=recorded`, 'POST', body);
        setPreview(null);
      })}>Use recording</Button>
      <Button variant="ghost" size="sm" onClick={() => setPreview(null)}>Discard</Button></>}
    {(error || action.error) && <p role="alert" className="text-sm text-destructive">{error || String(action.error)}</p>}
  </div>;
}
