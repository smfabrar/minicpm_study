import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAction } from '@/hooks/use-data';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { FormField, Status, JsonView } from '@/components/shared';
export function RuntimePage() {
  const query = useQuery({ queryKey: ['runtime'], queryFn: api.runtime, refetchInterval: 15000 });
  const [url, setUrl] = useState('');
  const action = useAction();
  return <div className="space-y-6">
    <div>
      <p className="eyebrow">Compute connection</p>
      <h1>Inference runtime</h1>
      <p className="text-muted-foreground">One submission contains the saved audio and frozen configuration. The GPU runtime owns every inference step.</p>
    </div>
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Remote service</CardTitle>
          <Status value={query.data?.online ? 'online' : 'offline'} />
        </div>
        <CardDescription>Use an SSH tunnel to the GPU server. Bearer tokens come from the platform environment variable SPEECH_RUNTIME_TOKEN.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); action.mutate(() => api.request('/runtime', 'PUT', { url: url || query.data?.url })); }}>
          <div className="min-w-72 flex-1">
            <FormField label="Runtime URL">
              <Input type="url" value={url || query.data?.url || ''} onChange={e => setUrl(e.target.value)} required />
            </FormField>
          </div>
          <Button disabled={action.isPending}>Save connection</Button>
          <Button type="button" variant="outline" onClick={() => query.refetch()}>Check health</Button>
        </form>
        <JsonView value={query.data ?? { status: 'checking' }} />
      </CardContent>
    </Card>
    <Card>
      <CardHeader>
        <CardTitle>Server setup</CardTitle>
        <CardDescription>See the project README for installation, pinned native backend setup, and GPU validation.</CardDescription>
      </CardHeader>
      <CardContent>
        <pre className="overflow-auto rounded-md bg-muted p-4 text-xs leading-7">
          {'# On the GPU server\nspeech-runtime --host 127.0.0.1 --port 8766 --data ./runtime-data\n\n# On this computer\nssh -L 8766:127.0.0.1:8766 your-gpu-server\n\n# In Study → Settings\n# Set reference_audio to a WAV path on the GPU server.\n# Set native_url and Granite / Whisper devices for your server.'}
        </pre>
      </CardContent>
    </Card>
  </div>;
}
