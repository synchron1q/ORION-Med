// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
// CFMS (Crew Fitness Management System) shapes - backend app/cfms/service.py.
export type GateStatus = "BLOCKED" | "CLEARANCE_REQUIRED" | "READY_PER_PLAN";
export type SessionStatus = "PLANNED" | "NOTIFIED" | "IN_PROGRESS" | "COMPLETED" | "ABORTED" | "MISSED" | "UNSCHEDULED" | "CANCELLED";
export type DeviceStatus = "OPERATIONAL" | "DEGRADED" | "FAULT" | "MAINTENANCE";

export interface GateReason { level: "BLOCK" | "CLEARANCE" | "INFO"; code: string; text: string; ref: string | null }
export interface Gate {
  status: GateStatus;
  reasons: GateReason[];
  clearance: { id: string; issued_by: string; valid_until: string } | null;
  evaluated_window: [string, string] | null;
  disclaimer: string;
}

export interface ProfileEval {
  profile_id: string; label: string; provenance: string; note: string; overall: string; summary: string;
  limits: { heart_rate: Record<string, number>; heart_rate_pct_hrmax?: Record<string, number>; spo2: Record<string, number> };
  hrmax_bpm?: number | null; reference?: string | null;
  heart_rate: { value: number | null; band: string; pct_hrmax?: number | null } | null;
  spo2: { value: number | null; band: string } | null;
}

export interface ExerciseSession {
  id: string; crew_id: string; exercise_type: string; exercise_label: string; day_index: number; ordinal: number;
  status: SessionStatus; device_id: string | null; device_label: string | null; duration_min: number | null;
  planned_start: string | null; planned_end: string | null; planned_start_met: string | null; planned_end_met: string | null;
  attempt: number; conflict: string | null; notified_at: string | null; actual_start: string | null; actual_end: string | null;
  clearance_id: string | null; profile_id: string | null; pre_hr: number | null; peak_hr: number | null; end_hr: number | null;
  end_reason: string | null; monitored: boolean; gate: Gate | null; provenance: string;
  profile?: ProfileEval | null;
}

export interface SessionDetail extends ExerciseSession {
  gate_at_start: Gate | null;
  context: { alerts?: string[]; profile_id?: string; monitored?: boolean; recovery?: RecoveryResult } | null;
  decisions: PlannerDecision[];
}

export interface PlannerDecision {
  id: number | null; timestamp: string; session_id: string; crew_id: string; exercise_type: string; action: string;
  trigger: string; reason: string; conflict_code: string | null; conflict_ref: string | null;
  from_start: string | null; from_start_met: string | null; from_end: string | null; from_device: string | null;
  to_start: string | null; to_start_met: string | null; to_end: string | null; to_device: string | null; plan_hash: string;
}

export interface Equipment { id: string; label: string; class: string; status: DeviceStatus; note: string; updated_at: string | null; provenance: string }

export interface Clearance {
  id: string; crew_id: string; exercise_type: string; valid_from: string; valid_until: string; valid_from_met: string;
  valid_until_met: string; issued_by: string; note: string; created_at: string; revoked_at: string | null;
  revoked_reason: string | null; state: "ACTIVE" | "PENDING" | "EXPIRED" | "REVOKED"; active: boolean; provenance: string;
}

export interface PlanActivity {
  id: string; type: string; title: string; crew: string[]; start: string; end: string; start_met: string; end_met: string;
  device_id: string | null; origin: "BASELINE" | "RUNTIME"; source: string; scope: "crew" | "vehicle";
  buffer_before_min: number; buffer_after_min: number; editable: boolean;
}
export interface PlanPhase { id: string; type: string; title: string; start: string; end: string; start_met: string; end_met: string; exercise_allowed: boolean }
export interface PlanView {
  plan_id: string; revision: string; content_hash: string; provenance: string; source_of_truth: string; horizon_h: number;
  now_met: string; phase_now: { id: string; type: string; title: string; exercise_allowed: boolean } | null;
  phases: PlanPhase[]; activities: PlanActivity[];
}

export interface FitnessConfig {
  provenance: string;
  activity_rules: Record<string, { type: string; scope: string; before_min: number; after_min: number }>;
  exercise_types: Record<string, { label: string; duration_min: number; device_classes: string[]; profile_id: string }>;
  program: { crew_id: string; exercise_type: string; ordinal: number; preferred_start_h: number }[];
  profiles: Record<string, { label: string; heart_rate_pct_hrmax: Record<string, number>; spo2: Record<string, number>; reference: string | null; provenance: string }>;
  crew_profiles: Record<string, { hrmax_bpm: number; resting_hr_bpm?: number; provenance: string }>;
  exercise_alarm_policy: "global" | "context_hrmax";
  exercise_hr_alarm_pct_hrmax: Record<string, number>;
  clearance_max_validity_h: number;
  clearance_issuer_label: string;
}

export type RecoveryStatus = "RECOVERING" | "RECOVERED" | "REVIEW" | "DATA_INCOMPLETE";
export interface RecoveryResult {
  status: RecoveryStatus; final: boolean; summary: string; baseline_hr: number | null; end_hr: number | null; peak_hr: number | null;
  hrr60: number | null; hrr120: number | null; time_to_baseline_s: number | null; elapsed_s: number; window_s: number;
  threshold_hr: number | null; provenance: string; note: string; assessed_at?: string;
  criteria: { window_min: number; hrr60_min_bpm: number; baseline_tolerance_bpm: number; elevated_response_bpm: number };
}
export interface RecoveryView {
  criteria: { window_min: number; hrr60_min_bpm: number; baseline_tolerance_bpm: number; elevated_response_bpm: number; validity_h: number; provenance: string };
  monitored_crew_id: string | null;
  latest_by_crew: { crew_id: string; session_id: string | null; recovery: RecoveryResult | null }[];
  items: { session: ExerciseSession; recovery: RecoveryResult | null; curve: [number, number][] }[];
}

export interface ReferenceValue {
  id: string; group: string; label: string; value: number | number[]; unit: string; value_type: string;
  statistic?: string; population?: string; requirement?: string; source: string; source_title: string; source_url: string;
}
export interface ReferenceData { provenance: string; verified_on: string | null; values: ReferenceValue[] }

export interface FitnessState {
  enabled: boolean;
  provenance?: string;
  plan?: { plan_id: string; revision: string; content_hash: string; provenance: string; now_met: string; horizon_h: number;
    phase_now: { id: string; type: string; title: string; exercise_allowed: boolean } | null };
  next_by_crew?: { crew_id: string; monitored: boolean; session: ExerciseSession | null }[];
  in_progress?: ExerciseSession[];
  unscheduled?: ExerciseSession[];
  counts?: Partial<Record<SessionStatus, number>>;
  equipment?: Equipment[];
  active_clearances?: Clearance[];
  notifications?: { id: number; timestamp: string; message: string }[];
  alert_context?: Record<string, string>;
  alarm_policy?: "global" | "context_hrmax";
  alarm_context?: { session_id: string; crew_id: string; hrmax_bpm: number; caution_high: number; warning_high: number; until: string | null } | null;
  recovery?: { crew_id: string; session_id: string; exercise_type: string; status: RecoveryStatus; final: boolean; summary: string;
    hrr60: number | null; time_to_baseline_s: number | null; elapsed_s: number; window_s: number }[];
  last_decision_id?: number;
}
