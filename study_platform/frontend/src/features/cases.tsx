import { VoiceRecorder } from './voice-recorder';
import { useState } from 'react';
import { Plus, Pencil, Upload, Volume2, Play, Trash2 } from 'lucide-react';
import type { Study, StudyCase } from '@/lib/types';
import { api } from '@/lib/api';
import { artifactUrl } from '@/lib/utils';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldGroup } from '@/components/ui/field';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Choice, FormField, ErrorNotice } from '@/components/shared';
const emptyCase = { question: '', category: 'none', split: 'development', expected_answer: '', oracle_result: '', oracle_mode: 'fixed', expected_tool: '', expected_arguments: {}, notes: '' };
export function Cases({ study }: {
  study: Study;
}) {
  const action = useAction();
  const [editing, setEditing] = useState<StudyCase | typeof emptyCase | null>(null);
  const [argumentsText, setArgumentsText] = useState('{}');
  const [condition, setCondition] = useState('all');
  const [deletingAudio, setDeletingAudio] = useState<StudyCase | null>(null);
  const frozen = study.status === 'frozen';
  const base = `/studies/${study.id}`;
  const editingNumber = editing && 'id' in editing
    ? study.cases.findIndex(item => item.id === editing.id) + 1
    : null;
  const deletingAudioNumber = deletingAudio
    ? study.cases.findIndex(item => item.id === deletingAudio.id) + 1
    : null;
  function edit(value: StudyCase | typeof emptyCase) { setArgumentsText(JSON.stringify(value.expected_arguments, null, 2)); setEditing({ ...value }); }
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground">{study.cases.length} cases · one saved audio input reused across all conditions</p>
      <div className="flex gap-2">
        {!frozen && <><Button variant="outline" disabled={action.isPending} onClick={() => action.mutate(async () => {
          for (const item of study.cases.filter(item => !item.audio_path))
            await api.request(`${base}/cases/${item.id}/prepare`, 'POST');
        })}><Volume2 className="size-4" /> Prepare missing audio</Button><Button onClick={() => edit(emptyCase)}><Plus className="size-4" /> Add case</Button></>}
        <div className="w-24">
          <Choice value={condition} options={['all', 'B0', 'B1', 'B2']} onChange={setCondition} />
        </div>
      </div>
    </div>
    {study.cases.length === 0 && <Card>
      <CardContent className="py-12 text-center">
        <p className="mb-4 text-muted-foreground">Add a case or load the revised 48-case starter template (room, document, server clock, web search and no-tool questions).</p>
        <Button variant="outline" disabled={action.isPending || frozen} onClick={() => action.mutate(() => api.request(`${base}/template`, 'POST'))}>Load starter template</Button>
      </CardContent>
    </Card>}
    {study.cases.map((item, index) => <Card key={item.id}>
      <CardContent className="space-y-4 pt-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex gap-2">
              <Badge variant="outline">
                {item.category}
              </Badge>
              <Badge variant="secondary">
                {item.split}
              </Badge>
            </div>
            <h3 className="font-medium leading-relaxed">
              <span className="mr-2 text-muted-foreground tabular-nums">{index + 1}.</span>
              {item.question}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">Expected: {item.oracle_mode === 'server_clock' ? 'Compare with the clock evidence saved for this run' : item.expected_answer || 'Not specified'}</p>
          </div>
          {!frozen && <div className="flex gap-1">
            <Button aria-label={`Edit question ${index + 1}`} variant="ghost" size="icon" disabled={item.audio_deletion_pending} onClick={() => edit(item)}>
              <Pencil className="size-4" />
            </Button>
            <Button aria-label={`Delete question ${index + 1}`} variant="ghost" size="icon" disabled={item.audio_deletion_pending} onClick={() => action.mutate(() => api.request(`${base}/cases/${item.id}`, 'DELETE'))}>
              <Trash2 className="size-4" />
            </Button>
          </div>}
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t pt-4">
          {item.audio_path ? <><audio className="h-9 max-w-full" controls preload="none" src={artifactUrl(item.audio_path)} /><span className="text-xs text-muted-foreground">{item.audio_origin} · {item.audio_sha256?.slice(0, 10)}</span></> : <span className="text-sm text-muted-foreground">Audio not prepared</span>}
          {!frozen && !item.audio_deletion_pending && <VoiceRecorder endpoint={`${base}/cases/${item.id}/audio`} />}
          <div className="ml-auto flex gap-2">
            {!frozen && item.audio_path && <Button variant="destructive" size="sm" disabled={action.isPending} onClick={() => setDeletingAudio(item)}><Trash2 className="size-4" />{item.audio_deletion_pending ? 'Retry audio deletion' : 'Delete audio'}</Button>}
            {!frozen && !item.audio_deletion_pending && <><Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => api.request(`${base}/cases/${item.id}/prepare`, 'POST'))}><Volume2 className="size-4" /> TTS</Button><Button asChild variant="outline" size="sm">
              <label><Upload className="size-4" /> WAV<input className="sr-only" type="file" accept="audio/wav,.wav" onChange={event => {
                const file = event.target.files?.[0]; if (file) {
                  const body = new FormData();
                  body.append('audio', file);
                  action.mutate(() => api.request(`${base}/cases/${item.id}/audio`, 'POST', body));
                } event.target.value = '';
              }} /></label>
            </Button></>}
            <Button size="sm" disabled={!item.audio_path || item.audio_deletion_pending || action.isPending} onClick={() => action.mutate(() => api.request(`${base}/runs`, 'POST', { case_id: item.id, conditions: condition === 'all' ? ['B0', 'B1', 'B2'] : [condition] }))}><Play className="size-4" /> Run {condition}</Button>
          </div>
        </div>
      </CardContent>
    </Card>)}
    <Dialog open={deletingAudio !== null} onOpenChange={open => { if (!open) setDeletingAudio(null); }}>
      <DialogContent><DialogHeader>
        <DialogTitle>Delete audio for question {deletingAudioNumber}?</DialogTitle>
        <DialogDescription>Permanently removes the original and normalized audio, preparation traces, manifests and preparation logs from Atlas and the local cache. The question stays. Shared files remain while another case, study or saved run needs them.</DialogDescription>
      </DialogHeader>
      <p className="text-sm">{deletingAudio?.question}</p>
      <ErrorNotice error={action.error} />
      <div className="flex gap-2"><Button variant="outline" onClick={() => setDeletingAudio(null)}>Cancel</Button>
        <Button variant="destructive" disabled={action.isPending} onClick={() => action.mutate(async () => {
          await api.request(`${base}/cases/${deletingAudio!.id}/audio`, 'DELETE'); setDeletingAudio(null);
        })}>{action.isPending ? 'Deleting…' : 'Delete audio and artifacts'}</Button></div>
      </DialogContent>
    </Dialog>
    <Dialog open={editing !== null} onOpenChange={open => {
      if (!open)
        setEditing(null);
    }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {editing && 'id' in editing ? `Edit question ${editingNumber}` : 'Add case'}
          </DialogTitle>
          <DialogDescription>The runtime receives audio. Expected answers and oracle facts remain study metadata; only B2 receives its oracle fact.</DialogDescription>
        </DialogHeader>
        {editing && <form onSubmit={event => { event.preventDefault(); action.mutate(async () => { const { question, category, split, expected_answer, oracle_result, expected_tool, notes, oracle_mode = 'fixed' } = editing; const payload = { question, category, split, expected_answer, oracle_result, oracle_mode, expected_tool, notes, expected_arguments: JSON.parse(argumentsText) }; await api.request(`${base}/cases${'id' in editing ? `/${editing.id}` : ''}`, 'id' in editing ? 'PUT' : 'POST', payload); setEditing(null); }); }}>
          <FieldGroup>
            <FormField label="Question / text sent to TTS">
              <Textarea required value={editing.question} onChange={e => setEditing({ ...editing, question: e.target.value })} />
            </FormField>
            <div className="grid grid-cols-2 gap-4">
              <FormField label="Category">
                <Choice value={editing.category} options={['room', 'document', 'datetime', 'web', 'none', 'custom', ...(editing.category === 'calculator' ? ['calculator'] : [])]} onChange={category => setEditing({ ...editing, category, oracle_mode: category === 'datetime' ? 'server_clock' : 'fixed', oracle_result: '' })} />
              </FormField>
              <FormField label="Dataset split">
                <Choice value={editing.split} options={['development', 'evaluation']} onChange={split => setEditing({ ...editing, split })} />
              </FormField>
            </div>
            <FormField label="Expected spoken answer">
              <Textarea value={editing.expected_answer} onChange={e => setEditing({ ...editing, expected_answer: e.target.value })} />
            </FormField>
            {editing.category === 'datetime' && <FormField label="B2 reference source">
              <Choice value={editing.oracle_mode === 'server_clock' ? 'Live server clock' : 'Saved reference fact'}
                options={['Live server clock', 'Saved reference fact']}
                onChange={source => setEditing({ ...editing, oracle_mode: source === 'Live server clock' ? 'server_clock' : 'fixed', oracle_result: '' })} />
            </FormField>}
            {editing.oracle_mode === 'server_clock' ? <p className="text-sm text-muted-foreground">B2 reads the pipeline server's clock after its configured delay, without Whisper or the tool caller. Review date, time and timezone against the saved clock evidence.</p> : <FormField label="B2 oracle fact">
              <Textarea value={editing.oracle_result} onChange={e => setEditing({ ...editing, oracle_result: e.target.value })} />
            </FormField>}
            {editing.category === 'web' && <p className="text-sm text-muted-foreground">Verify the answer from a current authoritative source before freezing. Record the source and verification date in Notes. Search excerpts may be stale or contradictory.</p>}
            <FormField label="Expected tool name">
              <Input value={editing.expected_tool} onChange={e => setEditing({ ...editing, expected_tool: e.target.value })} />
            </FormField>
            <FormField label="Expected arguments (JSON)">
              <Textarea className="font-mono text-xs" value={argumentsText} onChange={e => setArgumentsText(e.target.value)} />
            </FormField>
            <FormField label="Notes">
              <Textarea value={editing.notes} onChange={e => setEditing({ ...editing, notes: e.target.value })} />
            </FormField>
            <Button type="submit" disabled={action.isPending}>Save case</Button>
          </FieldGroup>
        </form>}
      </DialogContent>
    </Dialog>
  </div>;
}
