// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useEffect, useState } from "react";
import { Chip, Panel } from "../../components/Panel";
import { api, fitnessApi } from "../../services/api";
import type { DeviceStatus, FitnessConfig, FitnessState, ReferenceData } from "../../types/fitness";
import { DemoTag, type FitnessData, StatusChip, useFitnessAction } from "./common";

const STATUSES: DeviceStatus[] = ["OPERATIONAL", "DEGRADED", "FAULT", "MAINTENANCE"];
const TONE: Record<DeviceStatus, string> = {
  OPERATIONAL: "text-hev-green border-hev-green", DEGRADED: "text-hev-amber border-hev-amber", FAULT: "text-hev-red border-hev-red", MAINTENANCE: "text-hev-cyan border-hev-cyan",
};

export function EquipmentTab({ data, fitness, refresh }: { data: FitnessData | null; fitness: FitnessState; refresh: () => void }) {
  const run = useFitnessAction();
  const [cfg, setCfg] = useState<FitnessConfig | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  useEffect(() => {
    fitnessApi.config().then(setCfg).catch(() => setCfg(null));
    api.referenceData().then(setRefs).catch(() => setRefs(null));
  }, []);
  return (
    <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
      <div className="grid min-h-0 grid-cols-3 gap-2">
        {(fitness.equipment ?? []).map((d) => {
          const upcoming = (data?.schedule ?? []).filter((s) => s.device_id === d.id && ["PLANNED", "NOTIFIED", "IN_PROGRESS"].includes(s.status));
          return (
            <Panel key={d.id} title={`${d.id} · ${d.class}`} testId={`fitness-device-${d.id}`} bodyClassName="flex min-h-0 flex-col gap-2 p-2.5" right={<DemoTag text="SIMULATED" />}>
              <div className="text-[15px] font-semibold text-hev-white">{d.label}</div>
              <div data-testid={`fitness-device-${d.id}-status`} className={`text-[24px] font-bold tracking-[0.14em] ${TONE[d.status].split(" ")[0]}`}>{d.status}</div>
              {d.note && <div className="text-[11.5px] text-hev-white/75">{d.note}</div>}
              <div className="grid grid-cols-4 gap-1">
                {STATUSES.map((st) => (
                  <button key={st} type="button" data-testid={`fitness-device-${d.id}-${st}`} disabled={st === d.status}
                    onClick={() => void run(fitnessApi.equipment(d.id, st, st === "OPERATIONAL" ? "" : "Set from the crew interface (SIMULATED)"),
                      `${d.id} set to ${st}; planner re-run`).then(refresh)}
                    className={`h-7 border text-[9.5px] tracking-[0.1em] disabled:opacity-40 ${TONE[st]} hover:bg-white/5`}>{st}</button>
                ))}
              </div>
              <div className="hev-label mt-1 text-[10px]">Assigned sessions · {upcoming.length}</div>
              <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
                {upcoming.map((s) => (
                  <li key={s.id} className="flex items-center gap-2 text-[11.5px] text-hev-white/85">
                    <span className="w-[86px]">{s.planned_start_met}</span><span>{s.crew_id} · {s.exercise_type}</span><span className="flex-1" /><StatusChip status={s.status} />
                  </li>
                ))}
              </ul>
            </Panel>
          );
        })}
      </div>
      <div className="grid min-h-0 grid-cols-[minmax(0,0.9fr)_minmax(0,1fr)_minmax(0,1.1fr)] gap-2">
        <Panel title="Training program" testId="fitness-program" bodyClassName="min-h-0 overflow-y-auto p-2.5 text-[11.5px]" right={<DemoTag />}>
          {!cfg && <div className="text-hev-dim">Loading…</div>}
          {cfg && (
            <>
              <table className="w-full text-left">
                <thead className="text-[9.5px] tracking-[0.12em] text-hev-dim"><tr><th className="font-normal">CREW</th><th className="font-normal">SESSION</th><th className="font-normal">PREFERRED (MET-DAY HOUR)</th><th className="font-normal">DURATION · DEVICES</th></tr></thead>
                <tbody>
                  {cfg.program.map((p) => {
                    const t = cfg.exercise_types[p.exercise_type];
                    return (
                      <tr key={`${p.crew_id}-${p.ordinal}`} className="border-t border-hev-line/50 text-hev-white/85">
                        <td className="py-0.5">{p.crew_id}</td><td>{t?.label ?? p.exercise_type}</td><td>{p.preferred_start_h.toFixed(1)} h</td>
                        <td>{t?.duration_min} min · {t?.device_classes.join(" / ")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="mt-2 text-[9.5px] text-hev-dim">{cfg.provenance}</div>
            </>
          )}
        </Panel>
        <Panel title="In-session monitoring profiles · buffers" testId="fitness-profiles" bodyClassName="min-h-0 overflow-y-auto p-2.5 text-[11.5px]" right={<DemoTag />}>
          {cfg && (
            <>
              {Object.entries(cfg.profiles).map(([id, p]) => (
                <div key={id} className="border-b border-hev-line/50 py-1 text-hev-white/85">
                  <span className="font-semibold text-hev-cyan">{id}</span> · HR target {p.heart_rate_pct_hrmax.target_low}–{p.heart_rate_pct_hrmax.target_high} %, review &gt; {p.heart_rate_pct_hrmax.review_above} %, stop &gt; {p.heart_rate_pct_hrmax.stop_above} % of HRmax · SpO2 review &lt; {p.spo2.review_below}, stop &lt; {p.spo2.stop_below} %
                  {p.reference && <Chip className="ml-1 border-hev-white/50 text-hev-white/80">{p.reference}</Chip>}
                </div>
              ))}
              <div className="mt-1 text-hev-white/80" data-testid="fitness-alarm-policy">
                HR alarm policy during a confirmed session: <b>{cfg.exercise_alarm_policy === "context_hrmax"
                  ? `exercise context (caution > ${cfg.exercise_hr_alarm_pct_hrmax.caution_high} %, warning > ${cfg.exercise_hr_alarm_pct_hrmax.warning_high} % of HRmax), logged`
                  : "global limits"}</b>
              </div>
              <div className="mt-0.5 text-hev-white/70">
                SIMULATED HRmax: {Object.entries(cfg.crew_profiles).map(([c, v]) => `${c} ${v.hrmax_bpm}`).join(" · ")} bpm
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {Object.values(cfg.activity_rules).filter((r) => r.before_min || r.after_min).map((r) => (
                  <Chip key={r.type} className={r.scope === "vehicle" ? "border-hev-red/50 text-hev-red/90" : "border-hev-line text-hev-white/75"}>
                    {r.type} −{r.before_min}/+{r.after_min} min{r.scope === "vehicle" ? " · ALL CREW" : ""}
                  </Chip>
                ))}
              </div>
              <div className="mt-2 text-[9.5px] text-hev-dim">No alarm is suppressed; every switch of alarm limits is logged. Medical Clearance: max {cfg.clearance_max_validity_h} h, one crew member and one exercise type.</div>
            </>
          )}
        </Panel>
        <Panel title="NASA reference values · context only" testId="fitness-references" bodyClassName="min-h-0 overflow-y-auto p-2 text-[11px]"
          right={<span className="text-[9.5px] tracking-[0.1em] text-hev-dim">verified {refs?.verified_on ?? "--"}</span>}>
          {!refs && <div className="text-hev-dim">Loading…</div>}
          {refs && (
            <>
              <table className="w-full table-fixed text-left">
                <tbody>
                  {refs.values.map((v) => (
                    <tr key={v.id} className="border-b border-hev-line/50 align-top">
                      <td className="w-[52%] py-0.5 pr-1 text-hev-white/85">{v.label}</td>
                      <td className="hev-num w-[24%] text-hev-white">{Array.isArray(v.value) ? v.value.join(" / ") : v.value} <span className="text-hev-dim">{v.unit}</span></td>
                      <td className="text-[9.5px] text-hev-dim">
                        <span className={v.value_type === "STANDARD_REQUIREMENT" ? "text-hev-cyan" : ""}>{v.value_type.replace("_", " ")}</span>
                        <br />
                        <a href={v.source_url} target="_blank" rel="noreferrer" className="underline">{v.source}</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="mt-1 text-[9.5px] leading-snug text-hev-dim">{refs.provenance}. HEV-1 alarm limits remain DEMONSTRATION values.</div>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
