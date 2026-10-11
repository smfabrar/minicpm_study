export type Condition = 'B0' | 'B1' | 'B2';
export type Settings = Record<string, string | number | boolean>;
export interface StudySummary {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'frozen';
  case_count: number;
  run_count: number;
  updated_at: string;
}
export interface StudyCase {
  id: string;
  study_id: string;
  question: string;
  category: string;
  split: string;
  expected_answer: string;
  oracle_result: string;
  expected_tool: string;
  expected_arguments: Record<string, string>;
  notes: string;
  audio_path: string | null;
  audio_sha256: string | null;
  audio_origin: string | null;
}
export interface Tool {
  id: string;
  study_id: string;
  name: string;
  description: string;
  parameter: string;
  kind: string;
  records: Record<string, string>;
  aliases: Record<string, string>;
  delay_ms: number;
  failure: string;
}
export interface Review {
  verdict: string;
  heard_transcript: string;
  notes: string;
  relevant_fact_ms: number | null;
}
export interface Run {
  id: string;
  study_id: string;
  case_id: string;
  condition: Condition;
  status: string;
  created_at: string;
  error: string | null;
  result: {
    metrics?: {
      input_start_to_first_audio_ms?: number;
      pipeline_elapsed_ms?: number;
      memory?: {
        observed_peak_rss_bytes?: number;
        observed_peak_process_gpu_bytes?: number;
      };
    };
    audio_path?: string;
    [key: string]: unknown;
  } | null;
  artifact_directory: string | null;
  output_transcript: string;
  output_segments: unknown[];
  review: Review | null;
  snapshot: {
    cases: StudyCase[];
    settings: Settings;
  };
  request: unknown;
}
export interface Study extends Omit<StudySummary, 'case_count' | 'run_count'> {
  cases: StudyCase[];
  tools: Tool[];
  runs: Run[];
  settings: Settings;
}
export interface Span {
  id: string;
  parent_id: string | null;
  name: string;
  start_ns: number;
  end_ns: number | null;
  duration_ns: number | null;
  status: string;
  attributes: Record<string, unknown>;
}
export interface Telemetry {
  origin_ns: number;
  clock_id: string;
  clock_resolution_ns: number;
  spans: Span[];
  events: {
    name: string;
    at_ns: number;
    attributes: Record<string, unknown>;
  }[];
  memory: {
    at_ns: number;
    rss_bytes: number | null;
    gpus: {
      device: number;
      device_used_bytes: number;
      process_used_bytes: number | null;
    }[];
  }[];
  dropped_records: number;
}
export interface ConditionAnalysis {
  condition: Condition;
  attempted: number;
  primary_attempts: number;
  confirmed_correct: number;
  spoken_accuracy: number | null;
  unreviewed: number;
  failed: number;
  silent: number;
  median_first_audio_ms: number | null;
  peak_observed_rss_bytes: number | null;
  no_tool_attempts: number;
  unnecessary_calls: number;
}
export interface Analysis {
  conditions: ConditionAnalysis[];
  pending: number;
  notes: string[];
}
export interface RuntimeHealth {
  url: string;
  online: boolean;
  error?: string;
  [key: string]: unknown;
}
export interface Operation {
  id: string;
  kind: string;
  status: string;
  message: string;
  created_at: string;
}
