// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useState } from "react";
import { Chip, Panel } from "../../components/Panel";
import { fitnessApi } from "../../services/api";
import { fmtUtc } from "../../services/format";
import { useHevStore } from "../../store/useHevStore";
import type { FitnessState } from "../../types/fitness";
import { DemoTag, type FitnessData, useFitnessAction } from "./common";

const ACTION_TONE: Record<string, string> = {
  CREATED: "border-hev-dim text-hev-dim", MOVED: "border-hev-amber/70 text-hev-amber", DEVICE_REASSIGNED: "border-hev-cyan/70 text-hev-cyan",
  MISSED: "border-hev-red/70 text-hev-red", RESCHEDULED: "border-hev-amber/70 text-hev-amber", NOT_RESCHEDULED: "border-hev-red/70 text-hev-red",
  UNSCHEDULABLE: "border-hev-red/70 text-hev-red", PLACED: "border-hev-green/70 text-hev-green", CANCELLED: "border-hev-dim text-hev-dim",
  CREW_REQUEST: "border-hev-cyan/70 text-hev-cyan",
};
const TYPES = ["MANEUVER", "CRITICAL_OPS", "DOCKING", "EVA_PREP", "MEDICAL", "WORK", "CONFERENCE"];

function AddActivity({ crew, onDone }: { crew: string[]; onDone: () => void }) {
  const run = useFitnessAction();
  const [type, setType] = useState("MANEUVER");
  const [title, setTitle] = useState("Unplanned attitude maneuver");
  const [who, setWho] = useState("ALL");
  const [inMin, setInMin] = useState(10);
  const [dur, setDur] = useState(30);
  const [source, setSource] = useState("SIMULATED");
  const input = "h-7 min-w-0 border border-hev-line bg-black px-2 text-[11.5px] text-hev-white";
  return (
    <Panel title="Insert unplanned activity" testId="fitness-add-activity" bodyClassName="flex flex-col gap-1.5 p-2.5">
      <div className="grid grid-cols-[1fr_1fr] gap-1.5">
        <select aria-label="Activity type" value={type} onChange={(e) => setType(e.target.value)} className={input}>
          {TYPES.map((t) => <option key={t}>{t}</option>)}
        </select>
        <select aria-label="Crew" value={who} onChange={(e) => setWho(e.target.value)} className={input}>
          {["ALL", ...crew].map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <input aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)} className={input} />
      <div className="grid grid-cols-3 gap-1.5 text-[10px] tracking-[0.1em] text-hev-dim">
        <label className="flex flex-col gap-0.5">START IN (MIN)<input aria-label="Start in minutes" type="number" min={0} value={inMin} onChange={(e) => setInMin(Number(e.target.value))} className={input} /></label>
        <label className="flex flex-col gap-0.5">DURATION (MIN)<input aria-label="Duration minutes" type="number" min={1} value={dur} onChange={(e) => setDur(Number(e.target.value))} className={input} /></label>
        <label className="flex flex-col gap-0.5">SOURCE<select aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)} className={input}><option>SIMULATED</option><option>MANUAL</option></select></label>
      </div>
      <button type="button" data-testid="fitness-add-submit"
        onClick={() => void run(fitnessApi.addActivity({ activity_type: type, title, crew: [who], start_in_min: inMin, duration_min: dur, source }),
          `${type} added as a runtime activity; planner re-run`).then((ok) => ok && onDone())}
        className="h-8 border border-hev-cyan px-3 text-[11px] font-semibold tracking-[0.14em] text-hev-cyan hover:bg-hev-cyan/10">
        ADD AND REPLAN
      </button>
      <div className="text-[9.5px] leading-snug text-hev-dim">Stored as a runtime activity (RT-…). The baseline file config/mission_plan.yaml is never modified.</div>
    </Panel>
  );
}

export function PlannerTab({ data, fitness, refresh }: { data: FitnessData | null; fitness: FitnessState; refresh: () => void }) {
  const run = useFitnessAction();
  const state = useHevStore((s) => s.state);
  const select = useHevStore((s) => s.selectSession);
  const setTab = useHevStore((s) => s.setFitnessTab);
  if (!state) return null;
  const crew = state.mission.crew.map((c) => c.id);
  const decisions = data?.decisions ?? [];
  const lastReason = (sid: string) => decisions.find((d) => d.session_id === sid && d.action === "UNSCHEDULABLE")?.reason ?? "";
  const runtime = (data?.plan.activities ?? []).filter((a) => a.origin === "RUNTIME");
  const open = (sid: string) => {
    select(sid);
    setTab("schedule");
  };
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_480px] gap-2">
      <Panel title="Planner decision history" testId="fitness-decisions" bodyClassName="min-h-0 overflow-y-auto"
        right={<span className="text-[10px] tracking-[0.1em] text-hev-dim">original window · conflict · reason · new window</span>}>
        <table className="w-full table-fixed border-collapse text-[11px]">
          <thead className="sticky top-0 bg-hev-panel text-left text-[9.5px] tracking-[0.12em] text-hev-dim">
            <tr className="border-b border-hev-line">
              <th className="w-[74px] px-2 py-1 font-normal">UTC</th>
              <th className="w-[136px] px-1 font-normal">ACTION</th>
              <th className="w-[170px] px-1 font-normal">SESSION</th>
              <th className="w-[250px] px-1 font-normal">ORIGINAL → NEW WINDOW</th>
              <th className="px-1 font-normal">CONFLICT · REASON</th>
              <th className="w-[150px] px-1 font-normal">TRIGGER</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d) => (
              <tr key={d.id ?? d.timestamp} data-testid={`decision-${d.action}`} className="cursor-pointer border-b border-hev-line/50 align-top hover:bg-hev-cyan/5" onClick={() => open(d.session_id)}>
                <td className="hev-num px-2 py-1 text-hev-dim">{fmtUtc(d.timestamp)}</td>
                <td className="px-1 py-1"><Chip className={ACTION_TONE[d.action] ?? "border-hev-dim text-hev-dim"}>{d.action.replace("_", " ")}</Chip></td>
                <td className="truncate px-1 py-1 text-hev-white">{d.crew_id} · {d.exercise_type} · D{String(d.session_id.slice(4, 7))}</td>
                <td className="px-1 py-1 text-hev-white/85">
                  {d.from_start_met ?? "—"}{d.from_device ? ` ${d.from_device}` : ""} → {d.to_start_met ?? "—"}{d.to_device ? ` ${d.to_device}` : ""}
                </td>
                <td className="px-1 py-1 text-hev-white/75">
                  {d.conflict_code && <span className="mr-1 text-hev-amber">[{d.conflict_code}{d.conflict_ref ? ` ${d.conflict_ref}` : ""}]</span>}
                  <span className="line-clamp-2" title={d.reason}>{d.reason}</span>
                </td>
                <td className="truncate px-1 py-1 text-hev-dim">{d.trigger}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <div className="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-2">
        <AddActivity crew={crew} onDone={refresh} />
        <Panel title="Runtime additions (SQLite)" testId="fitness-runtime-activities" bodyClassName="max-h-[150px] overflow-y-auto p-2">
          {runtime.length === 0 && <div className="text-[11.5px] text-hev-dim">No unplanned activity in the horizon.</div>}
          {runtime.map((a) => (
            <div key={a.id} className="flex items-center gap-2 border-b border-hev-line/60 py-1 text-[11.5px]">
              <span className="font-semibold text-hev-cyan">{a.id}</span>
              <span className="truncate text-hev-white/85">{a.type} · {a.title} · {a.start_met}–{a.end_met.replace("MET ", "")} · {a.crew.join(",")}</span>
              <Chip className="border-hev-dim text-hev-dim">{a.source}</Chip>
              <span className="flex-1" />
              {a.editable && (
                <button type="button" data-testid={`fitness-cancel-${a.id}`} onClick={() => void run(fitnessApi.cancelActivity(a.id), `${a.id} cancelled; planner re-run`).then(refresh)}
                  className="h-6 border border-hev-line px-2 text-[10px] tracking-[0.1em] text-hev-dim hover:text-hev-white">CANCEL</button>
              )}
            </div>
          ))}
        </Panel>
        <Panel title={`Sessions without a valid window · ${(fitness.unscheduled ?? []).length}`} testId="fitness-unscheduled" bodyClassName="min-h-0 overflow-y-auto p-2">
          {(fitness.unscheduled ?? []).length === 0 && <div className="text-[11.5px] text-hev-dim">All program sessions in the horizon have a window.</div>}
          {(fitness.unscheduled ?? []).map((s) => (
            <button key={s.id} type="button" onClick={() => open(s.id)} className="block w-full border-b border-hev-line/60 py-1 text-left text-[11.5px] hover:bg-hev-amber/5">
              <span className="font-semibold text-hev-amber">{s.crew_id} · {s.exercise_type} · day {s.day_index}</span>
              <div className="line-clamp-2 text-hev-white/70">{lastReason(s.id)}</div>
            </button>
          ))}
        </Panel>
        <Panel title="Mission plan · source of truth" bodyClassName="p-2.5 text-[11.5px] leading-snug">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-hev-white">{data?.plan.plan_id ?? fitness.plan?.plan_id} rev {fitness.plan?.revision}</span>
            <span className="hev-num text-hev-dim">hash {fitness.plan?.content_hash}</span>
            <span className="flex-1" />
            <DemoTag text="SIMULATED" />
          </div>
          <div className="mt-1 text-hev-white/75">Baseline: config/mission_plan.yaml (never copied to the database). Runtime additions: SQLite. Every decision records the plan hash.</div>
          <div className="mt-1 text-hev-white/75">Phase now: {fitness.plan?.phase_now?.title ?? "--"} ({fitness.plan?.phase_now?.type ?? "--"}) — cruise is not treated as automatically safe.</div>
        </Panel>
      </div>
    </div>
  );
}
