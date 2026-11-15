// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { SEV_RANK } from "../../services/format";
import type { Alert, SeverityName, ZoneId } from "../../types/state";

export const ZONE_IDS: ZoneId[] = ["head", "eyes", "cardiovascular", "respiratory", "musculoskeletal", "radiation"];

export function zoneSeverity(zone: ZoneId, alerts: Alert[]): SeverityName {
  let worst: SeverityName = "NOMINAL";
  for (const a of alerts) if (a.zone === zone && a.lifecycle !== "CLEARED" && SEV_RANK[a.severity] > SEV_RANK[worst]) worst = a.severity;
  return worst;
}

export function worstZone(alerts: Alert[]): ZoneId | null {
  let best: { z: ZoneId; r: number } | null = null;
  for (const z of ZONE_IDS) {
    const r = SEV_RANK[zoneSeverity(z, alerts)];
    if (r > 0 && (!best || r > best.r)) best = { z, r };
  }
  return best?.z ?? null;
}
