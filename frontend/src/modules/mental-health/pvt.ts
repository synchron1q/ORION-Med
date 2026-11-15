// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
// Psychomotor Vigilance Test (PVT) - short 10-second demonstration version.
// Responses faster than MIN_RT_MS are anticipations (false starts); responses
// slower than LAPSE_MS are lapses; no response within RESPONSE_WINDOW_MS is a miss.
export const TEST_DURATION_MS = 10_000;
export const RESPONSE_WINDOW_MS = 1_500;
export const MIN_RT_MS = 100;
export const LAPSE_MS = 500;

export function nextDelayMs(rng: () => number = Math.random): number {
  return 1_500 + Math.floor(rng() * 2_000); // randomized 1.5-3.5 s foreperiod
}

export interface PvtSummary {
  responses: number;
  meanRt: number | null;
  medianRt: number | null;
  lapses: number;
}

export function summarize(reactionTimes: number[]): PvtSummary {
  const rts = reactionTimes.filter((x) => x >= MIN_RT_MS);
  if (rts.length === 0) return { responses: 0, meanRt: null, medianRt: null, lapses: 0 };
  const sorted = [...rts].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const mean = rts.reduce((a, b) => a + b, 0) / rts.length;
  return {
    responses: rts.length,
    meanRt: Math.round(mean * 10) / 10,
    medianRt: Math.round(median * 10) / 10,
    lapses: rts.filter((x) => x > LAPSE_MS).length,
  };
}

/** Classify one response given the stimulus onset (null = no stimulus visible). */
export function classifyResponse(onsetMs: number | null, nowMs: number): { kind: "false_start" } | { kind: "rt"; rt: number } {
  if (onsetMs === null) return { kind: "false_start" };
  const rt = nowMs - onsetMs;
  return rt < MIN_RT_MS ? { kind: "false_start" } : { kind: "rt", rt: Math.round(rt) };
}
