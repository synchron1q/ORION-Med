// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { describe, expect, it } from "vitest";
import { classifyResponse, nextDelayMs, summarize } from "./pvt";

describe("PVT logic", () => {
  it("summarizes reaction times with lapses", () => {
    expect(summarize([250, 300, 520])).toEqual({ responses: 3, meanRt: 356.7, medianRt: 300, lapses: 1 });
    expect(summarize([])).toEqual({ responses: 0, meanRt: null, medianRt: null, lapses: 0 });
  });
  it("classifies anticipations and responses without a stimulus as false starts", () => {
    expect(classifyResponse(null, 1000)).toEqual({ kind: "false_start" });
    expect(classifyResponse(1000, 1050)).toEqual({ kind: "false_start" });
    expect(classifyResponse(1000, 1280)).toEqual({ kind: "rt", rt: 280 });
  });
  it("randomizes the foreperiod between 1.5 and 3.5 s", () => {
    expect(nextDelayMs(() => 0)).toBe(1500);
    expect(nextDelayMs(() => 0.999)).toBeLessThan(3500);
  });
});
