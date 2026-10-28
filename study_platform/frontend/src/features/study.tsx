import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Lock, Copy, Play, Download, ArrowUpRight } from 'lucide-react';
import { api } from '@/lib/api';
import type { Study, Analysis as AnalysisData } from '@/lib/types';
import { useAction } from '@/hooks/use-data';
import { milliseconds, memory, shortDate } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { ErrorNotice, Status } from '@/components/shared';
import { StudySettings } from './study-settings';
import { Cases } from './cases';
import { Tools } from './tools';
export function StudyPage() {
  const { id = '' } = useParams();
  const [deleting, setDeleting] = useState(false);
  const action = useAction();
  const navigate = useNavigate();
  const query = useQuery({ queryKey: ['study', id], queryFn: () => api.study(id), refetchInterval: 4000 });
  if (query.isPending)
    return <p>Loading study…</p>;
  if (!query.data)
    return <ErrorNotice error={query.error} />;
  const study = query.data;
  return <div className="space-y-6">
    <div className="page-heading">
      <div>
        <div className="mb-3 flex items-center gap-3">
          <Link className="text-sm text-muted-foreground hover:text-foreground" to="/">Studies</Link>
          <span className="text-muted-foreground">/</span>
          <Status value={study.status} />
        </div>
        <h1>
          {study.name}
        </h1>
        <p className="text-muted-foreground">
          {study.description || 'Compare native speech, predicted tools, and oracle context.'}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline"><a href={`/api/studies/${id}/export`}><Download className="size-4" /> Export ZIP</a></Button>
        <Button asChild variant="outline"><Link to={`/operations?study_id=${id}`}>Operations</Link></Button>
        <Button variant="outline" onClick={() => setDeleting(true)}>Delete study</Button>
        <Button variant="outline" disabled={action.isPending} onClick={() => action.mutate(async () => { const clone = await api.request<Study>(`/studies/${id}/clone`, 'POST'); navigate(`/studies/${clone.id}`); })}><Copy className="size-4" /> Clone</Button>
        {study.status === 'draft' ? <Button disabled={action.isPending || !study.cases.length} onClick={() => action.mutate(() => api.request(`/studies/${id}/freeze`, 'POST'))}><Lock className="size-4" /> Freeze study</Button> : <Button disabled={action.isPending} onClick={() => action.mutate(() => api.request(`/studies/${id}/matrix`, 'POST'))}><Play className="size-4" /> Run full matrix</Button>}
      </div>
    </div>
    <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">B0 · Native speech <span className="mx-4">/</span> B1 · Whisper → caller → tools → native injection <span className="mx-4">/</span> B2 · Oracle → native injection</div>
    <Dialog open={deleting} onOpenChange={setDeleting}><DialogContent><DialogHeader><DialogTitle>Move {study.name} to Trash?</DialogTitle><DialogDescription>Recordings, metadata and run history will be retained. Restore the study from the dashboard. Finish this study's queued work first.</DialogDescription></DialogHeader><div className="flex gap-2"><Button variant="outline" onClick={() => setDeleting(false)}>Cancel</Button><Button variant="destructive" disabled={action.isPending} onClick={() => action.mutate(async () => { await api.request(`/studies/${id}`, 'DELETE'); navigate('/'); })}>Move to Trash</Button></div></DialogContent></Dialog>
    <Tabs defaultValue="cases">
      <TabsList className="mb-5">
        <TabsTrigger value="cases">Cases ({study.cases.length})</TabsTrigger>
        <TabsTrigger value="tools">Tools ({study.tools.length})</TabsTrigger>
        <TabsTrigger value="runs">Runs ({study.runs.length})</TabsTrigger>
        <TabsTrigger value="analysis">Analysis</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
      <TabsContent value="cases">
        <Cases study={study} />
      </TabsContent>
      <TabsContent value="tools">
        <Tools study={study} />
      </TabsContent>
      <TabsContent value="runs">
        <Runs study={study} />
      </TabsContent>
      <TabsContent value="analysis">
        <Analysis studyId={id} />
      </TabsContent>
      <TabsContent value="settings">
        <StudySettings key={`${id}-${study.status}`} study={study} />
      </TabsContent>
    </Tabs>
  </div>;
}
function Runs({ study }: {
  study: Study;
}) {
  return <Card>
    <CardHeader>
      <CardTitle>Run history</CardTitle>
      <CardDescription>Draft runs support development. Freeze the study before collecting evaluation results.</CardDescription>
    </CardHeader>
    <CardContent>
      {study.runs.length ? <Table>
        <TableHeader>
          <TableRow>
            {['Case', 'Condition', 'Status', 'Review', 'Started', ''].map(label => <TableHead key={label}>
              {label}
            </TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {study.runs.map(run => <TableRow key={run.id}>
            <TableCell className="max-w-80 truncate">
              {run.snapshot.cases.find(item => item.id === run.case_id)?.question || run.case_id}
            </TableCell>
            <TableCell>
              {run.condition}
            </TableCell>
            <TableCell>
              <Status value={run.status} />
            </TableCell>
            <TableCell>
              {run.review?.verdict || 'unreviewed'}
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {shortDate(run.created_at)}
            </TableCell>
            <TableCell>
              <Button asChild size="sm" variant="ghost">
                <Link to={`/runs/${run.id}`}>Inspect <ArrowUpRight className="size-4" /></Link>
              </Button>
            </TableCell>
          </TableRow>)}
        </TableBody>
      </Table> : <p className="py-8 text-center text-muted-foreground">No runs yet. Prepare audio in Cases, then run a condition.</p>}
    </CardContent>
  </Card>;
}
function Analysis({ studyId }: {
  studyId: string;
}) {
  const query = useQuery({ queryKey: ['analysis', studyId], queryFn: () => api.analysis(studyId), refetchInterval: 5000 });
  if (!query.data)
    return <ErrorNotice error={query.error} />;
  const report: AnalysisData = query.data;
  return <div className="space-y-5">
    <div className="flex items-center justify-between">
      <p className="text-sm text-muted-foreground">{report.pending} queued or running · human-reviewed spoken correctness</p>
      <Button asChild variant="outline">
        <a href={`/api/studies/${studyId}/export`}><Download className="size-4" /> Export study</a>
      </Button>
    </div>
    <div className="grid gap-4 md:grid-cols-3">
      {report.conditions.map(row => <Card key={row.condition}>
        <CardHeader>
          <CardDescription>{row.condition} · spoken accuracy</CardDescription>
          <CardTitle className="text-3xl">
            {row.spoken_accuracy === null ? '—' : `${(row.spoken_accuracy * 100).toFixed(1)}%`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="mb-4 h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary" style={{ width: `${(row.spoken_accuracy ?? 0) * 100}%` }} />
          </div>
          <p className="text-sm text-muted-foreground">{row.confirmed_correct} confirmed correct / {row.primary_attempts} eligible attempts</p>
          <p className="mt-2 text-xs text-muted-foreground">{row.unreviewed} unreviewed · {row.failed} failed · {row.silent} silent</p>
        </CardContent>
      </Card>)}
    </div>
    <Card>
      <CardHeader>
        <CardTitle>Timing and resource observations</CardTitle>
        <CardDescription>Per-condition observations. Initialization and output transcription have separate traces.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              {['Condition', 'Attempts', 'Median first audio', 'Peak process RSS', 'Unnecessary tool calls'].map(label => <TableHead key={label}>
                {label}
              </TableHead>)}
            </TableRow>
          </TableHeader>
          <TableBody>
            {report.conditions.map(row => <TableRow key={row.condition}>
              <TableCell>
                {row.condition}
              </TableCell>
              <TableCell>
                {row.attempted}
              </TableCell>
              <TableCell>
                {milliseconds(row.median_first_audio_ms)}
              </TableCell>
              <TableCell>
                {memory(row.peak_observed_rss_bytes)}
              </TableCell>
              <TableCell>{row.unnecessary_calls} / {row.no_tool_attempts}</TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
    <div className="space-y-2 text-sm text-muted-foreground">
      {report.notes.map(note => <p key={note}>
        {note}
      </p>)}
    </div>
  </div>;
}
