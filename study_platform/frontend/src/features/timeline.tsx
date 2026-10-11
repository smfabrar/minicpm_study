import { useMemo, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import type { Telemetry, Span } from '@/lib/types';
import { milliseconds } from '@/lib/utils';
import { Input } from '@/components/ui/input';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { JsonView } from '@/components/shared';
export function Timeline({ trace }: {
  trace: Telemetry;
}) {
  const [filter, setFilter] = useState('');
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<Span | null>(null);
  const last = Math.max(trace.origin_ns + 1, ...trace.spans.map(span => span.end_ns ?? span.start_ns), ...trace.events.map(event => event.at_ns));
  const duration = (last - trace.origin_ns) / 1e6;
  const spans = trace.spans.filter(span => span.name.toLowerCase().includes(filter.toLowerCase()));
  const parents = new Map(trace.spans.map(span => [span.id, span.parent_id]));
  function depth(span: Span) {
    let value = 0; let id = span.parent_id; const visited = new Set<string>(); while (id && !visited.has(id)) {
      visited.add(id);
      value++;
      id = parents.get(id) ?? null;
    } return Math.min(value, 7);
  }
  return <div className="space-y-5">
    <Card>
      <CardHeader>
        <CardTitle>Operation timeline</CardTitle>
        <CardDescription>Monotonic timestamps on {trace.clock_id}. Overlapping spans share elapsed time; their durations must not be summed.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <Input className="max-w-xs" placeholder="Filter operations…" aria-label="Filter timeline" value={filter} onChange={e => setFilter(e.target.value)} />
          <label className="flex items-center gap-3 text-sm">Zoom <input type="range" min="1" max="10" step="1" value={zoom} onChange={e => setZoom(Number(e.target.value))} /></label>
          <span className="ml-auto text-xs text-muted-foreground">{milliseconds(duration)} · {trace.spans.length} spans · {trace.dropped_records} dropped</span>
        </div>
        <div className="max-h-[560px] overflow-auto rounded-md border">
          <div style={{ minWidth: `${800 * zoom}px` }}>
            <div className="timeline-row sticky top-0 z-10 border-b bg-muted">
              <div className="px-3 py-2 text-xs">Operation</div>
              <div className="flex justify-between px-3 py-2 text-xs text-muted-foreground">
                {Array.from({ length: 6 }, (_, index) => <span key={index}>{(duration * index / 5 / 1000).toFixed(2)}s</span>)}
              </div>
            </div>
            {spans.map(span => <button type="button" key={span.id} className="timeline-row w-full border-b text-left hover:bg-accent/50" onClick={() => setSelected(span)}>
              <span className="truncate border-r py-2 pr-3 text-xs" style={{ paddingLeft: 12 + depth(span) * 10 }} title={span.name}>
                {span.name}
              </span>
              <span className="relative m-1 h-6">
                <span className={`timeline-bar ${span.status === 'error' ? 'bg-destructive' : span.name.startsWith('tool') || span.name.startsWith('oracle') ? 'bg-chart-2' : span.name.startsWith('granite') ? 'bg-chart-3' : 'bg-primary'}`} style={{ left: `${(span.start_ns - trace.origin_ns) / 1e6 / duration * 100}%`, width: `${Math.max(.15, ((span.end_ns ?? last) - span.start_ns) / 1e6 / duration * 100)}%` }} />
                <span className="absolute right-2 top-1 text-[10px] tabular-nums">
                  {milliseconds(span.duration_ns === null ? null : span.duration_ns / 1e6)}
                </span>
              </span>
            </button>)}
          </div>
        </div>
      </CardContent>
    </Card>
    {selected && <Card>
      <CardHeader>
        <CardTitle>
          {selected.name}
        </CardTitle>
        <CardDescription>{selected.status} · {milliseconds(selected.duration_ns === null ? null : selected.duration_ns / 1e6)}</CardDescription>
      </CardHeader>
      <CardContent>
        <JsonView value={selected} />
      </CardContent>
    </Card>}
    <MemoryPlot trace={trace} />
  </div>;
}
function MemoryPlot({ trace }: {
  trace: Telemetry;
}) {
  const data = useMemo(() => trace.memory.map(sample => ({ seconds: (sample.at_ns - trace.origin_ns) / 1e9, rss: sample.rss_bytes === null ? null : sample.rss_bytes / 1048576, gpu: sample.gpus.some(gpu => gpu.process_used_bytes !== null) ? sample.gpus.reduce((sum, gpu) => sum + (gpu.process_used_bytes ?? 0), 0) / 1048576 : null })), [trace]);
  return <Card>
    <CardHeader>
      <CardTitle>Memory over time</CardTitle>
      <CardDescription>Sampled process RSS and runtime-process GPU allocation. Missing observations remain empty; native-server memory is a separate process.</CardDescription>
    </CardHeader>
    <CardContent>
      {data.length ? <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="seconds" tickFormatter={value => `${Number(value).toFixed(1)}s`} />
            <YAxis unit=" MiB" width={80} />
            <Tooltip formatter={value => `${Number(value).toFixed(1)} MiB`} labelFormatter={value => `${Number(value).toFixed(3)}s`} contentStyle={{ background: 'var(--popover)', borderColor: 'var(--border)', borderRadius: 8 }} />
            <Legend />
            <Line type="linear" dataKey="rss" name="Process RSS" stroke="var(--primary)" dot={false} isAnimationActive={false} />
            <Line type="linear" dataKey="gpu" name="Process GPU (sum)" stroke="var(--chart-2)" dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div> : <p className="text-sm text-muted-foreground">Memory samples are not available yet.</p>}
    </CardContent>
  </Card>;
}
