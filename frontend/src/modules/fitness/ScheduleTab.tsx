// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useState } from "react";
import { Chip, Panel } from "../../components/Panel";
import { fitnessApi } from "../../services/api";
import { SEV_TEXT } from "../../services/format";
import { useHevStore } from "../../store/useHevStore";
import type { ExerciseSession, FitnessState, Gate, SessionDetail } from "../../types/fitness";
import { DemoTag, GATE_TEXT, GATE_TONE, GateBadge, StatusChip, useFitnessAction, type FitnessData } from "./common";
import { PlanTimeline } from "./Timeline";

const RECOVERY_TONE: Record<string, string> = {
  RECOVERING: "text-hev-cyan", RECOVERED: "text-hev-green", REVIEW: "text-hev-amber", DATA_INCOMPLETE: "text-hev-offline",
};
const REASON_TONE = { BLOCK: "text-hev-red", CLEARANCE: "text-hev-amber", INFO: "text-hev-dim" } as const;
const BAND_TONE: Record<string, string> = {
  IN_TARGET: "text-hev-green border-hev-green/60", BELOW_TARGET: "text-hev-cyan border-hev-cyan/60", ABOVE_TARGET: "text-hev-amber border-hev-amber/60",
  REVIEW: "text-hev-amber border-hev-amber", STOP_RECOMMENDED: "text-hev-red border-hev-red", DATA_INCOMPLETE: "text-hev-offline border-hev-offline",
};

function NextCard({ crewId, monitored, s, onSelect, selected }: {
  crewId: string; monitored: boolean; s: ExerciseSession | null; onSelect: (id: string) => void; selected: boolean;
}) {
  return (
    <button type="button" data-testid={`fitness-next-${crewId}`} disabled={!s} onClick={() => s && onSelect(s.id)}
      className={`flex min-w-0 flex-col justify-center border border-l-4 bg-hev-panel px-3 py-1.5 text-left ${selected ? "border-hev-white" : "border-hev-line"} ${s?.gate ? GATE_TONE[s.gate.status].split(" ")[0].replace("border-", "border-l-") : s?.status === "IN_PROGRESS" ? "border-l-hev-green" : "border-l-hev-line"}`}>
      <div className="flex items-center gap-1.5">
        <span className="text-[13px] font-bold tracking-[0.12em] text-hev-white">{crewId}</span>
        <Chip className={monitored ? "border-hev-green/60 text-hev-green" : "border-hev-dim text-hev-dim"}>{monitored ? "BIOSENSOR" : "NO BIOSENSOR"}</Chip>
        <span className="flex-1" />
        {s && <StatusChip status={s.status} />}
      </div>
      {s ? (
        <>
          <div className="mt-1 truncate text-[15px] font-semibold tracking-[0.06em] text-hev-cyan">
            {s.exercise_label.toUpperCase()} · {s.planned_start_met ?? "--"}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-hev-white/75">
            <span className="truncate">{s.device_label ?? "no device"}</span>
            <span className="flex-1" />
            {s.status === "IN_PROGRESS" ? <Chip className="border-hev-green text-hev-green">IN SESSION</Chip> : <GateBadge gate={s.gate} />}
          </div>
        </>
      ) : (
        <div className="mt-1 text-[12px] text-hev-dim">No session in the planning horizon</div>
      )}
    </button>
  );
}

function GateBlock({ gate, title }: { gate: Gate; title: string }) {
  return (
    <div className={`border border-l-4 bg-black/40 px-3 py-2 ${GATE_TONE[gate.status].split(" ")[0]} ${GATE_TONE[gate.status].split(" ")[0].replace("border-", "border-l-")}`}>
      <div className="flex items-center gap-2">
        <span className="hev-label text-[10px]">{title}</span>
        <span className="flex-1" />
        <DemoTag text="DEMONSTRATION RULES" />
      </div>
      <div data-testid="fitness-gate-status" className={`mt-1 text-[20px] font-bold tracking-[0.12em] ${GATE_TONE[gate.status].split(" ")[1]}`}>{GATE_TEXT[gate.status]}</div>
      <ul className="mt-1 space-y-0.5" data-testid="fitness-gate-reasons">
        {gate.reasons.length === 0 && <li className="text-[11.5px] text-hev-white/70">No blocker found by the configured rules.</li>}
        {gate.reasons.map((r, i) => (
          <li key={i} className={`text-[11.5px] leading-snug ${REASON_TONE[r.level]}`}>
            <span className="mr-1 font-semibold">{r.level === "BLOCK" ? "■" : r.level === "CLEARANCE" ? "▲" : "·"}</span>{r.text}
          </li>
        ))}
      </ul>
      {gate.clearance && <div className="mt-1 text-[11.5px] text-hev-green">Medical Clearance applied ({gate.clearance.id.slice(0, 8)}), issued by {gate.clearance.issued_by}.</div>}
      <div className="mt-1 text-[9.5px] leading-snug tracking-[0.04em] text-hev-dim">{gate.disclaimer}</div>
    </div>
  );
}

function ClearanceForm({ d, maxH, issuer, onDone }: { d: SessionDetail; maxH: number; issuer: string; onDone: () => void }) {
  const run = useFitnessAction();
  const [hours, setHours] = useState(4);
  const [by, setBy] = useState(issuer);
  return (
    <div data-testid="fitness-clearance-form" className="border border-hev-amber/50 bg-hev-amber/5 p-2">
      <div className="text-[11px] tracking-[0.08em] text-hev-amber">RECORD MEDICAL CLEARANCE — scoped to <b>{d.crew_id}</b> · <b>{d.exercise_type}</b> only</div>
      <div className="mt-1.5 flex items-center gap-2">
        <input value={by} onChange={(e) => setBy(e.target.value)} aria-label="Issued by"
          className="h-7 min-w-0 flex-1 border border-hev-line bg-black px-2 text-[11.5px] text-hev-white" />
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Validity"
          className="h-7 border border-hev-line bg-black px-1 text-[11.5px] text-hev-white">
          {[2, 4, 8, 24].filter((h) => h <= maxH).map((h) => <option key={h} value={h}>{h} h</option>)}
        </select>
        <button type="button" data-testid="fitness-clearance-submit"
          onClick={() => void run(fitnessApi.grantClearance({ crew_id: d.crew_id, exercise_type: d.exercise_type, issued_by: by, valid_hours: hours, note: `For ${d.id}` }),
            `Medical Clearance recorded for ${d.crew_id} ${d.exercise_type} (${hours} h, SIMULATED record)`).then((ok) => ok && onDone())}
          className="h-7 border border-hev-amber px-2 text-[10.5px] tracking-[0.12em] text-hev-amber hover:bg-hev-amber/10">RECORD</button>
      </div>
      <div className="mt-1 text-[9.5px] text-hev-dim">A clearance never overrides a BLOCKED gate (critical alerts, forbidden phases, plan conflicts, equipment, unmonitored cabin).</div>
    </div>
  );
}

function SessionPanel({ d, refresh, fitness }: { d: SessionDetail | null; refresh: () => void; fitness: FitnessState }) {
  const run = useFitnessAction();
  const [clearanceOpen, setClearanceOpen] = useState(false);
  const [abortReason, setAbortReason] = useState("");
  const maxH = 24;
  if (!d) {
    return (
      <Panel title="Exercise session" testId="fitness-session-detail" bodyClassName="flex items-center justify-center p-4">
        <span className="text-[12px] text-hev-dim">Select a session on the timeline or a crew card.</span>
      </Panel>
    );
  }
  const open = d.status === "PLANNED" || d.status === "NOTIFIED";
  const ready = d.gate?.status === "READY_PER_PLAN";
  const after = () => refresh();
  return (
    <Panel title="Exercise session" testId="fitness-session-detail" bodyClassName="flex min-h-0 flex-col gap-2 overflow-y-auto p-2.5"
      right={<span className="hev-num text-[10.5px] text-hev-dim">{d.id}</span>}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[18px] font-bold tracking-[0.1em] text-hev-white">{d.crew_id} · {d.exercise_label.toUpperCase()}</div>
          <div className="mt-0.5 text-[12px] text-hev-white/80">
            {d.planned_start_met ?? "no window"}{d.planned_end_met ? ` – ${d.planned_end_met.replace("MET ", "")}` : ""} · {d.duration_min} min · {d.device_label ?? "no device"}
          </div>
          <div className="mt-0.5 text-[10.5px] text-hev-dim">MET day {d.day_index} · reschedule attempt {d.attempt} · profile {d.profile_id ?? (d.status === "IN_PROGRESS" ? "--" : "applied at start")}</div>
        </div>
        <StatusChip status={d.status} />
      </div>

      {d.gate && open && <GateBlock gate={d.gate} title="Safety gate · planned window" />}
      {d.gate_at_start && !open && <GateBlock gate={d.gate_at_start} title="Safety gate at start" />}
      {d.status === "UNSCHEDULED" && (
        <div className="border border-hev-amber/50 bg-hev-amber/5 px-3 py-2 text-[12px] text-hev-amber">
          No valid window in the Mission Plan. {d.decisions[0]?.reason}
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {open && (
          <button type="button" data-testid="fitness-start" disabled={!ready}
            onClick={() => void run(fitnessApi.start(d.id), `Session started: ${d.crew_id} ${d.exercise_type} (crew confirmed)`).then(after)}
            className="h-8 border border-hev-green px-3 text-[11px] font-semibold tracking-[0.14em] text-hev-green enabled:hover:bg-hev-green/10 disabled:border-hev-line disabled:text-hev-dim"
            title={ready ? "Crew confirms the start" : "Start requires the Safety Gate to be READY PER PLAN"}>
            CONFIRM START
          </button>
        )}
        {(open || d.status === "UNSCHEDULED") && (
          <button type="button" data-testid="fitness-earliest"
            onClick={() => void run(fitnessApi.earliest(d.id), "Moved to the earliest valid window (crew request)").then(after)}
            className="h-8 border border-hev-cyan/70 px-3 text-[11px] tracking-[0.12em] text-hev-cyan hover:bg-hev-cyan/10">
            REQUEST EARLIEST WINDOW
          </button>
        )}
        {open && d.gate?.status === "CLEARANCE_REQUIRED" && (
          <button type="button" data-testid="fitness-clearance-open" onClick={() => setClearanceOpen((v) => !v)}
            className="h-8 border border-hev-amber/70 px-3 text-[11px] tracking-[0.12em] text-hev-amber hover:bg-hev-amber/10">
            MEDICAL CLEARANCE…
          </button>
        )}
        {d.status === "IN_PROGRESS" && (
          <>
            <button type="button" data-testid="fitness-complete"
              onClick={() => void run(fitnessApi.complete(d.id), `Session completed: ${d.crew_id} ${d.exercise_type}`).then(after)}
              className="h-8 border border-hev-green px-3 text-[11px] font-semibold tracking-[0.14em] text-hev-green hover:bg-hev-green/10">COMPLETE</button>
            <input value={abortReason} onChange={(e) => setAbortReason(e.target.value)} placeholder="Abort reason" aria-label="Abort reason"
              className="h-8 min-w-0 flex-1 border border-hev-line bg-black px-2 text-[11.5px] text-hev-white" />
            <button type="button" data-testid="fitness-abort" disabled={!abortReason.trim()}
              onClick={() => void run(fitnessApi.abort(d.id, abortReason), `Session aborted: ${d.crew_id} ${d.exercise_type}`).then(after)}
              className="h-8 border border-hev-red/70 px-3 text-[11px] tracking-[0.12em] text-hev-red enabled:hover:bg-hev-red/10 disabled:border-hev-line disabled:text-hev-dim">ABORT</button>
          </>
        )}
      </div>
      {clearanceOpen && open && d.gate?.status === "CLEARANCE_REQUIRED" && (
        <ClearanceForm d={d} maxH={maxH} issuer="Flight surgeon (SIMULATED)" onDone={() => { setClearanceOpen(false); after(); }} />
      )}
      {(d.status === "COMPLETED" || d.status === "ABORTED") && (
        <div className="text-[11.5px] text-hev-white/75">
          HR at start {d.pre_hr?.toFixed(0) ?? "--"} · peak {d.peak_hr?.toFixed(0) ?? "--"} · at end {d.end_hr?.toFixed(0) ?? "--"} bpm (SIMULATED){d.end_reason ? ` · ${d.end_reason}` : ""}
          {d.context?.recovery && (
            <div className="mt-0.5">Recovery: <span className={RECOVERY_TONE[d.context.recovery.status]}>{d.context.recovery.status.replace("_", " ")}</span> — {d.context.recovery.summary}</div>
          )}
        </div>
      )}
      {fitness.alert_context && Object.entries(fitness.alert_context).some(([, sid]) => sid === d.id) && (
        <div className="text-[11px] text-hev-amber">Global HEV-1 alert(s) raised during this session are linked to its exercise context — not suppressed.</div>
      )}

      <div className="mt-1">
        <div className="hev-label mb-1 text-[10px]">Planner history · {d.decisions.length}</div>
        <ul className="space-y-1" data-testid="fitness-session-history">
          {d.decisions.map((h) => (
            <li key={h.id ?? h.timestamp} className="border-l-2 border-hev-line pl-2 text-[11px] leading-snug">
              <span className="font-semibold text-hev-cyan">{h.action.replace("_", " ")}</span>
              <span className="text-hev-dim"> · {h.trigger}</span>
              {(h.from_start_met || h.to_start_met) && (
                <span className="text-hev-white/80"> · {h.from_start_met ?? "—"}{h.from_device ? ` ${h.from_device}` : ""} → {h.to_start_met ?? "—"}{h.to_device ? ` ${h.to_device}` : ""}</span>
              )}
              <div className="text-hev-white/65">{h.reason}</div>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

function InSession({ fitness }: { fitness: FitnessState }) {
  const alerts = useHevStore((s) => s.state?.alerts ?? []);
  const list = fitness.in_progress ?? [];
  return (
    <Panel title="In-session monitor" testId="fitness-in-session" bodyClassName="flex min-h-0 flex-col gap-2 overflow-y-auto p-2.5" right={<DemoTag text="DEMONSTRATION PROFILE" />}>
      {list.length === 0 && <div className="text-[12px] text-hev-dim">No exercise session in progress.</div>}
      {list.map((s) => {
        const p = s.profile;
        const hr = p?.heart_rate;
        const lim = p?.limits.heart_rate ?? {};
        const linked = alerts.filter((a) => fitness.alert_context?.[a.id] === s.id);
        const scale = (v: number) => `${Math.max(0, Math.min(100, ((v - 50) / 150) * 100))}%`;
        return (
          <div key={s.id} className="border border-hev-green/50 bg-hev-green/5 p-2">
            <div className="flex items-center gap-2">
              <span className="text-[14px] font-bold tracking-[0.1em] text-hev-white">{s.crew_id} · {s.exercise_label.toUpperCase()}</span>
              <span className="text-[11px] text-hev-dim">{s.device_label} · {p?.profile_id}</span>
              <span className="flex-1" />
              {p && <Chip className={BAND_TONE[p.overall] ?? "border-hev-dim text-hev-dim"}><span data-testid="fitness-profile-band">{p.overall.replace("_", " ")}</span></Chip>}
            </div>
            {p && hr ? (
              <>
                <div className="mt-1.5 flex items-baseline gap-3">
                  <span className="hev-num text-[30px] font-bold text-hev-white">{hr.value?.toFixed(0) ?? "---"}</span>
                  <span className="text-[11px] text-hev-dim">bpm HR · {hr.pct_hrmax ?? "--"} % of HRmax {p.hrmax_bpm ?? "--"}</span>
                  <span className="hev-num text-[18px] text-hev-white/85">{p.spo2?.value?.toFixed(0) ?? "--"}</span>
                  <span className="text-[11px] text-hev-dim">% SpO2</span>
                  <span className="flex-1" />
                  <span className="text-[11.5px] text-hev-white/80">{p.summary}</span>
                </div>
                <div className="relative mt-1.5 h-3 border border-hev-line bg-black" title="DEMONSTRATION heart-rate profile">
                  <div className="absolute inset-y-0 bg-hev-green/30" style={{ left: scale(lim.target_low ?? 0), width: `calc(${scale(lim.target_high ?? 0)} - ${scale(lim.target_low ?? 0)})` }} />
                  <div className="absolute inset-y-0 bg-hev-amber/30" style={{ left: scale(lim.review_above ?? 0), width: `calc(${scale(lim.stop_above ?? 0)} - ${scale(lim.review_above ?? 0)})` }} />
                  <div className="absolute inset-y-0 right-0 bg-hev-red/30" style={{ left: scale(lim.stop_above ?? 0) }} />
                  {hr.value !== null && <div className="absolute -top-1 h-5 w-0.5 bg-hev-white" style={{ left: scale(hr.value) }} />}
                </div>
                <div className="mt-0.5 flex justify-between text-[9.5px] text-hev-dim">
                  <span>target {lim.target_low}–{lim.target_high} bpm ({p.limits.heart_rate_pct_hrmax?.target_low}–{p.limits.heart_rate_pct_hrmax?.target_high} % HRmax{p.reference ? ` · REF ${p.reference}` : ""})</span>
                  <span>review &gt; {lim.review_above}</span><span>stop &gt; {lim.stop_above} bpm</span>
                </div>
                {fitness.alarm_context && fitness.alarm_context.session_id === s.id && (
                  <div data-testid="fitness-alarm-context" className="mt-1 border border-hev-cyan/60 px-2 py-0.5 text-[11px] text-hev-cyan">
                    HR alarm limits in exercise context: caution &gt; {fitness.alarm_context.caution_high}, warning &gt; {fitness.alarm_context.warning_high} bpm (logged). Low-side HR and all other alarms keep global limits.
                  </div>
                )}
              </>
            ) : (
              <div className="mt-1 text-[12px] text-hev-offline">{p?.summary ?? "No profile"}</div>
            )}
            {linked.map((a) => (
              <div key={a.id} className={`mt-1 text-[11.5px] ${SEV_TEXT[a.severity]}`}>
                Global alert {a.title} ({a.severity}) active — limits unchanged, not suppressed.
              </div>
            ))}
            <div className="mt-1 text-[9.5px] text-hev-dim">{p?.note}</div>
          </div>
        );
      })}
    </Panel>
  );
}

function ClearancesAndNotes({ fitness, refresh }: { fitness: FitnessState; refresh: () => void }) {
  const run = useFitnessAction();
  return (
    <Panel title="Medical clearances · CFMS notifications" testId="fitness-clearances" bodyClassName="flex min-h-0 flex-col gap-2 overflow-y-auto p-2.5">
      <div>
        {(fitness.active_clearances ?? []).length === 0 && <div className="text-[11.5px] text-hev-dim">No active Medical Clearance.</div>}
        {(fitness.active_clearances ?? []).map((c) => (
          <div key={c.id} className="flex items-center gap-2 border-b border-hev-line/60 py-1 text-[11.5px]">
            <span className="font-semibold text-hev-amber">{c.crew_id} · {c.exercise_type}</span>
            <span className="text-hev-white/75">until {c.valid_until_met} · {c.issued_by}</span>
            <span className="flex-1" />
            <button type="button" onClick={() => void run(fitnessApi.revokeClearance(c.id, "Revoked by crew"), "Medical Clearance revoked").then(refresh)}
              className="h-6 border border-hev-line px-2 text-[10px] tracking-[0.1em] text-hev-dim hover:text-hev-white">REVOKE</button>
          </div>
        ))}
      </div>
      <ul className="space-y-1" data-testid="fitness-notifications">
        {(fitness.notifications ?? []).map((n) => (
          <li key={n.id} className="text-[11px] leading-snug text-hev-white/75"><span className="text-hev-dim">{n.timestamp.slice(11, 19)}Z </span>{n.message}</li>
        ))}
      </ul>
    </Panel>
  );
}

export function ScheduleTab({ data, fitness, detail, refresh }: { data: FitnessData | null; fitness: FitnessState; detail: SessionDetail | null; refresh: () => void }) {
  const state = useHevStore((s) => s.state);
  const selected = useHevStore((s) => s.selectedSessionId);
  const select = useHevStore((s) => s.selectSession);
  if (!state) return null;
  const crew = state.mission.crew.map((c) => c.id);
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_540px] gap-2">
      <div className="grid min-h-0 min-w-0 grid-rows-[104px_minmax(0,1fr)_250px] gap-2">
        <div className="grid min-h-0 grid-cols-4 gap-2">
          {(fitness.next_by_crew ?? []).map((n) => (
            <NextCard key={n.crew_id} crewId={n.crew_id} monitored={n.monitored} s={n.session} onSelect={select} selected={!!n.session && n.session.id === selected} />
          ))}
        </div>
        <Panel title="Mission plan · next 24 h · crew and devices" bodyClassName="flex min-h-0 flex-col p-1.5"
          right={<span className="text-[10px] tracking-[0.1em] text-hev-dim">SIMULATED PLAN · dashed = buffer / runtime addition · dot = safety gate</span>}>
          {data ? (
            <PlanTimeline plan={data.plan} sessions={data.schedule} crew={crew} devices={fitness.equipment ?? []} nowIso={state.server_time}
              metStartIso={state.mission.met_start_utc} selectedId={selected} onSelect={select} />
          ) : <div className="p-3 text-[12px] text-hev-dim">Loading plan…</div>}
        </Panel>
        <div className="grid min-h-0 grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-2">
          <InSession fitness={fitness} />
          <ClearancesAndNotes fitness={fitness} refresh={refresh} />
        </div>
      </div>
      <SessionPanel d={detail} refresh={refresh} fitness={fitness} />
    </div>
  );
}
