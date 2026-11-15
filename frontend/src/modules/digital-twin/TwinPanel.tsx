// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Chip, Panel } from "../../components/Panel";
import { fmtValue, SEV_BORDER, SEV_TEXT, severityLabel, unitLabel } from "../../services/format";
import { useHevStore } from "../../store/useHevStore";
import type { ZoneId } from "../../types/state";
import { ParamRow } from "../biometrics/ParamRow";
import { HumanTwin } from "./HumanTwin";
import { worstZone, zoneSeverity } from "./zones";

function ConditionSummary() {
  const state = useHevStore((s) => s.state);
  if (!state) return null;
  const counts = { WARNING: 0, CAUTION: 0, ADVISORY: 0 };
  for (const a of state.alerts) counts[a.severity] += 1;
  const sev = state.medical_status;
  const text =
    state.alerts.length === 0
      ? "All monitored parameters are inside configured demonstration ranges."
      : `${counts.WARNING} warning, ${counts.CAUTION} caution, ${counts.ADVISORY} advisory active. Review the countermeasure guide.`;
  return (
    <div className={`flex items-center gap-3 border-l-4 px-3 py-2 ${SEV_BORDER[sev]} bg-black/40`} data-testid="condition-summary">
      <span className={`text-[15px] font-bold tracking-[0.16em] ${SEV_TEXT[sev]}`}>{sev === "NOMINAL" ? "CREW CONDITION NOMINAL" : severityLabel(sev)}</span>
      <span className="text-[13px] text-hev-white/85">{text}</span>
    </div>
  );
}

export function TwinPanel() {
  const state = useHevStore((s) => s.state);
  const selected = useHevStore((s) => s.selectedZone);
  const selectZone = useHevStore((s) => s.selectZone);
  const selectAlert = useHevStore((s) => s.selectAlert);
  const alerts = state?.alerts ?? [];
  const zone: ZoneId = selected ?? worstZone(alerts) ?? "cardiovascular";
  const zoneInfo = state?.zones?.[zone];
  const zoneParams = (state?.parameters ?? []).filter((p) => p.zone === zone);
  const zoneAlerts = alerts.filter((a) => a.zone === zone);
  const zs = zoneSeverity(zone, alerts);
  return (
    <Panel title="Digital human twin" testId="twin-panel" right={<span className="hev-label text-[10px]">Select an anatomical zone</span>} bodyClassName="flex flex-col gap-2 p-2">
      <ConditionSummary />
      <div className="flex min-h-0 flex-1 gap-3">
        <div className="relative h-full w-[460px] shrink-0 border border-hev-line/60 bg-black">
          {state && <HumanTwin alerts={alerts} params={state.parameters} selected={zone} onSelect={selectZone} />}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2" data-testid="zone-detail">
          <div className={`border-l-2 pl-2 ${SEV_BORDER[zs]}`}>
            <div className="flex items-center gap-2">
              <span className={`text-[17px] font-semibold tracking-[0.14em] ${zs === "NOMINAL" ? "text-hev-white" : SEV_TEXT[zs]}`}>{zoneInfo?.label ?? zone.toUpperCase()}</span>
              <Chip className={`${SEV_BORDER[zs]} ${zs === "NOMINAL" ? "text-hev-green" : SEV_TEXT[zs]}`}>{zs}</Chip>
            </div>
            <p className="m-0 mt-1 text-[12px] leading-snug text-hev-dim">{zoneInfo?.reference}</p>
          </div>
          <div className="hev-label">Related measurements</div>
          <div className="hev-scroll max-h-[210px] divide-y divide-hev-line/60 border border-hev-line/60">
            {zoneParams.length === 0 && <div className="p-3 text-[12px] text-hev-dim">No instrumented parameter for this zone. Nothing is assumed normal.</div>}
            {zoneParams.map((p) => (
              <ParamRow key={p.id} p={p} alerts={alerts} compact />
            ))}
          </div>
          <div className="hev-label">Active warnings in zone</div>
          <div className="hev-scroll flex min-h-0 flex-1 flex-col gap-1.5">
            {zoneAlerts.length === 0 && <div className="text-[12px] text-hev-dim">None.</div>}
            {zoneAlerts.map((a) => (
              <button key={a.id} type="button" onClick={() => selectAlert(a.id)}
                className={`border-l-2 bg-black/30 px-2 py-1.5 text-left ${SEV_BORDER[a.severity]}`}>
                <div className={`text-[12px] font-semibold tracking-[0.1em] ${SEV_TEXT[a.severity]}`}>{a.title}</div>
                {a.kind === "CORRELATION" && a.factors ? (
                  <div className="mt-0.5 text-[11px] text-hev-white/80">
                    Factors: {a.factors.map((f) => (f.factor === "space_weather_event" ? "space-weather event" : `${f.factor} ${f.value !== undefined ? fmtValue(f.value) : ""}`)).join(" · ")}
                  </div>
                ) : (
                  <div className="mt-0.5 text-[11px] text-hev-white/80">{a.message}</div>
                )}
                {a.kind === "THRESHOLD" && a.last_value !== null && (
                  <div className="hev-num text-[11px] text-hev-dim">LAST {fmtValue(a.last_value)} {unitLabel(a.unit)} · {a.data_source}</div>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}
