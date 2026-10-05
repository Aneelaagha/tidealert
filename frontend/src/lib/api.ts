// The only place the page talks to the backend. Every value the page shows comes back from one of these calls;
// the types mirror the FastAPI responses (backend/app/routes, docs/api/map.md) and add nothing of their own.

import { OfflineError, SLOW_TIMEOUT_MS, TIMEOUT_MS, cacheGet, cachePut, dispatch, fetchTimed, isNetworkError } from './connection';

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
  sources: { name: string; category: string; cadence_seconds: number; stale_after_seconds: number | null;
             stale_after_overridden: boolean }[];
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

export interface SupplyZone {
  zone_access: string;
  since: string | null;
  mechanism: string | null;
  reason_id: number;
}

/** /map/supply-access: every zone's access from the main road network as of `at`. Route feasibility only. */
export interface SupplyAccess {
  run_id: string;
  mode: Mode;
  at: string;
  states: string[]; // worst first
  labels: Record<string, string>;
  counts: Record<string, { zones: number; population: number }>;
  reasons: string[];
  zones: Record<string, SupplyZone>;
  does_not_show: string;
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

export interface SafetyWarning { code: string; severity: 'high' | 'medium' | string; since: string | null; text: string }

/** A task's zone access as of the slider time, from the isolation engine's stored state (app.services.safety). */
export interface Safety {
  zone_access: 'isolated' | 'reconnected' | 'possibly_isolated' | 'not_evaluated' | 'reachable' | string;
  since: string | null;
  mechanism: string | null;
  reason: string;
  warnings: SafetyWarning[];
  assignment_note: string | null;
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
  safety?: Safety; // present on /tasks, /tasks/{id} and /cases
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

export interface Counts { total: number; real: number; synthetic: number }

export interface DataPractices {
  households: Counts;
  responders: Counts;
  household_fields_stored: string[];
  personal_fields: string[];
  personal_fields_exposed: string[];
  write_routes: string[];
  consent_collected: boolean;
  authentication: boolean;
  response_scan: { method: string; limitation: string };
  copilot: { mode: string; reason: string; model: string; external_model_rule: string };
  known_gaps: { id: string; text: string; source: string }[];
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
  rewrites?: number; // model answers: times a draft was rejected by the check and rewritten before it passed
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

/** GET with a timeout. A network failure (never an HTTP error status) is reported to the connection store, and the
 *  same request's last response is served from the one-view cache if there is one; otherwise OfflineError. */
export async function get<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null) query.set(k, v);
  const qs = query.toString();
  const url = qs ? `${path}?${qs}` : path;
  let r: Response;
  try {
    r = await fetchTimed(url, {}, SLOW_TIMEOUT_MS[path] ?? TIMEOUT_MS, signal);
  } catch (e) {
    if (!isNetworkError(e)) throw e; // the page's own abort
    dispatch({ type: 'network_failure', at: Date.now() });
    const hit = cacheGet(url);
    if (hit) return hit.body as T;
    throw new OfflineError(path);
  }
  dispatch({ type: 'reachable', at: Date.now() });
  if (!r.ok) throw new ApiError(path, r.status, detailOf(await r.text()));
  const body = await r.json() as T;
  cachePut(url, body, Date.now());
  return body;
}

/** POST with a timeout. Never cached or queued: offline, writes and questions fail with OfflineError. */
export async function post<T>(path: string, body: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetchTimed(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
                         TIMEOUT_MS * 15); // a model answer can take most of the server's 60 s model timeout
  } catch (e) {
    if (!isNetworkError(e)) throw e;
    dispatch({ type: 'network_failure', at: Date.now() });
    throw new OfflineError(path, true);
  }
  dispatch({ type: 'reachable', at: Date.now() });
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
  supplyAccess: (runId: string, at: string | null, signal?: AbortSignal) =>
    get<SupplyAccess>('/map/supply-access', { run_id: runId, at }, signal),
  cases: (runId: string, zoneId: string | null, at: string | null, signal?: AbortSignal) =>
    get<{ at: string; cases: Case[] }>('/cases', { run_id: runId, zone_id: zoneId, at }, signal),
  tasks: (runId: string, at: string | null, signal?: AbortSignal) =>
    get<{ at: string; tasks: Task[] }>('/tasks', { run_id: runId, at }, signal),
  // A live run is served by real responders (run_id omitted); a replay or scenario by its own synthetic ones.
  responders: (run: Run, signal?: AbortSignal) =>
    get<{ responders: Responder[] }>('/responders', run.mode === 'live' ? {} : { run_id: run.id }, signal),
  assign: (taskId: string, responderId: string, a: Acting) =>
    post<Task>(`/tasks/${taskId}/assign`, { responder_id: responderId, actor: a.actor, note: a.note ?? '', ...(a.at ? { at: a.at } : {}) }),
  dataPractices: (signal?: AbortSignal) => get<DataPractices>('/data-practices', {}, signal),
  copilotStatus: (signal?: AbortSignal) => get<CopilotStatus>('/copilot/status', {}, signal),
  ask: (q: CopilotQuestion) => post<CopilotAnswer>('/copilot/ask', q),
  complete: (taskId: string, a: Acting) =>
    post<Task>(`/tasks/${taskId}/status`, { status: 'complete', actor: a.actor, note: a.note ?? '', ...(a.at ? { at: a.at } : {}) }),
};
