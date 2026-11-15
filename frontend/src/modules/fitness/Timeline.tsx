// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import type { ReactNode } from "react";
import type { Equipment, ExerciseSession, PlanActivity, PlanView } from "../../types/fitness";
import { fmtMetH, GATE_DOT, metHours } from "./common";

const WINDOW_BEFORE_H = 1;
const WINDOW_H = 24;
const VEHICLE_TYPES = new Set(["MANEUVER", "CRITICAL_OPS", "DOCKING"]);

const ACT_TONE: Record<string, string> = {
  SLEEP: "bg-hev-offline/25 border-hev-offline/50 text-hev-white/70",
  EVA: "bg-hev-amber/25 border-hev-amber/60 text-hev-amber",
  EVA_PREP: "bg-hev-amber/15 border-hev-amber/40 text-hev-amber/90",
  MANEUVER: "bg-hev-red/20 border-hev-red/60 text-hev-red",
  CRITICAL_OPS: "bg-hev-red/20 border-hev-red/60 text-hev-red",
  DOCKING: "bg-hev-red/20 border-hev-red/60 text-hev-red",
  MAINTENANCE: "bg-hev-cyan/10 border-hev-cyan/40 text-hev-cyan/80",
};
const SESSION_TONE: Record<string, string> = {
  PLANNED: "bg-hev-cyan/15 border-hev-cyan/70 text-hev-cyan",
  NOTIFIED: "bg-hev-cyan/35 border-hev-cyan text-hev-white",
  IN_PROGRESS: "bg-hev-green/45 border-hev-green text-black",
  COMPLETED: "bg-hev-green/15 border-hev-green/50 text-hev-green",
  ABORTED: "bg-hev-red/10 border-hev-red/60 text-hev-red",
  MISSED: "bg-hev-red/10 border-hev-red/60 text-hev-red",
};

interface Props {
  plan: PlanView;
  sessions: ExerciseSession[];
  crew: string[];
  devices: Equipment[];
  nowIso: string;
  metStartIso: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function PlanTimeline({ plan, sessions, crew, devices, nowIso, metStartIso, selectedId, onSelect }: Props) {
  const now = new Date(nowIso).getTime();
  const t0 = now - WINDOW_BEFORE_H * 3_600_000;
  const t1 = t0 + WINDOW_H * 3_600_000;
  const pos = (aIso: string, bIso: string) => {
    const a = Math.max(t0, new Date(aIso).getTime());
    const b = Math.min(t1, new Date(bIso).getTime());
    return b <= a ? null : { left: `${((a - t0) / (t1 - t0)) * 100}%`, width: `${((b - a) / (t1 - t0)) * 100}%` };
  };
  const shift = (iso: string, min: number) => new Date(new Date(iso).getTime() + min * 60_000).toISOString();
  const metNow = metHours(nowIso, metStartIso);
  const firstHour = Math.ceil(metNow - WINDOW_BEFORE_H);
  const ticks = Array.from({ length: WINDOW_H }, (_, i) => firstHour + i);
  const tickLeft = (h: number) => `${(((h - (metNow - WINDOW_BEFORE_H)) / WINDOW_H) * 100).toFixed(3)}%`;

  const activityBlock = (a: PlanActivity, row: string) => {
    const p = pos(a.start, a.end);
    const buf = pos(shift(a.start, -a.buffer_before_min), shift(a.end, a.buffer_after_min));
    if (!p && !buf) return null;
    return (
      <div key={`${row}-${a.id}`}>
        {buf && (a.buffer_before_min > 0 || a.buffer_after_min > 0) && (
          <div className="absolute bottom-1 top-1 border border-dashed border-hev-dim/30 bg-hev-dim/5" style={buf} title={`Buffer -${a.buffer_before_min}/+${a.buffer_after_min} min`} />
        )}
        {p && (
          <div data-testid={`tl-activity-${a.id}`} title={`${a.type} · ${a.title} · ${a.start_met}–${a.end_met} · ${a.origin}${a.origin === "RUNTIME" ? ` (${a.source})` : ""}`}
            className={`absolute bottom-1.5 top-1.5 overflow-hidden whitespace-nowrap border px-1 text-[9.5px] leading-[24px] ${ACT_TONE[a.type] ?? "border-hev-line bg-hev-line/40 text-hev-dim"} ${a.origin === "RUNTIME" ? "border-dashed" : ""}`}
            style={p}>
            {a.origin === "RUNTIME" ? `${a.id} ` : ""}{a.type === "SLEEP" ? "SLEEP" : a.title}
          </div>
        )}
      </div>
    );
  };

  const sessionBlock = (s: ExerciseSession, row: string) => {
    const startIso = s.status === "IN_PROGRESS" && s.actual_start ? s.actual_start : s.planned_start;
    const endIso = s.status === "IN_PROGRESS" && s.actual_start ? shift(s.actual_start, s.duration_min ?? 30) : s.planned_end;
    if (!startIso || !endIso) return null;
    const p = pos(startIso, endIso);
    if (!p) return null;
    return (
      <button key={`${row}-${s.id}`} type="button" data-testid={`tl-session-${row}-${s.id}`} onClick={() => onSelect(s.id)}
        title={`${s.id} · ${s.status} · ${s.planned_start_met ?? ""} · ${s.device_id ?? ""}${s.gate ? ` · gate ${s.gate.status}` : ""}`}
        className={`absolute bottom-1 top-1 z-10 overflow-hidden whitespace-nowrap border-2 px-0.5 text-left text-[10px] font-semibold leading-[24px] ${SESSION_TONE[s.status] ?? "border-hev-dim text-hev-dim"} ${selectedId === s.id ? "outline outline-2 outline-hev-white" : ""}`}
        style={p}>
        {s.gate && <span className={`absolute right-0.5 top-0.5 h-1.5 w-1.5 ${GATE_DOT[s.gate.status]}`} />}
        {row.startsWith("CM-") ? (s.exercise_type === "AEROBIC" ? "AER" : "RES") : s.crew_id.replace("CM-", "C")}
      </button>
    );
  };

  const visible = sessions.filter((s) => !["UNSCHEDULED", "CANCELLED"].includes(s.status));
  const rows: { id: string; label: string; sub: string; content: ReactNode }[] = [
    {
      id: "VEHICLE", label: "VEHICLE", sub: plan.phase_now?.type ?? "",
      content: (
        <>
          {plan.phases.map((ph) => {
            const p = pos(ph.start, ph.end);
            return p && !ph.exercise_allowed ? (
              <div key={ph.id} className="absolute inset-y-0 bg-[repeating-linear-gradient(45deg,rgba(255,59,48,0.18)_0_4px,transparent_4px_9px)]" style={p} title={`${ph.title}: exercise forbidden`} />
            ) : null;
          })}
          {plan.activities.filter((a) => VEHICLE_TYPES.has(a.type) || a.scope === "vehicle").map((a) => activityBlock(a, "VEHICLE"))}
        </>
      ),
    },
    ...crew.map((c) => ({
      id: c, label: c, sub: "",
      content: (
        <>
          {plan.activities.filter((a) => a.scope !== "vehicle" && (a.crew.includes("ALL") || a.crew.includes(c))).map((a) => activityBlock(a, c))}
          {visible.filter((s) => s.crew_id === c).map((s) => sessionBlock(s, c))}
        </>
      ),
    })),
    ...devices.map((d) => ({
      id: d.id, label: d.id, sub: d.status,
      content: (
        <>
          {plan.activities.filter((a) => a.device_id === d.id).map((a) => activityBlock(a, d.id))}
          {d.status !== "OPERATIONAL" && <div className="absolute inset-0 bg-hev-red/10" title={`${d.label}: ${d.status}`} />}
          {visible.filter((s) => s.device_id === d.id).map((s) => sessionBlock(s, d.id))}
        </>
      ),
    })),
  ];

  return (
    <div data-testid="fitness-timeline" className="flex min-h-0 flex-1 flex-col">
      <div className="relative ml-[88px] h-5 border-b border-hev-line">
        {ticks.map((h) => (
          <span key={h} className="absolute top-0.5 -translate-x-1/2 text-[9.5px] tracking-[0.06em] text-hev-dim" style={{ left: tickLeft(h) }}>
            {h % 2 === 0 ? fmtMetH(h).replace("MET ", "") : ""}
          </span>
        ))}
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col">
        {rows.map((r, i) => (
          <div key={r.id} className={`flex min-h-[34px] flex-1 border-b border-hev-line/60 ${i === 0 || i === crew.length ? "border-b-hev-line" : ""}`}>
            <div className="flex w-[88px] shrink-0 flex-col justify-center border-r border-hev-line px-2">
              <span className="text-[11px] font-semibold tracking-[0.1em] text-hev-white">{r.label}</span>
              {r.sub && <span className={`text-[9px] tracking-[0.08em] ${r.sub === "OPERATIONAL" || r.sub === "CRUISE" ? "text-hev-dim" : "text-hev-amber"}`}>{r.sub}</span>}
            </div>
            <div className="relative min-w-0 flex-1">
              {ticks.map((h) => <div key={h} className="absolute inset-y-0 w-px bg-hev-grid" style={{ left: tickLeft(h) }} />)}
              {r.content}
            </div>
          </div>
        ))}
        <div className="pointer-events-none absolute inset-y-0 z-20 w-px bg-hev-cyan" style={{ left: `calc(88px + (100% - 88px) * ${WINDOW_BEFORE_H / WINDOW_H})` }}>
          <span className="absolute -top-0.5 left-1 text-[9px] text-hev-cyan">NOW</span>
        </div>
      </div>
    </div>
  );
}
