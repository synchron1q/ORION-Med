// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Chip, Panel } from "../../components/Panel";
import { fitnessApi } from "../../services/api";
import type { RecoveryResult, RecoveryStatus, RecoveryView } from "../../types/fitness";
import { DemoTag } from "./common";

const TONE: Record<RecoveryStatus, string> = {
  RECOVERING: "text-hev-cyan border-hev-cyan", RECOVERED: "text-hev-green border-hev-green",
  REVIEW: "text-hev-amber border-hev-amber", DATA_INCOMPLETE: "text-hev-offline border-hev-offline",
};
const EFFECT: Record<RecoveryStatus, string> = {
  RECOVERING: "Next session of this crew member: BLOCKED while recovery is observed.",
  RECOVERED: "No recovery flag. Not a medical authorization.",
  REVIEW: "Next session: CLEARANCE REQUIRED (a clearance recorded after this finding).",
  DATA_INCOMPLETE: "Not treated as normal. Monitored crew member: CLEARANCE REQUIRED for the next session.",
};
const fmtS = (s: number | null | undefined) => (s === null || s === undefined ? "--" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);
const num = (v: number | null | undefined, unit = "") => (v === null || v === undefined ? "--" : `${v.toFixed(0)}${unit}`);

function Metric({ label, value, tone = "text-hev-white" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col border border-hev-line bg-black/40 px-2 py-1">
      <span className="hev-label text-[9.5px]">{label}</span>
      <span className={`hev-num text-[17px] ${tone}`}>{value}</span>
    </div>
  );
}

function CrewCard({ crewId, rec, monitored, onClick, selected }: {
  crewId: string; rec: RecoveryResult | null; monitored: boolean; onClick: () => void; selected: boolean;
}) {
  const progress = rec ? Math.min(100, (rec.elapsed_s / rec.window_s) * 100) : 0;
  return (
    <button type="button" data-testid={`recovery-card-${crewId}`} onClick={onClick} disabled={!rec}
      className={`flex min-w-0 flex-col border border-l-4 bg-hev-panel px-3 py-2 text-left ${selected ? "border-hev-white" : "border-hev-line"} ${rec ? TONE[rec.status].split(" ")[1].replace("border-", "border-l-") : "border-l-hev-line"}`}>
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-bold tracking-[0.12em] text-hev-white">{crewId}</span>
        <Chip className={monitored ? "border-hev-green/60 text-hev-green" : "border-hev-dim text-hev-dim"}>{monitored ? "BIOSENSOR" : "NO BIOSENSOR"}</Chip>
        <span className="flex-1" />
        {rec && !rec.final && <Chip className="border-hev-cyan/70 text-hev-cyan">LIVE</Chip>}
      </div>
      {rec ? (
        <>
          <div data-testid={`recovery-status-${crewId}`} className={`mt-1 text-[20px] font-bold tracking-[0.1em] ${TONE[rec.status].split(" ")[0]}`}>{rec.status.replace("_", " ")}</div>
          <div className="line-clamp-2 text-[11.5px] leading-snug text-hev-white/80" title={rec.summary}>{rec.summary}</div>
          <div className="mt-1 h-1 w-full bg-hev-line"><div className="h-1 bg-hev-cyan/70" style={{ width: `${progress}%` }} /></div>
          <div className="mt-1 text-[10px] text-hev-dim">{EFFECT[rec.status]}</div>
        </>
      ) : (
        <div className="mt-1 text-[12px] text-hev-dim">No finished session in the last 24 h</div>
      )}
    </button>
  );
}

export function RecoveryTab() {
  const [view, setView] = useState<RecoveryView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => fitnessApi.recovery().then((v) => alive && setView(v)).catch(() => undefined);
    load();
    const t = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (!view) return <div className="p-4 text-[12px] text-hev-dim">Loading recovery data…</div>;
  const item = view.items.find((i) => i.session.id === selected)
    ?? view.items.find((i) => i.session.crew_id === view.monitored_crew_id) ?? view.items[0] ?? null;
  const rec = item?.recovery ?? null;
  const c = view.criteria;
  const data = (item?.curve ?? []).map(([t, v]) => ({ t, v }));
  return (
    <div data-testid="fitness-recovery" className="grid min-h-0 flex-1 grid-rows-[150px_minmax(0,1fr)] gap-2">
      <div className="grid min-h-0 grid-cols-4 gap-2">
        {view.latest_by_crew.map((l) => (
          <CrewCard key={l.crew_id} crewId={l.crew_id} rec={l.recovery} monitored={l.crew_id === view.monitored_crew_id}
            selected={!!item && item.session.id === l.session_id} onClick={() => l.session_id && setSelected(l.session_id)} />
        ))}
      </div>
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)_500px] gap-2">
        <Panel title={item ? `Heart-rate recovery · ${item.session.crew_id} · ${item.session.exercise_label} · ${item.session.id}` : "Heart-rate recovery"}
          testId="recovery-curve" bodyClassName="flex min-h-0 flex-col gap-2 p-2.5" right={<DemoTag text="DEMONSTRATION CRITERIA" />}>
          {!item && <div className="text-[12px] text-hev-dim">No finished session in the last {c.validity_h} h. Complete a session to start recovery monitoring.</div>}
          {item && rec && (
            <>
              <div className="grid grid-cols-7 gap-1.5">
                <Metric label="Status" value={rec.status.replace("_", " ")} tone={TONE[rec.status].split(" ")[0]} />
                <Metric label="Pre-session HR" value={num(rec.baseline_hr, " bpm")} />
                <Metric label="Peak / end HR" value={`${num(rec.peak_hr)} / ${num(rec.end_hr)}`} />
                <Metric label="60-s drop (HRR60)" value={num(rec.hrr60, " bpm")} tone={rec.hrr60 !== null && rec.hrr60 < c.hrr60_min_bpm ? "text-hev-amber" : "text-hev-white"} />
                <Metric label="120-s drop" value={num(rec.hrr120, " bpm")} />
                <Metric label="Back to baseline" value={rec.time_to_baseline_s === null ? "--" : `${fmtS(rec.time_to_baseline_s)} min`} />
                <Metric label="Observed" value={`${fmtS(rec.elapsed_s)} / ${c.window_min} min`} />
              </div>
              <div className="min-h-0 flex-1" data-testid="recovery-chart">
                {data.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                      <CartesianGrid stroke="#0a1a1f" />
                      <XAxis dataKey="t" type="number" domain={[0, rec.window_s]} tickFormatter={(t: number) => `${Math.round(t / 60)}m`}
                        ticks={Array.from({ length: Math.floor(rec.window_s / 60) + 1 }, (_, i) => i * 60)} stroke="#6f8f99" fontSize={11} />
                      <YAxis domain={[(min: number) => Math.floor(Math.min(min, rec.baseline_hr ?? min) - 10), (max: number) => Math.ceil(Math.max(max, rec.end_hr ?? max) + 10)]}
                        stroke="#6f8f99" fontSize={11} width={40} />
                      <Tooltip contentStyle={{ background: "#000", border: "1px solid #133540", fontSize: 12 }} labelFormatter={(t) => `+${t} s`} formatter={(v) => [`${v} bpm`, "HR (SIMULATED)"]} />
                      {rec.baseline_hr !== null && <ReferenceLine y={rec.baseline_hr} stroke="#6f8f99" strokeDasharray="2 4" label={{ value: "pre-session", fill: "#6f8f99", fontSize: 10, position: "insideBottomRight" }} />}
                      {rec.threshold_hr !== null && <ReferenceLine y={rec.threshold_hr} stroke="#5fcf95" strokeDasharray="4 3" label={{ value: `baseline + ${c.baseline_tolerance_bpm}`, fill: "#5fcf95", fontSize: 10, position: "insideTopRight" }} />}
                      <ReferenceLine x={60} stroke="#3fd8ff" strokeDasharray="4 3" label={{ value: "+60 s", fill: "#3fd8ff", fontSize: 10, position: "insideTopLeft" }} />
                      <Line type="monotone" dataKey="v" stroke="#e6f6ff" strokeWidth={1.8} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-[12px] text-hev-offline">
                    {item.session.monitored ? "No heart-rate samples after the session - not treated as normal." : "No biosensor data stream for this crew member."}
                  </div>
                )}
              </div>
              <div className="text-[9.5px] leading-snug text-hev-dim">{rec.note}</div>
            </>
          )}
        </Panel>
        <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2">
          <Panel title="Recovery criteria" testId="recovery-criteria" bodyClassName="p-2.5 text-[11.5px] leading-snug text-hev-white/85" right={<DemoTag />}>
            <ul className="space-y-0.5">
              <li>Observation window: {c.window_min} min after the session ends</li>
              <li>REVIEW if the 60-s drop is below {c.hrr60_min_bpm} bpm after an elevated response (end HR ≥ pre-session + {c.elevated_response_bpm} bpm)</li>
              <li>RECOVERED when HR is back within pre-session + {c.baseline_tolerance_bpm} bpm and the 60-s criterion is met</li>
              <li>REVIEW if not back within the window; DATA INCOMPLETE if HR data is missing when needed</li>
              <li>A result affects the next session of the same crew member for {c.validity_h} h</li>
            </ul>
          </Panel>
          <Panel title="Recent sessions" testId="recovery-history" bodyClassName="min-h-0 overflow-y-auto p-2">
            {view.items.length === 0 && <div className="text-[11.5px] text-hev-dim">No finished session yet.</div>}
            {view.items.map((i) => (
              <button key={i.session.id} type="button" onClick={() => setSelected(i.session.id)}
                className={`flex w-full items-center gap-2 border-b border-hev-line/60 px-1 py-1 text-left text-[11.5px] hover:bg-hev-cyan/5 ${item?.session.id === i.session.id ? "bg-hev-cyan/10" : ""}`}>
                <span className="w-[42px] font-semibold text-hev-white">{i.session.crew_id}</span>
                <span className="w-[86px] text-hev-white/80">{i.session.exercise_type}</span>
                <span className="w-[74px] text-hev-dim">{i.session.status}</span>
                <span className="hev-num w-[70px] text-hev-dim">{i.session.actual_end?.slice(11, 19)}Z</span>
                <span className="flex-1" />
                {i.recovery && <Chip className={TONE[i.recovery.status]}>{i.recovery.status.replace("_", " ")}</Chip>}
              </button>
            ))}
          </Panel>
        </div>
      </div>
    </div>
  );
}
