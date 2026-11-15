// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useCallback, useEffect, useState } from "react";
import { Chip } from "../../components/Panel";
import { ApiError, fitnessApi } from "../../services/api";
import { useHevStore } from "../../store/useHevStore";
import type { ExerciseSession, Gate, GateStatus, PlannerDecision, PlanView, SessionDetail, SessionStatus } from "../../types/fitness";

export const GATE_TEXT: Record<GateStatus, string> = {
  BLOCKED: "BLOCKED", CLEARANCE_REQUIRED: "CLEARANCE REQUIRED", READY_PER_PLAN: "READY PER PLAN",
};
export const GATE_TONE: Record<GateStatus, string> = {
  BLOCKED: "border-hev-red/70 text-hev-red", CLEARANCE_REQUIRED: "border-hev-amber/70 text-hev-amber", READY_PER_PLAN: "border-hev-green/70 text-hev-green",
};
export const GATE_DOT: Record<GateStatus, string> = { BLOCKED: "bg-hev-red", CLEARANCE_REQUIRED: "bg-hev-amber", READY_PER_PLAN: "bg-hev-green" };

export const STATUS_TONE: Record<SessionStatus, string> = {
  PLANNED: "border-hev-cyan/60 text-hev-cyan", NOTIFIED: "border-hev-cyan text-hev-cyan", IN_PROGRESS: "border-hev-green text-hev-green",
  COMPLETED: "border-hev-green/50 text-hev-green/80", ABORTED: "border-hev-red/60 text-hev-red", MISSED: "border-hev-red/60 text-hev-red",
  UNSCHEDULED: "border-hev-amber/70 text-hev-amber", CANCELLED: "border-hev-dim text-hev-dim",
};

export function GateBadge({ gate, testId }: { gate: Gate | null | undefined; testId?: string }) {
  if (!gate) return null;
  return <Chip className={GATE_TONE[gate.status]}><span data-testid={testId}>{GATE_TEXT[gate.status]}</span></Chip>;
}

export function StatusChip({ status }: { status: SessionStatus }) {
  return <Chip className={STATUS_TONE[status]}>{status.replace("_", " ")}</Chip>;
}

export function DemoTag({ text = "DEMONSTRATION" }: { text?: string }) {
  return <Chip className="border-hev-amber/60 text-hev-amber/90">{text}</Chip>;
}

/** Runs a CFMS command and reports the result in the notice strip. */
export function useFitnessAction() {
  const setNotice = useHevStore((s) => s.setNotice);
  return useCallback(async (p: Promise<unknown>, ok: string): Promise<boolean> => {
    try {
      await p;
      setNotice(ok);
      return true;
    } catch (e) {
      setNotice(e instanceof ApiError ? `Refused: ${e.message}` : (e as Error).message || "Command failed");
      return false;
    }
  }, [setNotice]);
}

export interface FitnessData { schedule: ExerciseSession[]; plan: PlanView; decisions: PlannerDecision[] }

/** Schedule, plan and decision history: refreshed every 5 s, on new planner decisions and on demand. */
export function useFitnessData() {
  const lastDecision = useHevStore((s) => s.state?.fitness?.last_decision_id ?? 0);
  const progressKey = useHevStore((s) => (s.state?.fitness?.in_progress ?? []).map((x) => `${x.id}:${x.status}`).join(","));
  const [data, setData] = useState<FitnessData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    let alive = true;
    Promise.all([fitnessApi.schedule(), fitnessApi.plan(), fitnessApi.decisions(200)])
      .then(([schedule, plan, decisions]) => {
        if (!alive) return;
        setData({ schedule, plan, decisions });
        setError(null);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [lastDecision, progressKey, tick]);
  useEffect(() => {
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);
  return { data, error, refresh, tick };
}

export function useSessionDetail(id: string | null, tick: number) {
  const lastDecision = useHevStore((s) => s.state?.fitness?.last_decision_id ?? 0);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  useEffect(() => {
    let alive = true;
    if (!id) {
      setDetail(null);
      return;
    }
    fitnessApi.session(id).then((d) => alive && setDetail(d)).catch(() => alive && setDetail(null));
    return () => {
      alive = false;
    };
  }, [id, tick, lastDecision]);
  return detail;
}

export const metHours = (iso: string, metStartIso: string) => (new Date(iso).getTime() - new Date(metStartIso).getTime()) / 3_600_000;

export function fmtMetH(h: number): string {
  const total = Math.round(h * 60);
  return `MET ${String(Math.floor(total / 60)).padStart(3, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export const sessionLabel = (s: { crew_id: string; exercise_type: string }) => `${s.crew_id} · ${s.exercise_type}`;
