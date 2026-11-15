// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useEffect, useState } from "react";
import { Chip, Panel } from "../../components/Panel";
import { ageFrom, SEV_TEXT, severityLabel } from "../../services/format";
import { useNow } from "../../hooks/useNow";
import { useHevStore } from "../../store/useHevStore";
import type { Alert } from "../../types/state";
import { alertActions } from "./actions";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-[12px]">
      <span className="hev-label w-[86px] shrink-0 whitespace-nowrap pt-px text-[10px]">{label}</span>
      <span className="min-w-0 text-hev-white/90">{children}</span>
    </div>
  );
}

function ClearControl({ a, now }: { a: Alert; now: number }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  let status: string;
  if (a.lifecycle === "ACTIVE") status = "CONDITION ACTIVE - CLEAR LOCKED";
  else if (!a.resolution_verified) {
    const held = Math.min(a.recovery_hold_s, ageFrom(a.recovery_since, now) ?? 0);
    status = `RECOVERY - VERIFYING ${held.toFixed(0)}/${a.recovery_hold_s.toFixed(0)} s OF FRESH NOMINAL DATA`;
  } else status = "RESOLUTION VERIFIED - CLEAR AVAILABLE";
  return (
    <div className="flex items-center gap-2 border-t border-hev-line pt-2">
      <span data-testid="resolution-status" className={`flex-1 text-[11px] tracking-[0.1em] ${a.can_clear ? "text-hev-green" : a.lifecycle === "RECOVERY" ? "text-hev-cyan" : "text-hev-amber"}`}>
        {status}
      </span>
      <button
        type="button"
        data-testid="clear-btn"
        disabled={!a.can_clear}
        onClick={() => {
          if (!armed) setArmed(true);
          else {
            setArmed(false);
            void alertActions.clear(a.id);
          }
        }}
        className={`h-8 w-[150px] border text-[11px] tracking-[0.14em] disabled:border-hev-line disabled:text-hev-dim ${armed ? "border-hev-amber bg-hev-amber/20 text-hev-amber" : "border-hev-green text-hev-green enabled:hover:bg-hev-green/10"}`}
      >
        {armed ? "PRESS AGAIN TO CLEAR" : "CLEAR"}
      </button>
    </div>
  );
}

export function CountermeasureGuide() {
  const now = useNow(1000);
  const state = useHevStore((s) => s.state);
  const protocols = useHevStore((s) => s.protocols);
  const selectedId = useHevStore((s) => s.selectedAlertId);
  const alerts = state?.alerts ?? [];
  const a = alerts.find((x) => x.id === selectedId) ?? alerts[0];
  const proto = a?.protocol_id ? protocols[a.protocol_id] : undefined;
  const done = new Set(a?.cm_steps_done ?? []);
  const total = proto?.steps.length ?? 0;
  const pct = total ? Math.round((done.size / total) * 100) : 0;

  return (
    <Panel title="Countermeasure guide" testId="cm-guide"
      right={a ? <span className={`text-[10px] tracking-[0.14em] ${SEV_TEXT[a.severity]}`}>{a.rule_id}</span> : null}
      bodyClassName="hev-scroll flex flex-col gap-1.5 p-2.5">
      {!a && <div className="m-auto text-[12px] text-hev-dim">No active alert. Guides open automatically when an alert is raised.</div>}
      {a && (
        <>
          <div className={`text-[16px] font-bold tracking-[0.08em] ${SEV_TEXT[a.severity]}`} data-testid="cm-title">{proto?.title ?? a.title}</div>
          <p className="m-0 text-[12.5px] leading-snug text-hev-white/90">{proto?.description ?? a.message}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            <Row label="Subsystem">{proto?.subsystem ?? a.zone.toUpperCase()}</Row>
            <Row label="Severity"><span className={SEV_TEXT[a.severity]}>{severityLabel(a.severity)}</span></Row>
            <Row label="Source">{a.data_source}</Row>
            <Row label="Duration">{proto?.duration_min ? `~${proto.duration_min} min (configured)` : "--"}</Row>
            <Row label="ACK status"><span className={a.acknowledged ? "text-hev-green" : "text-hev-amber"}>{a.acknowledged ? "YES" : "NO - ACK REQUIRED"}</span></Row>
            <Row label="Completion"><span data-testid="cm-status">{a.cm_status.replace("_", " ")}</span></Row>
          </div>
          {proto && proto.kit !== "NONE" && (
            <div className="flex items-center gap-3 border border-hev-amber/60 bg-hev-amber/5 px-2.5 py-1.5" data-testid="cm-kit">
              <span className="hev-label whitespace-nowrap text-[10px] text-hev-amber/80">Required kit</span>
              <span className="whitespace-nowrap text-[17px] font-bold tracking-[0.14em] text-hev-amber">{proto.kit}</span>
              <span className="min-w-0 truncate text-[11px] text-hev-white/70">{proto.kit_contents.join(" · ")}</span>
            </div>
          )}
          {proto ? (
            <>
              <div className="flex items-center gap-2">
                <span className="hev-label text-[10px]">Protocol progress</span>
                <div className="h-1.5 flex-1 bg-hev-line">
                  <div className="h-full bg-hev-cyan transition-all" style={{ width: `${pct}%` }} data-testid="cm-progress" />
                </div>
                <span className="hev-num text-[12px] text-hev-cyan">{done.size}/{total}</span>
              </div>
              <ol className="m-0 flex list-none flex-col gap-1 p-0">
                {proto.steps.map((step, i) => (
                  <li key={i} className={`flex items-center gap-2 border px-2 py-1 ${done.has(i) ? "border-hev-green/40 text-hev-white/60" : "border-hev-line text-hev-white"}`}>
                    <span className="hev-num w-5 text-[12px] text-hev-dim">{i + 1}</span>
                    <span className="flex-1 text-[12.5px] leading-snug">{step}</span>
                    <button type="button" data-testid={`step-${i}`} disabled={done.has(i)}
                      onClick={() => void alertActions.confirmStep(a.id, i)}
                      className="h-6 w-[78px] shrink-0 border border-hev-cyan/70 text-[10px] tracking-[0.14em] text-hev-cyan enabled:hover:bg-hev-cyan/10 disabled:border-hev-green/50 disabled:text-hev-green">
                      {done.has(i) ? "DONE" : "CONFIRM"}
                    </button>
                  </li>
                ))}
              </ol>
              <Row label="Resolution">{proto.resolution}</Row>
              <div className="text-[10px] tracking-[0.1em] text-hev-dim">{proto.provenance}. Confirming steps records crew actions; it does not prove the condition is resolved.</div>
            </>
          ) : (
            <div className="border border-hev-line p-2 text-[12px] text-hev-white/85">
              {a.kind === "CORRELATION" ? (
                <>
                  <div className="hev-label mb-1 text-[10px]">Contributing observations</div>
                  {(a.factors ?? []).map((f, i) => (
                    <div key={i} className="hev-num text-[11.5px]">
                      {f.factor === "space_weather_event" ? "SPACE-WEATHER EVENT" : f.factor.toUpperCase()} {f.value !== undefined ? f.value : ""} {f.severity ?? ""} @ {f.timestamp.slice(11, 19)}Z
                    </div>
                  ))}
                  <Chip className="mt-1 border-hev-cyan/50 text-hev-cyan">CORRELATION ≠ CAUSATION</Chip>
                </>
              ) : (
                "No countermeasure protocol is configured for this alert."
              )}
            </div>
          )}
          <ClearControl a={a} now={now} />
        </>
      )}
    </Panel>
  );
}
