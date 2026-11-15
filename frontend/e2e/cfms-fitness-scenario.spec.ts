// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// CFMS vertical scenario: Mission Plan -> Scheduler -> Safety Gate -> ExerciseSession, then replanning.
// Needs a FRESH instance started with ORION_CFMS_ENABLED=true (skipped otherwise). It runs before the
// 30-second walkthrough and leaves no active alert behind (the crew clears them after verified recovery).
const SHOTS = process.env.E2E_SCREENSHOT_DIR ?? "../docs/screenshots";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png` });

async function crewClearsAlerts(request: APIRequestContext) {
  await expect.poll(async () => {
    const alerts = (await (await request.get("/api/v1/alerts")).json()) as { id: string; acknowledged: boolean; can_clear: boolean }[];
    for (const a of alerts) {
      if (!a.acknowledged) await request.post(`/api/v1/alerts/${a.id}/ack`);
      if (a.can_clear) await request.post(`/api/v1/alerts/${a.id}/resolve`);
    }
    return ((await (await request.get("/api/v1/alerts")).json()) as unknown[]).length;
  }, { timeout: 60_000, intervals: [1_000] }).toBe(0);
}

test("CFMS: plan, safety gate, scoped clearance, monitored session, replanning", async ({ page, request }) => {
  const health = await (await request.get("/api/v1/health")).json();
  test.skip(!health.cfms_enabled, "CFMS is disabled (ORION_CFMS_ENABLED=false)");

  await request.post("/api/v1/simulator/nominal");
  await page.goto("/");
  const next = page.getByTestId("hud-next-exercise");
  await expect(next).toContainText("CM-1 AEROBIC", { timeout: 15_000 });
  await expect(next).toContainText("READY PER PLAN", { timeout: 15_000 });

  // Screen 3: crew schedule, timeline and the safety gate per crew member.
  await page.keyboard.press("3");
  await expect(page.getByTestId("screen-fitness-view")).toBeVisible();
  await expect(page.getByTestId("fitness-next-CM-2")).toContainText("CLEARANCE REQUIRED");
  await page.getByTestId("fitness-next-CM-1").click();
  const panel = page.getByTestId("fitness-session-detail");
  await expect(panel.getByTestId("fitness-gate-status")).toHaveText("READY PER PLAN");
  await expect(page.getByTestId("tl-activity-TCM-3")).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "10-fitness-crew-schedule");

  // CM-2 has no biosensor: a Medical Clearance scoped to CM-2 + AEROBIC.
  await page.getByTestId("fitness-next-CM-2").click();
  await expect(panel.getByTestId("fitness-gate-status")).toHaveText("CLEARANCE REQUIRED");
  await expect(panel.getByTestId("fitness-start")).toBeDisabled();
  await panel.getByTestId("fitness-clearance-open").click();
  await expect(page.getByTestId("fitness-clearance-form")).toContainText("CM-2 · AEROBIC only");
  await page.getByTestId("fitness-clearance-submit").click();
  await expect(panel.getByTestId("fitness-gate-status")).toHaveText("READY PER PLAN", { timeout: 10_000 });
  await expect(page.getByTestId("fitness-clearances")).toContainText("CM-2 · AEROBIC");

  // CM-1 starts on explicit crew confirmation; SIMULATED load raises heart rate.
  await page.getByTestId("fitness-next-CM-1").click();
  await expect(panel.getByTestId("fitness-gate-status")).toHaveText("READY PER PLAN");
  await panel.getByTestId("fitness-start").click();
  const live = page.getByTestId("fitness-in-session");
  await expect(live).toContainText("CM-1 · AEROBIC SESSION", { timeout: 10_000 });
  // Global HEV-1 limits unchanged: MASTER CAUTION fires and is NOT suppressed; the DEMO profile shows the context.
  await expect(page.getByTestId("master-caution")).toHaveAttribute("aria-pressed", "true", { timeout: 20_000 });
  await expect(live).toContainText("not suppressed", { timeout: 15_000 });
  await expect(page.getByTestId("fitness-profile-band")).toHaveText("IN TARGET");
  await page.waitForTimeout(1_000);
  await shot(page, "11-fitness-in-session");

  await page.keyboard.press("1");
  await expect(next).toContainText("In session");
  await expect(page.getByTestId("hud-triage")).not.toContainText("NO ACTIVE", { timeout: 5_000 });
  await page.waitForTimeout(800);
  await shot(page, "12-command-exercise-caution");

  await page.keyboard.press("3");
  await expect(panel).toContainText("CM-1 · AEROBIC SESSION");
  await panel.getByTestId("fitness-complete").click();
  await expect(panel).toContainText("COMPLETED", { timeout: 10_000 });

  // Recovery Monitor: observed for 60 s, then RECOVERED (DEMONSTRATION criteria).
  await page.getByTestId("fitness-tab-recovery").click();
  await expect(page.getByTestId("recovery-status-CM-1")).toHaveText("RECOVERING", { timeout: 10_000 });
  await expect(page.getByTestId("recovery-status-CM-2")).toHaveCount(0);
  await expect(page.getByTestId("recovery-status-CM-1")).toHaveText("RECOVERED", { timeout: 90_000 });
  await page.waitForTimeout(3_500);
  await shot(page, "15-fitness-recovery-monitor");
  await page.getByTestId("fitness-tab-schedule").click();
  await crewClearsAlerts(request);

  // Mission planner: an unplanned maneuver moves conflicting sessions; full decision history.
  await page.getByTestId("fitness-tab-planner").click();
  await page.getByTestId("fitness-add-submit").click();
  await expect(page.getByTestId("decision-MOVED").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("fitness-runtime-activities")).toContainText("RT-0001");
  await page.waitForTimeout(800);
  await shot(page, "13-fitness-planner-replan");

  // Equipment: the only resistive device fails -> resistive sessions lose their window; restore -> placed again.
  await page.getByTestId("fitness-tab-equipment").click();
  await page.getByTestId("fitness-device-RES-01-FAULT").click();
  await expect(page.getByTestId("fitness-device-RES-01-status")).toHaveText("FAULT", { timeout: 10_000 });
  await page.waitForTimeout(800);
  await shot(page, "14-fitness-equipment-fault");
  await page.getByTestId("fitness-tab-planner").click();
  await expect(page.getByTestId("fitness-unscheduled")).toContainText("RESISTIVE");
  await page.getByTestId("fitness-tab-equipment").click();
  await page.getByTestId("fitness-device-RES-01-OPERATIONAL").click();
  await expect(page.getByTestId("fitness-device-RES-01-status")).toHaveText("OPERATIONAL", { timeout: 10_000 });
  await page.getByTestId("fitness-tab-planner").click();
  await expect(page.getByTestId("decision-PLACED").first()).toBeVisible({ timeout: 10_000 });

  await page.keyboard.press("1");
  await crewClearsAlerts(request);
});
