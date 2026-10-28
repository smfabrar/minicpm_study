import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { Run, Review } from '@/lib/types';
import { api } from '@/lib/api';
import { useAction } from '@/hooks/use-data';
import { artifactUrl, milliseconds, memory } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { FieldGroup } from '@/components/ui/field';
import { Status, ErrorNotice, Choice, FormField, JsonView } from '@/components/shared';
import { Timeline } from './timeline';
export function RunPage() {
  const { id = '' } = useParams();
  const action = useAction();
  const query = useQuery({ queryKey: ['run', id], queryFn: () => api.run(id), refetchInterval: 2500 });
  const trace = useQuery({ queryKey: ['telemetry', id], queryFn: () => api.telemetry(id), refetchInterval: query.data && ['running', 'queued'].includes(query.data.status) ? 2000 : false, retry: false });
  useEffect(() => {
    if (query.data && !['queued', 'running'].includes(query.data.status)) void trace.refetch();
  }, [query.data?.status]);
  if (query.isPending)
    return <p>Loading run…</p>;
  if (!query.data)
    return <ErrorNotice error={query.error} />;
  const run = query.data;
  const metrics = run.result?.metrics;
  const item = run.snapshot.cases.find(item => item.id === run.case_id);
  return <div className="space-y-6">
    <div className="page-heading">
      <div>
        <Link className="text-sm text-muted-foreground" to={`/studies/${run.study_id}`}>← Study</Link>
        <div className="mt-3 flex items-center gap-3">
          <h1>{run.condition} run</h1>
          <Status value={run.status} />
        </div>
        <p className="mt-2 max-w-3xl text-muted-foreground">
          {item?.question}
        </p>
      </div>
      {run.status === 'interrupted' && <Button disabled={action.isPending} onClick={() => action.mutate(() => api.request(`/runs/${id}/resume`, 'POST'))}>Resume collection</Button>}
    </div>
    {run.error && <ErrorNotice error={new Error(run.error)} />}
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[['First audio', milliseconds(metrics?.input_start_to_first_audio_ms)], ['Inference elapsed', milliseconds(metrics?.pipeline_elapsed_ms)], ['Peak runtime RSS', memory(metrics?.memory?.observed_peak_rss_bytes)], ['Peak runtime GPU', memory(metrics?.memory?.observed_peak_process_gpu_bytes)]].map(([label, value]) => <Card key={label}>
        <CardHeader>
          <CardDescription>
            {label}
          </CardDescription>
          <CardTitle className="text-2xl tabular-nums">
            {value}
          </CardTitle>
        </CardHeader>
      </Card>)}
    </div>
    <Tabs defaultValue="review">
      <TabsList className="mb-5">
        <TabsTrigger value="review">Audio & review</TabsTrigger>
        <TabsTrigger value="timeline">Timeline & memory</TabsTrigger>
        <TabsTrigger value="tools">Tool path</TabsTrigger>
        <TabsTrigger value="provenance">Request & provenance</TabsTrigger>
      </TabsList>
      <TabsContent value="review">
        <ContextObservation run={run} />
        <AudioReview key={run.id} run={run} />
      </TabsContent>
      <TabsContent value="timeline">
        {trace.data ? <Timeline trace={trace.data} /> : <p className="text-muted-foreground">Telemetry is available when the runtime starts recording.</p>}
      </TabsContent>
      <TabsContent value="tools">
        <div className="space-y-5">
          <ContextObservation run={run} />
          <Card>
            <CardHeader>
              <CardTitle>Tool decisions and injection</CardTitle>
              <CardDescription>Captured runtime events, including validation, execution, submission, and native evaluation acknowledgements.</CardDescription>
            </CardHeader>
            <CardContent>
              <JsonView value={{ input_transcript: run.result?.input_transcript, caller_action: run.result?.caller_action, tool_result: run.result?.tool_result, tool_error: run.result?.tool_error, context_submitted: run.result?.context_submitted, context_evaluated: run.result?.context_evaluated, missing_evaluation_acks: run.result?.missing_evaluation_acks }} />
            </CardContent>
          </Card>
          {trace.data?.events.filter(event => /tool|oracle|context|caller/.test(event.name)).map((event, index) => <Card key={index}>
            <CardHeader>
              <CardTitle className="text-sm">
                {event.name}
              </CardTitle>
              <CardDescription>{milliseconds((event.at_ns - trace.data!.origin_ns) / 1e6)} after trace origin</CardDescription>
            </CardHeader>
            <CardContent>
              <JsonView value={event.attributes} />
            </CardContent>
          </Card>)}
        </div>
      </TabsContent>
      <TabsContent value="provenance">
        <div className="space-y-5">
          <JsonView value={run.request} />
          <JsonView value={run.result} />
          {run.artifact_directory && <Button asChild variant="outline">
            <a href={artifactUrl(`${run.artifact_directory}/trace.chrome.json`)} download>Download Chrome trace</a>
          </Button>}
        </div>
      </TabsContent>
    </Tabs>
  </div>;
}
function AudioReview({ run }: {
  run: Run;
}) {
  const [review, setReview] = useState<Review>(run.review ?? { verdict: 'unreviewed', heard_transcript: '', notes: '', relevant_fact_ms: null });
  const action = useAction();
  const output = typeof run.result?.output_audio === 'string' && run.artifact_directory ? `${run.artifact_directory}/${run.result.output_audio.split('/').pop()}` : null;
  const item = run.snapshot.cases.find(item => item.id === run.case_id);
  return <div className="grid gap-5 xl:grid-cols-2">
    <Card>
      <CardHeader>
        <CardTitle>Spoken output</CardTitle>
        <CardDescription>Listen to the actual generated audio before scoring correctness.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {output ? <audio className="w-full" controls preload="metadata" src={artifactUrl(output)} /> : <p className="text-muted-foreground">No output audio has been collected.</p>}
        <div>
          <p className="mb-2 text-sm font-medium">Output ASR</p>
          <p className="whitespace-pre-wrap rounded-md bg-muted/40 p-4 text-sm">
            {run.output_transcript || 'No transcription yet.'}
          </p>
          <Button className="mt-3" size="sm" variant="outline" disabled={!output || action.isPending} onClick={() => action.mutate(() => api.request(`/runs/${run.id}/transcribe`, 'POST'))}>Transcribe output audio</Button>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Model text</p>
          <p className="whitespace-pre-wrap text-sm text-muted-foreground">
            {typeof run.result?.assistant_text === 'string' ? run.result.assistant_text : '—'}
          </p>
        </div>
        <div className="border-t pt-4">
          <p className="mb-2 text-sm font-medium">Expected answer</p>
          <p className="text-sm text-muted-foreground">
            {item?.expected_answer || 'Not specified'}
          </p>
        </div>
      </CardContent>
    </Card>
    <Card>
      <CardHeader>
        <CardTitle>Listening review</CardTitle>
        <CardDescription>Your verdict supplies the spoken correctness measure. ASR is supporting evidence.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={event => { event.preventDefault(); action.mutate(() => api.request(`/runs/${run.id}/review`, 'PUT', { verdict: review.verdict, heard_transcript: review.heard_transcript, notes: review.notes, relevant_fact_ms: review.relevant_fact_ms })); }}>
          <FieldGroup>
            <FormField label="Verdict">
              <Choice value={review.verdict} options={['unreviewed', 'correct', 'incorrect', 'partial', 'silent']} onChange={verdict => setReview({ ...review, verdict })} />
            </FormField>
            <FormField label="What you heard">
              <Textarea value={review.heard_transcript} onChange={e => setReview({ ...review, heard_transcript: e.target.value })} />
            </FormField>
            <FormField label="First relevant fact (ms from output audio start)">
              <Input type="number" min="0" value={review.relevant_fact_ms ?? ''} onChange={e => setReview({ ...review, relevant_fact_ms: e.target.value === '' ? null : Number(e.target.value) })} />
            </FormField>
            <FormField label="Review notes">
              <Textarea value={review.notes} onChange={e => setReview({ ...review, notes: e.target.value })} />
            </FormField>
            <Button disabled={action.isPending}>Save review</Button>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  </div>;
}

function ContextObservation({ run }: { run: Run }) {
  const observation = run.result?.context_observation;
  if (!observation || observation.status === 'not_submitted') return null;
  const labels: Record<string, string> = {
    not_evaluated: 'Context submitted; evaluation not confirmed',
    evaluated_no_new_text: 'Evaluated but no new answer text',
    evaluated_with_new_text: 'New text received after evaluation',
    unavailable: 'Context observation unavailable',
  };
  const audio = observation.output_audio && run.artifact_directory
    ? artifactUrl(`${run.artifact_directory}/${observation.output_audio.split('/').pop()}`) : null;
  const expected = run.snapshot.cases.find(item => item.id === run.case_id)?.expected_answer;
  return <Card className="mb-5">
    <CardHeader>
      <CardTitle>{labels[observation.status] ?? observation.status}</CardTitle>
      <CardDescription>Run completion means collection finished. Spoken correctness is scored separately.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-3 text-sm">
      <p>Fact or guidance evaluated: {observation.evaluated === undefined ? 'Unknown' : observation.evaluated ? 'Yes' : 'No'}</p>
      <p>New text after evaluation: {observation.new_text === undefined ? 'Unknown' : observation.new_text || 'None recorded'}</p>
      <p>Audio received after evaluation: {observation.audio_chunks ?? 'Unknown'} chunks · {milliseconds(observation.audio_duration_ms)}</p>
      <p>Observation after evaluation: {milliseconds(observation.observation_ms ?? undefined)}</p>
      {observation.window_completed === false && <p>Observation window interrupted; this is partial evidence.</p>}
      {observation.clip_error && <p>Interval audio unavailable: {observation.clip_error}</p>}
      {audio && <audio className="w-full" controls preload="metadata" src={audio} />}
      <p className="text-muted-foreground">This audio can include buffered speech from before injection. Listen and use the review below to confirm whether the expected fact was spoken.</p>
      <p>Expected spoken answer: {expected || 'Not specified'}</p>
      <p>Spoken correctness (listening review): {run.review?.verdict ?? 'unreviewed'}</p>
      {observation.error && <p>{observation.error}</p>}
    </CardContent>
  </Card>;
}
