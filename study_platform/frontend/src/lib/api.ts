import type { Study, StudySummary, Run, Telemetry, Analysis, RuntimeHealth, Operation } from './types';
class ApiClient {
  async request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    const response = await fetch(`/api${path}`, { method, headers: body instanceof FormData ? undefined : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body) });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>;
  }
  studies = () => this.request<StudySummary[]>('/studies');
  study = (id: string) => this.request<Study>(`/studies/${id}`);
  run = (id: string) => this.request<Run>(`/runs/${id}`);
  telemetry = (id: string) => this.request<Telemetry>(`/runs/${id}/telemetry`);
  analysis = (id: string) => this.request<Analysis>(`/studies/${id}/analysis`);
  runtime = () => this.request<RuntimeHealth>('/runtime');
  operations = () => this.request<Operation[]>('/operations');
}
export const api = new ApiClient();
