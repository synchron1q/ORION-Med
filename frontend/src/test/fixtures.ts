// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import type { Alert, HevSystemState, ParameterState, Protocol } from "../types/state";

export function param(over: Partial<ParameterState> & { id: string }): ParameterState {
  return {
    label: over.id, short: over.id.toUpperCase(), unit: "bpm", category: "physiological", zone: "cardiovascular",
    valid_range: [0, 300], thresholds: { caution_high: 110, warning_high: 130 }, hysteresis: 5, stale_after_s: 8,
    recovery_hold_s: 5, protocol: null, sensor: "TEST", available: true, provenance: "DEMONSTRATION",
    status: "OK", value: 72, timestamp: "2026-11-14T12:00:00Z", age_s: 0.5, source: "SIMULATED", latest_quality: "GOOD",
    fault_reason: null, band: "NOMINAL", trend: [["2026-11-14T11:59:59Z", 71], ["2026-11-14T12:00:00Z", 72]],
    ...over,
  };
}

export const co2Alert: Alert = {
  id: "a1", rule_id: "TH-cabin_co2", kind: "THRESHOLD", parameter: "cabin_co2", zone: "respiratory",
  title: "CABIN CO2 PARTIAL PRESSURE HIGH", message: "Cabin CO2 is 7.0 mmHg, above the configured warning limit.",
  data_source: "SIMULATED", simulated: true, protocol_id: "CM-ECLSS-01", severity: "WARNING", peak_severity: "WARNING",
  lifecycle: "ACTIVE", acknowledged: false, silenced: false, cm_status: "AVAILABLE", cm_steps_done: [], unit: "mmHg",
  trigger_value: 7, last_value: 7, occurrence_count: 1, recovery_since: null, resolution_verified: false, recovery_hold_s: 5,
  factors: null, created_at: "2026-11-14T12:00:00Z", updated_at: "2026-11-14T12:00:00Z", cleared_at: null, cleared_by: null,
  states: ["WARNING"], audio_required: true, can_clear: false,
};

export const protocols: Protocol[] = [{
  id: "CM-ECLSS-01", title: "Elevated Cabin CO2", description: "CO2 above limit.", subsystem: "ECLSS / ATMOSPHERE",
  kit: "KIT ECLSS-03", kit_contents: ["Portable CO2 monitor"], duration_min: 10,
  steps: ["Announce the condition.", "Check the CO2 removal system.", "Reduce exertion."],
  resolution: "CO2 below limit for the hold time.", provenance: "DEMONSTRATION PROCEDURE - NOT A NASA-APPROVED PROTOCOL",
}];

export function makeState(over: Partial<HevSystemState> = {}): HevSystemState {
  return {
    server_time: "2026-11-14T12:00:01Z", version: "1.0.1",
    mission: { id: "HEV-DEMO-01", name: "Demo", environment: "CISLUNAR TRANSIT", vehicle: "SIM", met_start_utc: "2026-11-11T00:00:00Z",
      met_seconds: 275_430, crew: [{ id: "CM-1", name: "CM-1", role: "COMMANDER", monitored: true }], monitored_crew_id: "CM-1" },
    mode: { demo_mode: true, simulator_enabled: true, scenario: "nominal", scenarios: [
      { id: "nominal", label: "NOMINAL", description: "", active: true },
      { id: "high_co2", label: "HIGH CO2", description: "", active: false }] },
    medical_status: "NOMINAL",
    system_health: { status: "NOMINAL", detail: "", database: "OK", rules_engine: "OK" },
    master: { warning: false, warning_unacked: false, caution: false, caution_unacked: false, audio_required: false },
    zones: {
      head: { label: "HEAD / NEURO", reference: "" }, eyes: { label: "EYES / VISION", reference: "" },
      cardiovascular: { label: "CARDIOVASCULAR", reference: "Heart rate." }, respiratory: { label: "RESPIRATORY / ATMOSPHERE", reference: "" },
      musculoskeletal: { label: "MUSCULOSKELETAL", reference: "" }, radiation: { label: "WHOLE-BODY RADIATION", reference: "" },
    },
    parameters: [
      param({ id: "heart_rate", short: "HR", label: "Heart Rate" }),
      param({ id: "cabin_co2", short: "CO2", unit: "mmHg", category: "environmental", zone: "respiratory", value: 2.0, thresholds: { caution_high: 4, warning_high: 6 } }),
      param({ id: "dose_rate", short: "DOSE RATE", unit: "uGy/h", category: "radiation", zone: "radiation", value: 18, thresholds: { caution_high: 100, warning_high: 500 } }),
      param({ id: "hydration", short: "HYD", unit: "%", zone: "musculoskeletal", available: false, status: "NOT_INSTRUMENTED", value: null, thresholds: {} }),
    ],
    alerts: [], recent_cleared: [], events: [], latest_event_seq: 0,
    radiation: { dose_rate: 18, dose_rate_source: "SIMULATED", accumulated_mGy: 1.6, budget_mGy: 50, budget_fraction: 0.032,
      budget_provenance: "DEMONSTRATION", events: [], note: "" },
    sync: { link_up: true, target: "SIMULATED_GROUND_STATION", pending: 0, sent: 3, oldest_pending_at: null, last_success_at: null, last_error: null, duplicates_ignored: 0 },
    timeline: [{ id: "L1", timestamp: "2026-11-14T12:00:00Z", category: "SYSTEM", event_type: "SYSTEM", severity: null, message: "HEV-1 core started", source: "SYSTEM", alert_id: null, zone: null, actor: null }],
    nasa_donki: {
      status: "CACHED_OFFLINE", latest_event: "Solar Flare M4.2 (Region AR3889)", event_id: "F1", event_type: "FLR", class_type: "M4.2",
      peak_time: "2026-11-12T08:31:00Z", event_age_h: 51.5, link: null, space_weather_risk: "CAUTION", eva_advisory: "MONITOR RADIATION",
      radiation_context: "External context only.", updated_at: "2026-11-14T12:00:01Z", last_successful_fetch: "2026-11-14T11:00:00Z",
      is_placeholder: false, refresh_in_progress: false,
      feeds: { FLR: { last_attempt: null, last_success: null, last_status: "ERROR", http_status: 429, error: "429", endpoint: "FLR" } },
      recent_events: [], source: "NASA DONKI via api.nasa.gov", provenance: "",
    },
    space_weather_simulation: null,
    readiness: {
      eva: { status: "NO_BLOCKERS", gates_clear: 4, gates_total: 4, disclaimer: "Decision support only.",
        gates: [{ id: "radiation", label: "Radiation exposure", status: "CLEAR", reasons: [] },
          { id: "atmosphere", label: "Cabin atmosphere", status: "CLEAR", reasons: [] },
          { id: "cardiorespiratory", label: "Cardiorespiratory", status: "CLEAR", reasons: [] },
          { id: "alertness", label: "Alertness and sleep", status: "CLEAR", reasons: [] }] },
      triage: { focus: "NOMINAL", title: "No active findings", severity: "NOMINAL", alert_id: null, protocol_id: null, kit: null,
        rationale: "All nominal.", context: [], disclaimer: "Suggested focus for the crew - not a diagnosis." },
    },
    ...over,
  };
}
