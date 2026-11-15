// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Panel } from "../../components/Panel";
import { useHevStore } from "../../store/useHevStore";
import { ParamRow } from "./ParamRow";

const ORDER = ["heart_rate", "hrv", "spo2", "body_temp", "resp_rate", "hydration", "sleep_hours", "activity_level", "pvt_mean_rt"];

export function VitalsPanel() {
  const state = useHevStore((s) => s.state);
  const selectZone = useHevStore((s) => s.selectZone);
  const setModal = useHevStore((s) => s.setModal);
  const params = state ? ORDER.map((id) => state.parameters.find((p) => p.id === id)).filter((p) => p !== undefined) : [];
  const crew = state?.mission.crew.find((c) => c.monitored);
  return (
    <Panel
      title="Physiological telemetry"
      testId="vitals-panel"
      right={<span className="hev-label text-[10px]">{crew ? `${crew.id} · ${crew.role}` : ""}</span>}
      bodyClassName="flex flex-col"
    >
      <div className="hev-scroll flex-1 divide-y divide-hev-line/60">
        {params.map((p) => (
          <ParamRow key={p.id} p={p} alerts={state?.alerts ?? []} onSelect={() => selectZone(p.zone)} />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 border-t border-hev-line p-2">
        <button type="button" data-testid="open-pvt" onClick={() => setModal("pvt")}
          className="h-8 border border-hev-cyan/60 text-[11px] tracking-[0.16em] text-hev-cyan hover:bg-hev-cyan/10">
          PVT VIGILANCE TEST
        </button>
        <button type="button" data-testid="open-psych" onClick={() => setModal("psych")}
          className="h-8 border border-hev-cyan/60 text-[11px] tracking-[0.16em] text-hev-cyan hover:bg-hev-cyan/10">
          PRIVATE SELF-CHECK
        </button>
      </div>
    </Panel>
  );
}
