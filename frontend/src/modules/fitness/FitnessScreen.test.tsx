// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../App";
import { useHevStore } from "../../store/useHevStore";
import { makeState, protocols } from "../../test/fixtures";
import type { ExerciseSession, FitnessState, Gate, PlanView } from "../../types/fitness";

const gate = (status: Gate["status"], reasons: Gate["reasons"] = []): Gate => ({
  status, reasons, clearance: null, evaluated_window: null, disclaimer: "Decision support only. Not a medical authorization.",
});
const session = (over: Partial<ExerciseSession>): ExerciseSession => ({
  id: "EX-D003-CM-1-AEROBIC-1", crew_id: "CM-1", exercise_type: "AEROBIC", exercise_label: "Aerobic session", day_index: 3, ordinal: 1,
  status: "NOTIFIED", device_id: "ERG-01", device_label: "Cycle ergometer (SIMULATED)", duration_min: 30,
  planned_start: "2026-11-14T12:15:00Z", planned_end: "2026-11-14T12:45:00Z", planned_start_met: "MET 076:45", planned_end_met: "MET 077:15",
  attempt: 0, conflict: null, notified_at: null, actual_start: null, actual_end: null, clearance_id: null, profile_id: null,
  pre_hr: null, peak_hr: null, end_hr: null, end_reason: null, monitored: true, gate: gate("READY_PER_PLAN"), provenance: "SIMULATED", ...over,
});
const cm1 = session({});
const cm2 = session({
  id: "EX-D003-CM-2-AEROBIC-1", crew_id: "CM-2", device_id: "TRD-01", device_label: "Treadmill with harness (SIMULATED)", monitored: false,
  gate: gate("CLEARANCE_REQUIRED", [{ level: "CLEARANCE", code: "NO_BIOSENSOR", text: "No biosensor data stream for CM-2", ref: null }]),
});
const fitness: FitnessState = {
  enabled: true, provenance: "DEMONSTRATION TRAINING PROGRAM - SIMULATED",
  plan: { plan_id: "HEV-DEMO-01-PLAN", revision: "A", content_hash: "abc", provenance: "SIMULATED", now_met: "MET 076:30", horizon_h: 48,
    phase_now: { id: "PH-TLC", type: "CRUISE", title: "Translunar cruise", exercise_allowed: true } },
  next_by_crew: [{ crew_id: "CM-1", monitored: true, session: cm1 }, { crew_id: "CM-2", monitored: false, session: cm2 }],
  in_progress: [], unscheduled: [], counts: { PLANNED: 2 }, active_clearances: [], notifications: [], alert_context: {}, last_decision_id: 1,
  equipment: [{ id: "ERG-01", label: "Cycle ergometer (SIMULATED)", class: "CYCLE", status: "OPERATIONAL", note: "", updated_at: null, provenance: "SIMULATED" }],
};
const plan: PlanView = {
  plan_id: "HEV-DEMO-01-PLAN", revision: "A", content_hash: "abc", provenance: "SIMULATED", source_of_truth: "yaml", horizon_h: 48, now_met: "MET 076:30",
  phase_now: fitness.plan!.phase_now, phases: [],
  activities: [{ id: "TCM-3", type: "MANEUVER", title: "Trajectory correction burn TCM-3", crew: ["ALL"], start: "2026-11-14T15:30:00Z", end: "2026-11-14T16:15:00Z",
    start_met: "MET 080:00", end_met: "MET 080:45", device_id: null, origin: "BASELINE", source: "BASELINE", scope: "vehicle", buffer_before_min: 30, buffer_after_min: 30, editable: false }],
};
const rec = {
  status: "RECOVERED", final: true, summary: "Back within baseline + 10 bpm after 8 s; 60-s drop 53 bpm", baseline_hr: 72, end_hr: 125, peak_hr: 126,
  hrr60: 53, hrr120: 53, time_to_baseline_s: 8, elapsed_s: 600, window_s: 600, threshold_hr: 82, provenance: "DEMONSTRATION", note: "DEMONSTRATION criteria",
  criteria: { window_min: 10, hrr60_min_bpm: 12, baseline_tolerance_bpm: 10, elevated_response_bpm: 20 },
} as const;
const recoveryView = {
  criteria: { window_min: 10, hrr60_min_bpm: 12, baseline_tolerance_bpm: 10, elevated_response_bpm: 20, validity_h: 24, provenance: "DEMONSTRATION" },
  monitored_crew_id: "CM-1",
  latest_by_crew: [{ crew_id: "CM-1", session_id: cm1.id, recovery: rec }, { crew_id: "CM-2", session_id: null, recovery: null }],
  items: [{ session: { ...cm1, status: "COMPLETED", actual_end: "2026-11-14T12:30:00Z" }, recovery: rec, curve: [[0, 125], [5, 90], [10, 75], [60, 72]] }],
};
const calls: { url: string; method: string; body?: string }[] = [];

function mock(enabled = true) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/state")) return json(makeState({ server_time: "2026-11-14T12:00:00Z", mission: { ...makeState().mission, met_start_utc: "2026-11-11T07:30:00Z" }, fitness: enabled ? fitness : { enabled: false } }));
    if (url === "/api/v1/protocols") return json(protocols);
    if (url.endsWith("/fitness/schedule")) return json([cm1, cm2]);
    if (url.endsWith("/fitness/plan")) return json(plan);
    if (url.includes("/fitness/decisions")) return json([]);
    if (url.endsWith("/fitness/recovery")) return json(recoveryView);
    if (url.includes("/fitness/sessions/EX-D003-CM-2")) return json({ ...cm2, gate_at_start: null, context: null, decisions: [] });
    if (url.includes("/fitness/sessions/EX-D003-CM-1")) return json({ ...cm1, gate_at_start: null, context: null, decisions: [] });
    return json({ ok: true });
  }) as typeof fetch;
}

beforeEach(() => {
  calls.length = 0;
  useHevStore.setState({ state: null, connection: "CONNECTING", lastSeq: null, screen: "command", fitnessTab: "schedule", selectedSessionId: null, notice: null, modal: null });
});

describe("FITNESS screen (screen 3, CFMS)", () => {
  it("is hidden while CFMS is disabled", async () => {
    mock(false);
    render(<App />);
    await screen.findByTestId("screen-command-view");
    await waitFor(() => expect(useHevStore.getState().state).not.toBeNull());
    expect(screen.queryByTestId("screen-fitness")).not.toBeInTheDocument();
    expect(screen.queryByTestId("hud-next-exercise")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "3" });
    expect(screen.queryByTestId("screen-fitness-view")).not.toBeInTheDocument();
  });

  it("shows the next exercise on COMMAND and opens screen 3 with key 3", async () => {
    mock();
    render(<App />);
    expect(await screen.findByTestId("hud-next-exercise")).toHaveTextContent("CM-1 AEROBIC");
    fireEvent.keyDown(window, { key: "3" });
    expect(await screen.findByTestId("screen-fitness-view")).toBeInTheDocument();
    expect(screen.getByTestId("fitness-next-CM-2")).toHaveTextContent("CLEARANCE REQUIRED");
    expect(screen.getByTestId("fitness-next-CM-2")).toHaveTextContent("NO BIOSENSOR");
    expect(await screen.findByTestId("tl-activity-TCM-3")).toBeInTheDocument();
  });

  it("keeps START disabled until the gate is READY and scopes a clearance to one crew member and type", async () => {
    mock();
    useHevStore.setState({ screen: "fitness" });
    render(<App />);
    fireEvent.click(await screen.findByTestId("fitness-next-CM-2"));
    const panel = await screen.findByTestId("fitness-session-detail");
    await within(panel).findByText(/CM-2 · AEROBIC SESSION/);
    expect(within(panel).getByTestId("fitness-gate-status")).toHaveTextContent("CLEARANCE REQUIRED");
    expect(within(panel).getByTestId("fitness-start")).toBeDisabled();
    fireEvent.click(within(panel).getByTestId("fitness-clearance-open"));
    expect(screen.getByTestId("fitness-clearance-form")).toHaveTextContent("CM-2 · AEROBIC only");
    fireEvent.click(screen.getByTestId("fitness-clearance-submit"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/fitness/clearances" && c.method === "POST")).toBe(true));
    const body = JSON.parse(calls.find((c) => c.url === "/api/v1/fitness/clearances")!.body!);
    expect(body).toMatchObject({ crew_id: "CM-2", exercise_type: "AEROBIC", valid_hours: 4 });
  });

  it("starts a READY session only on explicit crew confirmation", async () => {
    mock();
    useHevStore.setState({ screen: "fitness", selectedSessionId: cm1.id });
    render(<App />);
    const panel = await screen.findByTestId("fitness-session-detail");
    const start = await within(panel).findByTestId("fitness-start");
    await waitFor(() => expect(start).toBeEnabled());
    expect(calls.some((c) => c.url.endsWith("/start"))).toBe(false);
    fireEvent.click(start);
    await waitFor(() => expect(calls.some((c) => c.url === `/api/v1/fitness/sessions/${cm1.id}/start` && c.method === "POST")).toBe(true));
  });

  it("shows the recovery monitor with DEMONSTRATION criteria and never a missing result as normal", async () => {
    mock();
    useHevStore.setState({ screen: "fitness", fitnessTab: "recovery" });
    render(<App />);
    expect(await screen.findByTestId("recovery-status-CM-1")).toHaveTextContent("RECOVERED");
    expect(screen.getByTestId("recovery-card-CM-2")).toHaveTextContent("No finished session");
    expect(screen.getByTestId("recovery-curve")).toHaveTextContent("53 bpm");
    expect(screen.getByTestId("recovery-criteria")).toHaveTextContent("DEMONSTRATION");
  });
});
