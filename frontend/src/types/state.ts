// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
// Shape of GET /api/state (backend: app/schemas/state.py HevSystemState).
import type { FitnessState } from "./fitness";
export type SeverityName = "NOMINAL" | "ADVISORY" | "CAUTION" | "WARNING";
export type ZoneId = "head" | "eyes" | "cardiovascular" | "respiratory" | "musculoskeletal" | "radiation";
export type ParamStatus = "OK" | "STALE" | "SENSOR_FAULT" | "NO_DATA" | "NOT_INSTRUMENTED";

export interface ParameterState {
  id: string;
  label: string;
  short: string;
  unit: string;
  category: "physiological" | "environmental" | "radiation" | "psychological";
  zone: ZoneId;
  valid_range: [number, number];
  thresholds: Record<string, number>;
  hysteresis: number;
  stale_after_s: number;
  recovery_hold_s: number;
  protocol: string | null;
  sensor: string;
  available: boolean;
  provenance: string;
  status: ParamStatus;
  value: number | null;
  timestamp: string | null;
  age_s: number | null;
  source: string | null;
  latest_quality: string | null;
  fault_reason: string | null;
  band: SeverityName | null;
  effective_thresholds?: Record<string, number>;
  limits_context?: string | null;
  trend: [string, number][];
}

export interface Alert {
  id: string;
  rule_id: string;
  kind: "THRESHOLD" | "SENSOR_FAULT" | "DATA_STALE" | "CORRELATION";
  parameter: string | null;
  zone: ZoneId;
  title: string;
  message: string;
  data_source: string;
  simulated: boolean;
  protocol_id: string | null;
  severity: Exclude<SeverityName, "NOMINAL">;
  peak_severity: SeverityName;
  lifecycle: "ACTIVE" | "RECOVERY" | "CLEARED";
  acknowledged: boolean;
  silenced: boolean;
  cm_status: "NONE" | "AVAILABLE" | "IN_PROGRESS" | "COMPLETED";
  cm_steps_done: number[];
  unit: string | null;
  trigger_value: number | null;
  last_value: number | null;
  occurrence_count: number;
  recovery_since: string | null;
  resolution_verified: boolean;
  recovery_hold_s: number;
  factors: { factor: string; value?: number; severity?: string; timestamp: string; detail?: string }[] | null;
  created_at: string;
  updated_at: string;
  cleared_at: string | null;
  cleared_by: string | null;
  states: string[];
  audio_required: boolean;
  can_clear: boolean;
}

export interface AlertEventCue {
  seq: number;
  event_type: string;
  alert_id: string;
  title: string;
  kind: Alert["kind"];
  severity: SeverityName;
  protocol_id: string | null;
  silenced: boolean;
  parameter: string | null;
  timestamp: string;
}

export interface TimelineEntry {
  id: string;
  timestamp: string;
  category: string;
  event_type: string;
  severity: SeverityName | null;
  message: string;
  source: string;
  alert_id: string | null;
  zone: ZoneId | null;
  actor: string | null;
}

export interface FeedStatus {
  last_attempt: string | null;
  last_success: string | null;
  last_status: string | null;
  http_status: number | null;
  error: string | null;
  endpoint: string | null;
}

export interface NasaDonkiContext {
  status: "LIVE" | "CACHED_OFFLINE" | "OFFLINE_BASELINE";
  latest_event: string;
  event_id: string | null;
  event_type: string | null;
  class_type: string | null;
  peak_time: string | null;
  event_age_h: number | null;
  link: string | null;
  space_weather_risk: "NOMINAL" | "CAUTION" | "WARNING";
  eva_advisory: string;
  radiation_context: string;
  updated_at: string;
  last_successful_fetch: string | null;
  is_placeholder: boolean;
  refresh_in_progress: boolean;
  feeds: Record<string, FeedStatus>;
  recent_events: { event_id: string; event_type: string; class_type: string; peak_time: string | null; description: string; link: string | null }[];
  source: string;
  provenance: string;
}

export interface SimulatedSpaceWeather {
  status: "SIMULATED";
  latest_event: string;
  space_weather_risk: "WARNING";
  eva_advisory: string;
  radiation_context: string;
  started_at: string;
  source: string;
}

export type GateStatus = "CLEAR" | "REVIEW" | "UNKNOWN" | "HOLD";
export interface Readiness {
  eva: {
    status: "NO_BLOCKERS" | "REVIEW" | "DATA_INCOMPLETE" | "HOLD_RECOMMENDED";
    gates: { id: string; label: string; status: GateStatus; reasons: string[] }[];
    gates_clear: number;
    gates_total: number;
    disclaimer: string;
  };
  triage: {
    focus: string; title: string; severity: SeverityName; alert_id: string | null; protocol_id: string | null;
    kit: string | null; rationale: string; context: string[]; disclaimer: string;
  };
}

export interface Scenario { id: string; label: string; description: string; active: boolean }

export interface HevSystemState {
  server_time: string;
  version: string;
  mission: {
    id: string; name: string; environment: string; vehicle: string; met_start_utc: string; met_seconds: number;
    crew: { id: string; name: string; role: string; monitored: boolean }[]; monitored_crew_id: string | null;
  };
  mode: { demo_mode: boolean; simulator_enabled: boolean; scenario: string; scenarios: Scenario[] };
  medical_status: SeverityName;
  system_health: { status: "NOMINAL" | "DEGRADED"; detail: string; database: string; rules_engine: string };
  master: { warning: boolean; warning_unacked: boolean; caution: boolean; caution_unacked: boolean; audio_required: boolean };
  zones: Record<ZoneId, { label: string; reference: string }>;
  parameters: ParameterState[];
  alerts: Alert[];
  recent_cleared: Alert[];
  events: AlertEventCue[];
  latest_event_seq: number;
  radiation: {
    dose_rate: number | null; dose_rate_source: string | null; accumulated_mGy: number | null; budget_mGy: number;
    budget_fraction: number | null; budget_provenance: string;
    events: { id: string; event_type: string; source: string; start_time: string; peak_time: string | null; class_type: string | null; description: string; link: string | null }[];
    note: string;
  };
  sync: { link_up: boolean; target: string; pending: number; sent: number; oldest_pending_at: string | null; last_success_at: string | null; last_error: string | null; duplicates_ignored: number };
  timeline: TimelineEntry[];
  nasa_donki: NasaDonkiContext;
  space_weather_simulation: SimulatedSpaceWeather | null;
  readiness?: Readiness;
  fitness?: FitnessState;
}

export interface Protocol {
  id: string; title: string; description: string; subsystem: string; kit: string; kit_contents: string[];
  duration_min: number | null; steps: string[]; resolution: string; provenance: string;
}

export interface PvtResult {
  id: string; timestamp: string; duration_s: number; stimuli: number; responses: number; mean_rt_ms: number | null;
  median_rt_ms: number | null; lapses: number; misses: number; false_starts: number; reaction_times_ms: number[]; source: string;
}
