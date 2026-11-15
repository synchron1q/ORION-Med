// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import type {
  Clearance, Equipment, ExerciseSession, FitnessConfig, PlannerDecision, PlanView, RecoveryView, ReferenceData, SessionDetail,
} from "../types/fitness";
import type { Alert, HevSystemState, Protocol, PvtResult } from "../types/state";

export class ApiError extends Error {
  constructor(public status: number, message: string, public data?: unknown) {
    super(message);
  }
}

const TIMEOUT_MS = 4000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(path, {
      ...init,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = res.statusText;
      let data: unknown;
      try {
        const body = await res.json();
        data = body.detail;
        detail = typeof body.detail === "string" ? body.detail
          : typeof body.detail?.message === "string" ? body.detail.message
          : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ")
          : JSON.stringify(body.detail ?? body);
      } catch {
        /* keep status text */
      }
      throw new ApiError(res.status, detail, data);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  state: (since: number | null) => request<HevSystemState>(`/api/state${since !== null ? `?since=${since}` : ""}`),
  protocols: () => request<Protocol[]>("/api/v1/protocols"),
  ack: (id: string) => post<Alert>(`/api/v1/alerts/${id}/ack`),
  silence: (id: string) => post<Alert>(`/api/v1/alerts/${id}/silence`),
  silenceAll: () => post<{ silenced: number }>("/api/v1/alerts/silence-all"),
  confirmStep: (id: string, stepIndex: number) => post<Alert>(`/api/v1/alerts/${id}/countermeasure`, { step_index: stepIndex }),
  resolve: (id: string) => post<Alert>(`/api/v1/alerts/${id}/resolve`),
  scenario: (scenario: string) => post<unknown>(`/api/v1/simulator/${scenario}`),
  link: (up: boolean) => post<unknown>("/api/v1/simulator/link", { up }),
  simulatorEnabled: (enabled: boolean) => post<unknown>("/api/v1/simulator/control", { enabled }),
  referenceData: () => request<ReferenceData>("/api/v1/reference-data"),
  refreshSpaceWeather: () => post<{ scheduled: boolean; message: string }>("/api/v1/space-weather/refresh"),
  submitPvt: (body: { reaction_times_ms: number[]; misses: number; false_starts: number; duration_s: number }) =>
    post<PvtResult>("/api/v1/pvt/results", body),
  pvtHistory: () => request<{ results: PvtResult[]; baseline_mean_rt_ms: number | null; latest_delta_ms: number | null }>("/api/v1/pvt/history"),
  submitPsych: (body: { mood: number; stress: number; fatigue: number; sleep_quality: number; notes: string; private: boolean }) =>
    post<unknown>("/api/v1/psych/assessments", body),
};

const F = "/api/v1/fitness";
export const fitnessApi = {
  config: () => request<FitnessConfig>(`${F}/config`),
  schedule: () => request<ExerciseSession[]>(`${F}/schedule`),
  plan: () => request<PlanView>(`${F}/plan`),
  recovery: () => request<RecoveryView>(`${F}/recovery`),
  decisions: (limit = 200) => request<PlannerDecision[]>(`${F}/decisions?limit=${limit}`),
  session: (id: string) => request<SessionDetail>(`${F}/sessions/${encodeURIComponent(id)}`),
  start: (id: string) => post<ExerciseSession>(`${F}/sessions/${encodeURIComponent(id)}/start`),
  complete: (id: string) => post<ExerciseSession>(`${F}/sessions/${encodeURIComponent(id)}/complete`),
  abort: (id: string, reason: string) => post<ExerciseSession>(`${F}/sessions/${encodeURIComponent(id)}/abort`, { reason }),
  earliest: (id: string) => post<{ session: ExerciseSession; decision: PlannerDecision }>(`${F}/sessions/${encodeURIComponent(id)}/request-earliest`),
  addActivity: (body: { activity_type: string; title: string; crew: string[]; start_in_min: number; duration_min: number; source: string }) =>
    post<{ activity: unknown; replan: { changes: number; decisions: PlannerDecision[] } }>(`${F}/plan/activities`, body),
  cancelActivity: (id: string) =>
    request<{ replan: { changes: number } }>(`${F}/plan/activities/${encodeURIComponent(id)}`, { method: "DELETE" }),
  equipment: (id: string, status: string, note: string) =>
    post<{ device: Equipment; replan: { changes: number; decisions: PlannerDecision[] } | null }>(`${F}/equipment/${encodeURIComponent(id)}`, { status, note }),
  grantClearance: (body: { crew_id: string; exercise_type: string; issued_by: string; valid_hours: number; note: string }) =>
    post<Clearance>(`${F}/clearances`, body),
  revokeClearance: (id: string, reason: string) => post<Clearance>(`${F}/clearances/${encodeURIComponent(id)}/revoke`, { reason }),
};
