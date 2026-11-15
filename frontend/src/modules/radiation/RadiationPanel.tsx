// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Area, AreaChart, ReferenceLine, ResponsiveContainer, YAxis } from "recharts";
import { Chip, Panel } from "../../components/Panel";
import { api } from "../../services/api";
import { fmtUtc, fmtValue, SEV_TEXT } from "../../services/format";
import { useHevStore } from "../../store/useHevStore";

const TIER_STYLE: Record<string, string> = {
  LIVE: "border-hev-green text-hev-green",
  CACHED_OFFLINE: "border-hev-offline text-hev-offline",
  OFFLINE_BASELINE: "border-hev-dim text-hev-dim",
  SIMULATED: "border-hev-amber text-hev-amber",
};

export function RadiationPanel() {
  const state = useHevStore((s) => s.state);
  const setNotice = useHevStore((s) => s.setNotice);
  if (!state) return <Panel title="Radiation / space weather"><div /></Panel>;
  const rad = state.radiation;
  const doseParam = state.parameters.find((p) => p.id === "dose_rate");
  const data = (doseParam?.trend ?? []).map(([t, v]) => ({ t, v }));
  const caution = doseParam?.thresholds.caution_high;
  const warning = doseParam?.thresholds.warning_high;
  const dr = doseParam?.status === "OK" ? rad.dose_rate : null;
  const drSev = doseParam?.band ?? "NOMINAL";
  const frac = rad.budget_fraction ?? 0;
  const donki = state.nasa_donki;
  const sim = state.space_weather_simulation;
  const ctx = sim ?? donki;
  return (
    <Panel title="Radiation / space weather" testId="radiation-panel"
      right={<span className="hev-label text-[10px]">Whole-body exposure</span>} bodyClassName="flex gap-3 p-2">
      <div className="flex w-[205px] shrink-0 flex-col gap-1.5">
        <div className="flex items-baseline justify-between">
          <span className="hev-label text-[10px]">Dose rate</span>
          {rad.dose_rate_source === "SIMULATED" && <Chip className="border-hev-amber/60 text-hev-amber/90">SIM</Chip>}
        </div>
        <div className={`hev-num text-[30px] leading-none ${doseParam?.status === "OK" ? SEV_TEXT[drSev] : "text-hev-amber"}`}>
          {fmtValue(dr)} <span className="text-[12px] text-hev-dim">µGy/h</span>
        </div>
        <div className="h-[70px] border border-hev-line/60">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 2, bottom: 0, left: 0 }}>
              <YAxis hide domain={[0, (max: number) => Math.max(max * 1.1, 120)]} />
              {caution !== undefined && <ReferenceLine y={caution} stroke="#ffb000" strokeDasharray="3 3" />}
              {warning !== undefined && <ReferenceLine y={warning} stroke="#ff3b30" strokeDasharray="3 3" />}
              <Area type="monotone" dataKey="v" stroke="#3fd8ff" fill="#3fd8ff" fillOpacity={0.15} isAnimationActive={false} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="flex items-baseline justify-between">
          <span className="hev-label whitespace-nowrap text-[10px]">Mission dose</span>
          <span className="hev-num whitespace-nowrap text-[12px]">{fmtValue(rad.accumulated_mGy, 3)}/{rad.budget_mGy} mGy</span>
        </div>
        <div className="h-2 border border-hev-line" title="Demonstration mission dose budget">
          <div className={`h-full ${frac >= 0.8 ? "bg-hev-amber" : "bg-hev-cyan"}`} style={{ width: `${Math.min(100, frac * 100)}%` }} />
        </div>
        <span className="text-[10px] text-hev-dim">Budget: demonstration value</span>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1" data-testid="donki-context">
        <div className="flex items-center gap-1.5">
          <span className="hev-label text-[10px]">{sim ? "Simulated event" : "NASA DONKI context"}</span>
          <Chip className={TIER_STYLE[ctx.status] ?? "border-hev-dim text-hev-dim"}>{ctx.status.replace("_", " ")}</Chip>
          <span className="flex-1" />
          {!sim && (
            <button type="button" title="Request a DONKI refresh (max once per minute)"
              onClick={() => void api.refreshSpaceWeather().then((r) => setNotice(r.message)).catch(() => setNotice("Refresh unavailable"))}
              className="h-5 border border-hev-line px-1.5 text-[9px] tracking-[0.12em] text-hev-dim hover:text-hev-cyan">REFRESH</button>
          )}
        </div>
        <div className="text-[14px] font-semibold text-hev-white">{ctx.latest_event}</div>
        <div className="flex gap-3 text-[12px]">
          <span>RISK <span className={SEV_TEXT[ctx.space_weather_risk]}>{ctx.space_weather_risk}</span></span>
          <span className={ctx.space_weather_risk === "NOMINAL" ? "text-hev-white/80" : SEV_TEXT[ctx.space_weather_risk]}>{ctx.eva_advisory}</span>
        </div>
        <p className="m-0 text-[11px] leading-snug text-hev-dim">{ctx.radiation_context}</p>
        {sim && (
          <div className="text-[10.5px] text-hev-dim">Live DONKI: <span className="text-hev-white/80">{donki.status.replace("_", " ")} · {donki.latest_event}</span></div>
        )}
        <div className="mt-auto flex flex-wrap gap-x-3 text-[10px] text-hev-dim">
          {Object.entries(donki.feeds).map(([feed, f]) => (
            <span key={feed} title={f.error ?? undefined}>
              {feed}: <span className={f.last_status === "OK" ? "text-hev-green" : "text-hev-amber"}>{f.last_status ?? "--"}{f.http_status && f.last_status !== "OK" ? ` ${f.http_status}` : ""}</span>
              {f.endpoint?.startsWith("notifications") && <span className="text-hev-dim"> via notifications</span>}
            </span>
          ))}
          <span>LAST GOOD {donki.last_successful_fetch ? fmtUtc(donki.last_successful_fetch) : "NEVER"}</span>
          {donki.is_placeholder && <span className="text-hev-amber/80">PLACEHOLDER - NOT A NASA OBSERVATION</span>}
        </div>
        <div className="text-[9.5px] text-hev-dim/80">{donki.source}. Context only - not a dose measurement.</div>
      </div>
    </Panel>
  );
}
