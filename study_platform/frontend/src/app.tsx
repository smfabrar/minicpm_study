import { Link, NavLink, Route, Routes } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { FlaskConical, LayoutDashboard, Server, Activity, Wrench } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Dashboard } from '@/features/dashboard';
import { StudyPage } from '@/features/study';
import { RunPage } from '@/features/run';
import { RuntimePage } from '@/features/runtime';
import { ToolLibraryPage } from '@/features/tool-library';
import { OperationsPage, OperationPage } from '@/features/operations';
import { Badge } from '@/components/ui/badge';
export function App() {
  const operations = useQuery({ queryKey: ['operations'], queryFn: api.operations, refetchInterval: 3000 });
  const active = operations.data?.filter(operation => ['queued', 'running'].includes(operation.status)) ?? [];
  const recent = operations.data?.slice(0, 4) ?? [];
  return <div className="min-h-screen bg-background">
    <aside className="workspace-sidebar">
      <NavLink to="/" className="mb-10 flex items-center gap-3 px-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <FlaskConical className="size-5" />
        </div>
        <div>
          <p className="font-semibold tracking-tight">Speech Study</p>
          <p className="text-xs text-sidebar-foreground/50">Experimental workspace</p>
        </div>
      </NavLink>
      <p className="mb-3 px-3 text-[10px] font-medium uppercase tracking-[.18em] text-sidebar-foreground/40">Workspace</p>
      <nav className="space-y-1">
        {[{ to: '/', label: 'Studies', icon: LayoutDashboard }, { to: '/tools', label: 'Tool library', icon: Wrench }, { to: '/operations', label: 'Operations', icon: Activity }, { to: '/runtime', label: 'Runtime', icon: Server }].map(item => <NavLink key={item.to} end to={item.to} className={({ isActive }) => cn('flex items-center gap-3 rounded-md px-3 py-2.5 text-sm text-sidebar-foreground/65 hover:bg-sidebar-accent', isActive && 'bg-sidebar-accent text-sidebar-foreground')}>
          <item.icon className="size-4" />
          {item.label}
        </NavLink>)}
      </nav>
      <div className="mt-auto border-t border-sidebar-border pt-5">
        <div className="mb-3 flex items-center gap-2 px-3 text-xs text-sidebar-foreground/60"><Activity className="size-3.5" /> Operations {active.length > 0 && <Badge variant="secondary">
          {active.length}
        </Badge>}</div>
        {recent.length ? recent.map(operation => <Link to={`/operations/${operation.id}`} key={operation.id} className="block rounded px-3 py-2 hover:bg-sidebar-accent">
          <p className="text-xs text-sidebar-foreground/80">
            {operation.kind}
            <span className={operation.status === 'failed' ? 'text-destructive' : 'text-sidebar-foreground/40'}>· {operation.status}</span>
          </p>
          {operation.message && <p className="mt-1 break-words text-[11px] text-sidebar-foreground/50">
            {operation.message}
          </p>}
        </Link>) : <p className="px-3 text-xs text-sidebar-foreground/40">No background work</p>}
        <p className="mt-5 px-3 text-[10px] text-sidebar-foreground/40">Offline protocol · v0.1</p>
      </div>
    </aside>
    <main className="workspace-main">
      <header className="mb-9 flex items-center justify-between border-b pb-5">
        <span className="text-xs font-medium uppercase tracking-[.18em] text-muted-foreground">Audio + tool use research</span>
        <Badge variant="outline">Non-live evaluation</Badge>
      </header>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/studies/:id" element={<StudyPage />} />
        <Route path="/runs/:id" element={<RunPage />} />
        <Route path="/runtime" element={<RuntimePage />} />
        <Route path="/tools" element={<ToolLibraryPage />} />
        <Route path="/operations" element={<OperationsPage />} />
        <Route path="/operations/:id" element={<OperationPage />} />
        <Route path="*" element={<p>Page not found.</p>} />
      </Routes>
    </main>
  </div>;
}
