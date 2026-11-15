// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import type { SeverityName } from "../types/state";

export const unitLabel = (u: string | null | undefined): string =>
  !u ? "" : u === "degC" ? "°C" : u.replace("uGy", "µGy");

export function fmtValue(v: number | null | undefined, digits?: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "----";
  const d = digits ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 10 ? 1 : 2);
  return v.toFixed(d);
}

export function fmtMET(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d, 3)}:${p(h)}:${p(m)}:${p(sec)}`;
}

export const fmtUtc = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toISOString().slice(11, 19) + "Z" : "--:--:--";

export function fmtAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "--";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export const ageFrom = (iso: string | null | undefined, now = Date.now()): number | null =>
  iso ? Math.max(0, (now - new Date(iso).getTime()) / 1000) : null;

export const SEV_TEXT: Record<SeverityName, string> = {
  WARNING: "text-hev-red",
  CAUTION: "text-hev-amber",
  ADVISORY: "text-hev-cyan",
  NOMINAL: "text-hev-green",
};
export const SEV_BORDER: Record<SeverityName, string> = {
  WARNING: "border-hev-red",
  CAUTION: "border-hev-amber",
  ADVISORY: "border-hev-cyan",
  NOMINAL: "border-hev-line",
};
export const SEV_BG: Record<SeverityName, string> = {
  WARNING: "bg-hev-red",
  CAUTION: "bg-hev-amber",
  ADVISORY: "bg-hev-cyan",
  NOMINAL: "bg-hev-green",
};
export const SEV_HEX: Record<SeverityName, string> = {
  WARNING: "#ff3b30",
  CAUTION: "#ffb000",
  ADVISORY: "#3fd8ff",
  NOMINAL: "#5fcf95",
};
export const SEV_RANK: Record<SeverityName, number> = { NOMINAL: 0, ADVISORY: 1, CAUTION: 2, WARNING: 3 };

export const severityLabel = (s: SeverityName): string =>
  s === "WARNING" ? "MASTER WARNING" : s === "CAUTION" ? "MASTER CAUTION" : s;
