// The only place the page talks to the backend. Every value the page shows comes back from one of these calls;
// the types mirror the FastAPI responses (backend/app/routes, docs/api/map.md) and add nothing of their own.

export type Mode = 'replay' | 'scenario' | 'live' | string;

export interface Run {
  id: string;
  name: string;
  description: string | null;
  mode: Mode;
  window_start: string | null;
  window_end: string | null;
  case_count: number;
  regions: string[];
  extent: [number, number, number, number] | null;
  caveats: string[];
  task_actions_blocked: string | null; // the server's reason task actions refuse this run, or null
}

export interface Vocabulary {
  risk_level: string[];
  confidence_word: string[];
  engine: string[];
  direction: string[];
  mode: string[];
  coverage_gap: string[];
  task_status: string[];
  task_kind: string[];
  task_priority: string[];
}

export interface CoverageGap {
  kind: string;
  status: string | null;
  since: string | null;
  time_bound: boolean;
  active: boolean;
  reason_id: number;
}

export interface ZoneProps {
  zone_id: string;
  name: string;
  region: string;
  population: number | null;
  risk_level: string;
  risk_level_note: string | null;
  data_confidence: number | null;
  coverage_gaps: CoverageGap[];
  coverage_gap_active: boolean;
  case_count: number;
  confidence_word: string | null;
  engines: string[];
  task_count: number;
  task_awaiting: number;
  task_flagged: number;
  task_status: string | null;
  task_priority: string | null;
  task_verify: boolean;
  task_kinds: string[];
  task_anchor?: [number, number] | null;
}

export interface ZonesResponse {
  type: 'FeatureCollection';
  run_id: string;
  mode: Mode;
  at: string;
  gap_reasons: string[];
  features: { type: 'Feature'; geometry: GeoJSON.Geometry; properties: ZoneProps }[];
}

export interface Source {
  name: string;
  category: string;
  status: string;
  last_observed_at: string | null;
  age_seconds: number | null;
  stale_after_seconds: number | null;
  stale_after_overridden: boolean;
}

export interface Freshness {
  at: string;
  sources: Source[];
  note: string | null;
}

export interface TaskEvent {
  at: string;
  status: string;
  priority: string;
  verify_before_dispatch: boolean;
  actor: string;
  note: string;
  assigned_responder_id: string | null;
}

export interface Task {
  id: string;
  case_id: string;
  kind: string;
  created_at: string;
  created_by_rule: string;
  status: string;
  priority: string;
  verify_before_dispatch: boolean;
  assigned_responder_id: string | null;
  active: boolean;
  events: TaskEvent[];
}

export interface Contribution {
  engine: string;
  direction: string;
  engine_confidence: number;
  effective_confidence: number;
  independent_sources: number;
  first_observed_at: string;
  last_confirmed_at: string;
  rule_fragment: string;
}

export interface Case {
  id: string;
  zone_id: string;
  household_id: string | null;
  status: string;
  confidence_word: string;
  opened_at: string;
  inference_sentence: string;
  support: number;
  contradiction: number;
  fresh_sources: number;
  engines: string[];
  contributions: Contribution[];
  tasks: Task[];
}

export interface Responder {
  id: string;
  name: string;
  role: string;
  team_id: string | null;
  status: string;
  synthetic: boolean;
  run_id: string | null;
  last_ping_at: string | null;
  has_location: boolean;
}

export interface CopilotStatus {
  mode: 'model' | 'template' | string;
  reason: string;
  intents: Record<string, string>; // intent -> what it answers
  needs: Record<string, 'zone_id' | 'case_id' | string>; // intent -> what must be selected
}

export interface CopilotAnswer {
  mode: 'model' | 'template' | string;
  mode_reason: string;
  question: string;
  intent: string | null;
  in_scope: boolean;
  answer: string;
  unknowns: string[];
  as_of?: string;
  tools: string[];
  served_by?: string | null;
  placeholders?: number;
  retry_model_after_seconds?: number;
  household_data?: { households: number; real: number; may_send_to_external_model: boolean };
}

export interface CopilotQuestion {
  run_id: string;
  question: string;
  intent: string | null;
  at: string | null;
  zone_id: string | null;
  case_id: string | null;
}

type Params = Record<string, string | null | undefined>;

export class ApiError extends Error {
  constructor(public path: string, public status: number, public detail: string) {
    super(`${path}: ${status} ${detail}`);
  }
}

/** The `detail` FastAPI puts in an error body, as given; the raw body if there is none. */
function detailOf(body: string): string {
  try {
    const d = JSON.parse(body)?.detail;
    return typeof d === 'string' ? d : d != null ? JSON.stringify(d) : body;
  } catch {
    return body;
  }
}

export async function get<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null) query.set(k, v);
  const qs = query.toString();
  const r = await fetch(qs ? `${path}?${qs}` : path, { signal });
  if (!r.ok) throw new ApiError(path, r.status, detailOf(await r.text()));
  return r.json() as Promise<T>;
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new ApiError(path, r.status, detailOf(await r.text()));
  return r.json() as Promise<T>;
}

/** Who acts and when: `at` is the slider time on the run's clock (omitted for a live run: the server uses now). */
export interface Acting { actor: string; at: string | null; note?: string }

export const api = {
  runs: (signal?: AbortSignal) => get<{ runs: Run[]; vocabulary: Vocabulary }>('/runs', {}, signal),
  zones: (runId: string, at: string | null, signal?: AbortSignal) =>
    get<ZonesResponse>('/map/zones', { run_id: runId, at }, signal),
  freshness: (runId: string, at: string | null, signal?: AbortSignal) =>
    get<Freshness>('/map/freshness', { run_id: runId, at }, signal),
  cases: (runId: string, zoneId: string | null, at: string | null, signal?: AbortSignal) =>
    get<{ at: string; cases: Case[] }>('/cases', { run_id: runId, zone_id: zoneId, at }, signal),
  tasks: (runId: string, at: string | null, signal?: AbortSignal) =>
    get<{ at: string; tasks: Task[] }>('/tasks', { run_id: runId, at }, signal),
  // A live run is served by real responders (run_id omitted); a replay or scenario by its own synthetic ones.
  responders: (run: Run, signal?: AbortSignal) =>
    get<{ responders: Responder[] }>('/responders', run.mode === 'live' ? {} : { run_id: run.id }, signal),
  assign: (taskId: string, responderId: string, a: Acting) =>
    post<Task>(`/tasks/${taskId}/assign`, { responder_id: responderId, actor: a.actor, note: a.note ?? '', ...(a.at ? { at: a.at } : {}) }),
  copilotStatus: (signal?: AbortSignal) => get<CopilotStatus>('/copilot/status', {}, signal),
  ask: (q: CopilotQuestion) => post<CopilotAnswer>('/copilot/ask', q),
  complete: (taskId: string, a: Acting) =>
    post<Task>(`/tasks/${taskId}/status`, { status: 'complete', actor: a.actor, note: a.note ?? '', ...(a.at ? { at: a.at } : {}) }),
};
