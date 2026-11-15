// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { defineConfig } from "@playwright/test";

// End-to-end walkthrough of the demonstration script against a RUNNING HEV-1
// instance (backend serving the built frontend). Start it first:
//   backend:  uvicorn app.main:app --port 8000
// then:      npm run e2e        (override with E2E_BASE_URL)
export default defineConfig({
  testDir: "./e2e",
  timeout: 150_000,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8000",
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
    actionTimeout: 15_000,
  },
});
