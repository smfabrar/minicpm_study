import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { shortDate } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/table';
import { ErrorNotice, JsonView, Status } from '@/components/shared';

export function OperationsPage() {
  const [params] = useSearchParams();
  const studyId = params.get('study_id');
  const query = useQuery({ queryKey: ['operations'], queryFn: api.operations, refetchInterval: 3000 });
  const all = query.data ?? [];
  const operations = studyId ? all.filter(operation => operation.payload.study_id === studyId) : all;
  const active = operations.filter(operation => ['queued', 'running'].includes(operation.status));
  const waiting = active.filter(operation => operation.status === 'queued').sort((a, b) => (a.queue_position ?? 0) - (b.queue_position ?? 0));
  const running = active.filter(operation => operation.status === 'running');
  const completed = operations.filter(operation => !['queued', 'running'].includes(operation.status));
  return <div className="space-y-6">
    <div className="page-heading"><div><h1>Operations</h1><p className="text-muted-foreground">{running.length} running · {waiting.length} waiting. Preparation, inference and transcription run serially.</p></div>{studyId && <Button asChild variant="outline"><Link to="/operations">Show all studies</Link></Button>}</div>
    <ErrorNotice error={query.error} />
    <Card><CardHeader><CardTitle>Queue and history</CardTitle><CardDescription>All active work and the latest 100 finished operations. Open an operation for its request, progress and logs.</CardDescription></CardHeader>
      <CardContent>{operations.length ? <Table><TableHeader><TableRow>{['Order', 'Operation', 'Request', 'Status', 'Progress', 'Created', ''].map(label => <TableHead key={label}>{label}</TableHead>)}</TableRow></TableHeader><TableBody>
        {[...running, ...waiting, ...completed].map(operation => <TableRow key={operation.id}>
          <TableCell>{operation.queue_position ?? (operation.status === 'running' ? 'Now' : '—')}</TableCell>
          <TableCell>{operation.kind}<p className="font-mono text-[10px] text-muted-foreground">{operation.id.slice(0, 8)}</p></TableCell>
          <TableCell className="max-w-64"><div className="truncate">{operation.payload.question ?? operation.payload.condition ?? operation.payload.run_id?.slice(0, 8) ?? '—'}</div>{operation.payload.study_id && <Link className="text-xs text-muted-foreground underline" to={`/studies/${operation.payload.study_id}`}>Study {operation.payload.study_id.slice(0, 8)}</Link>}</TableCell>
          <TableCell><Status value={operation.status} /></TableCell><TableCell className="max-w-72 break-words text-xs">{operation.message}</TableCell><TableCell className="whitespace-nowrap text-xs text-muted-foreground">{shortDate(operation.created_at)}</TableCell>
          <TableCell><Button asChild variant="ghost" size="sm"><Link to={`/operations/${operation.id}`}>Inspect</Link></Button></TableCell>
        </TableRow>)}
      </TableBody></Table> : <p className="py-8 text-center text-muted-foreground">No operations yet.</p>}</CardContent>
    </Card>
  </div>;
}

export function OperationPage() {
  const { id = '' } = useParams();
  const query = useQuery({ queryKey: ['operation', id], queryFn: () => api.operation(id), refetchInterval: 3000 });
  const operation = query.data;
  if (!operation) return <ErrorNotice error={query.error} />;
  return <div className="space-y-6">
    <Link className="text-sm text-muted-foreground underline" to="/operations">All operations</Link>
    <div className="page-heading"><div><h1>{operation.kind}</h1><p className="mt-2 font-mono text-xs text-muted-foreground">{operation.id}</p><p className="mt-3">{operation.message}</p></div><Status value={operation.status} /></div>
    <ErrorNotice error={query.error} />
    <div className="grid gap-4 sm:grid-cols-3">{[['Queued', operation.created_at], ['Started', operation.started_at], ['Finished', operation.finished_at]].map(([label, value]) => <Card key={label}><CardHeader><CardDescription>{label}</CardDescription><CardTitle className="text-sm">{value ? shortDate(value) : '—'}</CardTitle></CardHeader></Card>)}</div>
    <div className="flex gap-3">{operation.payload.run_id && <Button asChild variant="outline"><Link to={`/runs/${operation.payload.run_id}`}>Inspect run</Link></Button>}{operation.payload.study_id && <Button asChild variant="outline"><Link to={`/studies/${operation.payload.study_id}`}>Open study</Link></Button>}</div>
    <Card><CardHeader><CardTitle>Request and runtime job</CardTitle><CardDescription>{operation.remote_job_id ? `${operation.runtime_url} · ${operation.remote_job_id}` : 'No runtime job submitted yet.'}</CardDescription></CardHeader><CardContent className="space-y-4"><JsonView value={operation.payload} />{operation.runtime && <JsonView value={operation.runtime} />}{operation.runtime_error && <p className="text-sm text-destructive">{operation.runtime_error}</p>}</CardContent></Card>
    <Card><CardHeader><CardTitle>Operation log</CardTitle><CardDescription>Persistent platform progress and failure details.</CardDescription></CardHeader><CardContent><Log text={operation.log || 'Waiting for log entries…'} /></CardContent></Card>
    {Object.entries(operation.runtime_logs).map(([name, contents]) => <Card key={name}><CardHeader><CardTitle className="font-mono text-base">{name}</CardTitle><CardDescription>Runtime output, including Python tool stdout and exceptions. Showing the latest 32 KiB.</CardDescription></CardHeader><CardContent><Log text={contents || 'No output yet.'} /></CardContent></Card>)}
  </div>;
}

function Log({ text }: { text: string }) {
  return <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-4 font-mono text-xs leading-5">{text}</pre>;
}
