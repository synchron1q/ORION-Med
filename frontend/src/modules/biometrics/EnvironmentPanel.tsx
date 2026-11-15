// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Line, LineChart, ReferenceLine, ResponsiveContainer, YAxis } from "recharts";
import { Panel } from "../../components/Panel";
import { fmtValue, SEV_TEXT, unitLabel } from "../../services/format";
import { useHevStore } from "../../store/useHevStore";
import { ParamRow } from "./ParamRow";

export function EnvironmentPanel() {
  const state = useHevStore((s) => s.state);
  const selectZone = useHevStore((s) => s.selectZone);
  const params = (state?.parameters ?? []).filter((p) => p.category === "environmental");
  const co2 = params.find((p) => p.id === "cabin_co2");
  const others = params.filter((p) => p.id !== "cabin_co2");
  const data = (co2?.trend ?? []).map(([t, v]) => ({ t, v }));
  const sev = co2?.band ?? "NOMINAL";
  return (
    <Panel title="Cabin environment (ECLSS)" testId="environment-panel" bodyClassName="flex flex-col p-2">
      {co2 && (
        <button type="button" onClick={() => selectZone("respiratory")} className="flex items-stretch gap-2 text-left" data-testid="param-cabin_co2-big">
          <div className="flex w-[118px] flex-col">
            <span className="text-[13px] font-semibold tracking-[0.12em]">CO2</span>
            <span className={`hev-num text-[28px] leading-none ${co2.status === "OK" ? SEV_TEXT[sev] : "text-hev-amber"} ${sev === "WARNING" ? "hev-flash" : ""}`}>
              {co2.status === "OK" ? fmtValue(co2.value) : "----"}
            </span>
            <span className="text-[11px] text-hev-dim">{unitLabel(co2.unit)} · LIMITS {co2.thresholds.caution_high}/{co2.thresholds.warning_high}</span>
          </div>
          <div className="h-[64px] flex-1 border border-hev-line/60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 4, right: 2, bottom: 2, left: 0 }}>
                <YAxis hide domain={[0, (max: number) => Math.max(max * 1.1, 7)]} />
                <ReferenceLine y={co2.thresholds.caution_high} stroke="#ffb000" strokeDasharray="3 3" />
                <ReferenceLine y={co2.thresholds.warning_high} stroke="#ff3b30" strokeDasharray="3 3" />
                <Line type="monotone" dataKey="v" stroke="#3fd8ff" dot={false} strokeWidth={1.5} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </button>
      )}
      <div className="hev-scroll mt-1 flex-1 divide-y divide-hev-line/50">
        {others.map((p) => (
          <ParamRow key={p.id} p={p} alerts={state?.alerts ?? []} compact onSelect={() => selectZone(p.zone)} />
        ))}
      </div>
    </Panel>
  );
}
