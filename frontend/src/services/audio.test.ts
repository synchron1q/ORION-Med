// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { describe, expect, it } from "vitest";
import { protocols } from "../test/fixtures";
import { cueFor } from "./audio";

const P = Object.fromEntries(protocols.map((p) => [p.id, p]));
const base = { seq: 1, alert_id: "a", title: "CABIN CO2 HIGH", timestamp: "", silenced: false };

describe("HEV voice cues", () => {
  it("announces a master warning with the countermeasure kit", () => {
    const c = cueFor({ ...base, event_type: "RAISED", kind: "THRESHOLD", severity: "WARNING", protocol_id: "CM-ECLSS-01", parameter: "cabin_co2" }, P);
    expect(c.tone).toBe("warning");
    expect(c.text).toBe("Warning. Elevated carbon dioxide detected. Countermeasure protocol available. Retrieve medical kit ECLSS 03.");
  });
  it("advisories get no mandatory voice and silenced alerts stay quiet", () => {
    expect(cueFor({ ...base, event_type: "RAISED", kind: "CORRELATION", severity: "ADVISORY", protocol_id: null, parameter: null }, P)).toEqual({ tone: "advisory" });
    expect(cueFor({ ...base, silenced: true, event_type: "RAISED", kind: "THRESHOLD", severity: "WARNING", protocol_id: null, parameter: "heart_rate" }, P)).toEqual({});
  });
  it("announces recovery", () => {
    expect(cueFor({ ...base, event_type: "RECOVERY_STARTED", kind: "THRESHOLD", severity: "WARNING", protocol_id: null, parameter: "cabin_co2" }, P).text).toContain("Recovery in progress");
  });
});
