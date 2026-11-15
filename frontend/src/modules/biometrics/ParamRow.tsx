// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Chip, SourceBadge, Sparkline } from "../../components/Panel";
import { fmtAge, fmtValue, SEV_HEX, SEV_RANK, SEV_TEXT, unitLabel } from "../../services/format";
import type { Alert, ParameterState, SeverityName } from "../../types/state";

const STATUS_TEXT: Record<string, string> = {
  STALE: "DATA STALE",
  SENSOR_FAULT: "SENSOR FAULT",
  NO_DATA: "NO DATA",
  NOT_INSTRUMENTED: "NO SENSOR",
};

export function paramSeverity(p: ParameterState, alerts: Alert[]): SeverityName {
  let worst: SeverityName = p.status === "OK" ? (p.band ?? "NOMINAL") : "NOMINAL";
  for (const a of alerts) {
    if (a.parameter === p.id && a.kind !== "CORRELATION" && SEV_RANK[a.severity] > SEV_RANK[worst]) worst = a.severity;
  }
  return worst;
}

function limitsText(p: ParameterState): string {
  const t = p.thresholds;
  const lo = t.caution_low ?? t.advisory_low;
  const hi = t.caution_high ?? t.advisory_high;
  if (!p.available) return "NO SENSOR ON BOARD";
  if (lo === undefined && hi === undefined) return "NO LIMITS CONFIGURED";
  return `LIMITS ${lo !== undefined ? fmtValue(lo) : "--"} / ${hi !== undefined ? fmtValue(hi) : "--"}`;
}

export function ParamRow({ p, alerts, onSelect, compact = false }: {
  p: ParameterState; alerts: Alert[]; onSelect?: () => void; compact?: boolean;
}) {
  const sev = paramSeverity(p, alerts);
  const ok = p.status === "OK";
  const color = ok ? SEV_TEXT[sev] : p.status === "NOT_INSTRUMENTED" ? "text-hev-dim" : "text-hev-amber";
  const trend = p.trend.map(([, v]) => v);
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid={`param-${p.id}`}
      className={`group flex w-full items-stretch gap-2 border-l-2 bg-transparent px-2 text-left ${compact ? "py-1" : "py-1.5"} ${sev !== "NOMINAL" ? (sev === "WARNING" ? "border-hev-red bg-hev-red/5" : sev === "CAUTION" ? "border-hev-amber bg-hev-amber/5" : "border-hev-cyan") : "border-transparent"} hover:bg-hev-cyan/5`}
    >
      <div className="flex min-w-0 flex-1 flex-col justify-center">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold tracking-[0.12em] text-hev-white">{p.short}</span>
          {ok && <SourceBadge source={p.source} />}
          {!ok && <Chip className="border-hev-amber/70 text-hev-amber">{STATUS_TEXT[p.status] ?? p.status}</Chip>}
        </div>
        <span className="truncate text-[11px] text-hev-dim">{p.label}</span>
        {!compact && <span className="text-[10px] tracking-[0.08em] text-hev-dim/80">{limitsText(p)} · DEMO</span>}
      </div>
      {!compact && (
        <div className="flex items-center">
          <Sparkline points={trend.slice(-60)} color={ok ? SEV_HEX[sev] : "#45606a"} width={92} height={30} />
        </div>
      )}
      <div className="flex w-[104px] flex-col items-end justify-center">
        <div className={`hev-num leading-none ${compact ? "text-[20px]" : "text-[28px]"} ${color} ${sev === "WARNING" && ok ? "hev-flash" : ""}`}>
          {ok ? fmtValue(p.value) : "----"}
        </div>
        <div className="mt-0.5 text-[11px] text-hev-dim">
          {ok ? unitLabel(p.unit) : p.value !== null && p.status !== "NOT_INSTRUMENTED" ? `LAST ${fmtValue(p.value)} · ${fmtAge(p.age_s)}` : p.status === "NOT_INSTRUMENTED" ? "N/A" : "UNAVAILABLE"}
        </div>
      </div>
    </button>
  );
}
