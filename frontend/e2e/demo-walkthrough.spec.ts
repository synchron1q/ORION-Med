// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { expect, test, type Page } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOT_DIR ?? "../docs/screenshots";
const shot = (page: Page, name: string) => page.screenshot({ path: `${SHOTS}/${name}.png` });

test("30-second demonstration script on the real running application", async ({ page, request }) => {
  await request.post("/api/v1/simulator/nominal");
  await page.goto("/");
  await expect(page.getByTestId("screen-command-view")).toBeVisible();
  await expect(page.getByTestId("metric-heart_rate")).toContainText("bpm", { timeout: 10_000 });
  await expect(page.getByTestId("hud-eva")).toContainText("NO BLOCKERS FOUND", { timeout: 10_000 });
  await page.waitForTimeout(2_000);
  await shot(page, "01-command-nominal");

  // HIGH CO2 -> Master Warning, respiratory zone, R.I.D.G.E. focus, EVA hold
  await page.getByTestId("scenario-high_co2").click();
  const co2 = page.getByTestId("alert-TH-cabin_co2");
  await expect(co2).toContainText("MASTER WARNING", { timeout: 15_000 });
  await expect(page.locator('[data-zone="respiratory"]')).toHaveAttribute("data-severity", "WARNING");
  await expect(page.getByTestId("hud-triage")).toContainText("CABIN CO2 REMOVAL");
  await expect(page.getByTestId("hud-eva")).toContainText("HOLD RECOMMENDED");
  await page.waitForTimeout(1_500);
  await shot(page, "02-high-co2-master-warning");

  // ACK never clears; guide with KIT ECLSS-03
  await co2.getByTestId("ack-btn").click();
  await expect(co2).toContainText("ACK");
  await expect(co2).toContainText("MASTER WARNING");
  await co2.click();
  await expect(page.getByTestId("cm-kit")).toContainText("KIT ECLSS-03");
  for (const i of [0, 1, 2]) await page.getByTestId(`step-${i}`).click();
  await expect(page.getByTestId("cm-status")).toContainText("IN PROGRESS");
  await page.waitForTimeout(800);
  await shot(page, "03-ack-countermeasure-guide");

  // Return to nominal -> RECOVERY -> verified -> two-step CLEAR
  await page.getByTestId("scenario-nominal").click();
  await expect(page.getByTestId("resolution-status")).toContainText("RECOVERY", { timeout: 20_000 });
  await shot(page, "04-recovery");
  await expect(page.getByTestId("clear-btn")).toBeEnabled({ timeout: 20_000 });
  await page.getByTestId("clear-btn").click();
  await page.getByTestId("clear-btn").click();

  // Screen 2: engineering view keeps the persistent mission log
  await page.keyboard.press("2");
  await expect(page.getByTestId("screen-engineering-view")).toBeVisible();
  await expect(page.getByTestId("timeline")).toContainText("CLEARED", { timeout: 5_000 });
  await page.waitForTimeout(1_000);
  await shot(page, "05-engineering-mission-log");
  await page.getByTestId("screen-command").click();

  // HYPOXIA
  await page.getByTestId("scenario-hypoxia").click();
  await expect(page.getByTestId("alert-TH-spo2")).toContainText("MASTER WARNING", { timeout: 20_000 });
  await expect(page.getByTestId("hud-triage")).toContainText("OXYGENATION");
  await page.waitForTimeout(1_500);
  await shot(page, "06-hypoxia");

  // SOLAR FLARE (simulated event shown separately from live DONKI)
  await page.getByTestId("scenario-solar_flare").click();
  await expect(page.getByTestId("alert-TH-dose_rate")).toContainText("MASTER WARNING", { timeout: 15_000 });
  await expect(page.getByTestId("hud-space-weather")).toContainText("SIMULATED");
  await page.waitForTimeout(1_000);
  await shot(page, "07-solar-flare");

  // SENSOR FAILURE: missing data never normal, EVA readiness DATA INCOMPLETE
  await page.getByTestId("scenario-sensor_failure").click();
  await expect(page.getByTestId("metric-heart_rate")).toContainText("SENSOR FAULT", { timeout: 10_000 });
  await expect(page.getByTestId("hud-eva")).toContainText("DATA INCOMPLETE");
  await shot(page, "08-sensor-failure");

  // TACHYCARDIA
  await page.getByTestId("scenario-tachycardia").click();
  await expect(page.getByTestId("alert-TH-heart_rate")).toContainText("MASTER WARNING", { timeout: 20_000 });
  await page.waitForTimeout(1_000);
  await shot(page, "09-tachycardia");
  await page.getByTestId("scenario-nominal").click();
});
