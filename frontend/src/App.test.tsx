// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { useHevStore } from "./store/useHevStore";
import { co2Alert, makeState, protocols } from "./test/fixtures";
import type { HevSystemState } from "./types/state";

let current: HevSystemState;
let online = true;
const calls: { url: string; method: string; body?: string }[] = [];

function mockFetch() {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    if (!online) throw new TypeError("Failed to fetch");
    const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/state")) return json(current);
    if (url === "/api/v1/protocols") return json(protocols);
    if (url === "/api/v1/pvt/history") return json({ results: [], baseline_mean_rt_ms: null, latest_delta_ms: null });
    return json({ ok: true });
  }) as typeof fetch;
}

beforeEach(() => {
  current = makeState();
  online = true;
  calls.length = 0;
  mockFetch();
  useHevStore.setState({ state: null, connection: "CONNECTING", lastSeq: null, selectedAlertId: null, selectedZone: null, protocols: {}, notice: null, modal: null, outboxPending: 0, screen: "engineering" });
});
afterEach(() => vi.useRealTimers());

describe("HEV-1 crew interface", () => {
  it("renders mission telemetry and labels simulated data", async () => {
    render(<App />);
    expect(await screen.findByText(/HEV-DEMO-01/)).toBeInTheDocument();
    const hr = within(screen.getByTestId("vitals-panel")).getByTestId("param-heart_rate");
    expect(hr).toHaveTextContent("72.0");
    expect(hr).toHaveTextContent("SIM");
    expect(screen.getByText("CREW CONDITION NOMINAL")).toBeInTheDocument();
  });

  it("never shows a missing sensor as a normal value", async () => {
    render(<App />);
    const hyd = await within(await screen.findByTestId("vitals-panel")).findByTestId("param-hydration");
    expect(hyd).toHaveTextContent("NO SENSOR");
    expect(hyd).toHaveTextContent("----");
  });

  it("selects a Digital Twin zone and shows its related measurements", async () => {
    render(<App />);
    await screen.findByText(/HEV-DEMO-01/);
    fireEvent.click(document.querySelector('[data-zone="respiratory"]')!);
    const detail = screen.getByTestId("zone-detail");
    expect(detail).toHaveTextContent("RESPIRATORY / ATMOSPHERE");
    expect(within(detail).getByTestId("param-cabin_co2")).toBeInTheDocument();
  });

  it("shows a master warning, highlights the zone and sends ACK / SILENCE", async () => {
    current = makeState({ alerts: [co2Alert], medical_status: "WARNING",
      master: { warning: true, warning_unacked: true, caution: false, caution_unacked: false, audio_required: true } });
    render(<App />);
    const card = await screen.findByTestId("alert-TH-cabin_co2");
    expect(card).toHaveTextContent("MASTER WARNING");
    expect(document.querySelector('[data-zone="respiratory"]')).toHaveAttribute("data-severity", "WARNING");
    expect(screen.getByTestId("master-warning")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(card).getByTestId("ack-btn"));
    fireEvent.click(within(card).getByTestId("silence-btn"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/alerts/a1/ack" && c.method === "POST")).toBe(true));
    expect(calls.some((c) => c.url === "/api/v1/alerts/a1/silence")).toBe(true);
    expect(calls.some((c) => c.url.includes("/resolve"))).toBe(false);
  });

  it("shows the countermeasure guide, kit and records step confirmation", async () => {
    current = makeState({ alerts: [{ ...co2Alert, cm_status: "IN_PROGRESS", cm_steps_done: [0] }] });
    render(<App />);
    expect(await screen.findByTestId("cm-kit")).toHaveTextContent("KIT ECLSS-03");
    expect(screen.getByTestId("step-0")).toBeDisabled();
    expect(screen.getByTestId("cm-progress")).toHaveStyle({ width: "33%" });
    fireEvent.click(screen.getByTestId("step-1"));
    await waitFor(() => expect(calls.find((c) => c.url === "/api/v1/alerts/a1/countermeasure")?.body).toBe('{"step_index":1}'));
    expect(screen.getByTestId("clear-btn")).toBeDisabled();
  });

  it("requires two presses to clear a verified alert", async () => {
    current = makeState({ alerts: [{ ...co2Alert, lifecycle: "RECOVERY", resolution_verified: true, can_clear: true, recovery_since: "2026-11-14T12:00:00Z" }] });
    render(<App />);
    const btn = await screen.findByTestId("clear-btn");
    expect(btn).toBeEnabled();
    fireEvent.click(btn);
    expect(calls.some((c) => c.url.includes("/resolve"))).toBe(false);
    fireEvent.click(btn);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/alerts/a1/resolve")).toBe(true));
  });

  it("indicates offline state and keeps cached telemetry", async () => {
    render(<App />);
    await screen.findByText(/HEV-DEMO-01/);
    online = false;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 1300));
    });
    expect(await screen.findByTestId("offline-banner")).toHaveTextContent("CORE LINK LOST");
    expect(screen.getByText(/HEV-DEMO-01/)).toBeInTheDocument();
  });

  it("triggers a simulator scenario through the API", async () => {
    render(<App />);
    fireEvent.click(await screen.findByTestId("scenario-high_co2"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/simulator/high_co2" && c.method === "POST")).toBe(true));
  });

  it("shows DONKI resilience tier and the simulated override separately", async () => {
    current = makeState({ space_weather_simulation: { status: "SIMULATED", latest_event: "Solar Flare X1.0 + SEP onset (SIMULATED demonstration scenario)",
      space_weather_risk: "WARNING", eva_advisory: "EVA HOLD RECOMMENDED", radiation_context: "Simulated.", started_at: "", source: "SIM" } });
    render(<App />);
    const ctx = await screen.findByTestId("donki-context");
    expect(ctx).toHaveTextContent("SIMULATED");
    expect(ctx).toHaveTextContent("EVA HOLD RECOMMENDED");
    expect(ctx).toHaveTextContent("Live DONKI: CACHED OFFLINE");
  });
});

describe("COMMAND screen (screen 1)", () => {
  beforeEach(() => useHevStore.setState({ screen: "command" }));

  it("is the default screen and switches with tabs and keys 1 / 2", async () => {
    useHevStore.setState({ screen: useHevStore.getInitialState().screen });
    render(<App />);
    expect(await screen.findByTestId("screen-command-view")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("screen-engineering"));
    expect(screen.getByTestId("screen-engineering-view")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByTestId("screen-command-view")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.queryByTestId("screen-command-view")).not.toBeInTheDocument();
  });

  it("shows backend values only and puts the twin on screen 1", async () => {
    current = makeState({ alerts: [co2Alert], medical_status: "WARNING",
      parameters: makeState().parameters.map((p) => (p.id === "cabin_co2" ? { ...p, value: 8.25, band: "WARNING" as const } : p)),
      readiness: { ...makeState().readiness!,
        eva: { ...makeState().readiness!.eva, status: "HOLD_RECOMMENDED", gates_clear: 3 },
        triage: { focus: "CABIN_CO2", title: "Cabin CO2 removal", severity: "WARNING", alert_id: "a1", protocol_id: "CM-ECLSS-01",
          kit: "KIT ECLSS-03", rationale: "CO2 high", context: ["Elevated cabin CO2 coincides with physiological change"], disclaimer: "not a diagnosis" } } });
    render(<App />);
    expect(await screen.findByTestId("metric-cabin_co2")).toHaveTextContent("8.25");
    expect(screen.getByTestId("hud-mission-status")).toHaveTextContent("ACTION REQUIRED");
    expect(screen.getByTestId("hud-triage")).toHaveTextContent("CABIN CO2 REMOVAL");
    expect(screen.getByTestId("hud-eva")).toHaveTextContent("HOLD RECOMMENDED");
    expect(screen.getByTestId("hud-eva")).not.toHaveTextContent(/CLEARANCE|GO\b/);
    // Emergency layout: high-contrast band with cause, kit and 30-s hold; nominal values dimmed; EVA never "GO".
    const band = screen.getByTestId("emergency-band");
    expect(band).toHaveTextContent("MASTER WARNING");
    expect(screen.getByTestId("emergency-kit")).toHaveTextContent("KIT ECLSS-03");
    expect(screen.getByTestId("emergency-hold")).toHaveTextContent("HOLD");
    expect(screen.getByTestId("banner-mission-status")).toHaveTextContent("ACTION REQUIRED");
    expect(screen.getByTestId("banner-eva")).toHaveTextContent("EVA: NO-GO (HOLD)");
    expect(screen.getByTestId("metric-heart_rate").className).toContain("hev-dimmed");
    expect(screen.getByTestId("metric-cabin_co2").className).not.toContain("hev-dimmed");
    fireEvent.click(within(band).getByText("SHOW TWIN"));
    expect(within(screen.getByTestId("hud-twin")).getByRole("group", { name: "Digital human twin" })).toBeInTheDocument();
    expect(document.querySelector('[data-zone="respiratory"]')).toHaveAttribute("data-severity", "WARNING");
    expect(screen.getByTestId("alert-TH-cabin_co2")).toBeInTheDocument();
    expect(screen.getByTestId("cm-kit")).toHaveTextContent("KIT ECLSS-03");
  });

  it("never shows a missing sensor as a value on the HUD", async () => {
    current = makeState({ parameters: makeState().parameters.map((p) => (p.id === "heart_rate" ? { ...p, status: "SENSOR_FAULT" as const } : p)) });
    render(<App />);
    const hr = await screen.findByTestId("metric-heart_rate");
    expect(hr).toHaveTextContent("SENSOR FAULT");
    expect(hr).toHaveTextContent("----");
  });

  it("drives scenarios through the backend simulator", async () => {
    render(<App />);
    fireEvent.click(await screen.findByTestId("scenario-high_co2"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/simulator/high_co2" && c.method === "POST")).toBe(true));
    expect(calls.some((c) => c.url.includes("reset"))).toBe(false);
  });
});

describe("SYS_DEBUG crew selector", () => {
  it("shows NO TELEMETRY LINK for a crew member without a biosensor instead of values", async () => {
    current = makeState({ mission: { ...makeState().mission, crew: [
      { id: "CM-1", name: "CM-1", role: "COMMANDER", monitored: true }, { id: "CM-2", name: "CM-2", role: "PILOT", monitored: false }] } });
    useHevStore.setState({ screen: "command", viewCrewId: null });
    render(<App />);
    fireEvent.change(await screen.findByTestId("crew-select"), { target: { value: "CM-2" } });
    expect(screen.getByTestId("crew-no-link")).toHaveTextContent("CM-2 · NO TELEMETRY LINK");
    expect(screen.queryByTestId("metric-heart_rate")).not.toBeInTheDocument();
    useHevStore.setState({ viewCrewId: null });
  });
});
