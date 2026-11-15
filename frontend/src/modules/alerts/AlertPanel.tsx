// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Chip, Panel } from "../../components/Panel";
import { ageFrom, fmtAge, SEV_BORDER, SEV_TEXT, severityLabel } from "../../services/format";
import { useNow } from "../../hooks/useNow";
import { useHevStore } from "../../store/useHevStore";
import type { Alert } from "../../types/state";
import { alertActions } from "./actions";

const STATE_CHIPS: Record<string, string> = {
  ACKNOWLEDGED: "ACK",
  SILENCED: "SILENCED",
  COUNTERMEASURE_IN_PROGRESS: "CM IN PROGRESS",
  COUNTERMEASURE_COMPLETED: "CM DONE",
  RECOVERY: "RECOVERY",
  RESOLUTION_VERIFIED: "VERIFIED",
  SENSOR_FAULT: "SENSOR FAULT",
  DATA_STALE: "DATA STALE",
};

function AlertCard({ a, selected, now }: { a: Alert; selected: boolean; now: number }) {
  const selectAlert = useHevStore((s) => s.selectAlert);
  const selectZone = useHevStore((s) => s.selectZone);
  const flashing = a.severity === "WARNING" && !a.acknowledged && a.lifecycle === "ACTIVE";
  return (
    <article
      data-testid={`alert-${a.rule_id}`}
      data-alert-id={a.id}
      onClick={() => {
        selectAlert(a.id);
        selectZone(a.zone);
      }}
      className={`cursor-pointer border border-l-4 bg-black/40 px-2.5 py-2 ${SEV_BORDER[a.severity]} ${selected ? "outline outline-1 outline-hev-white/70" : ""} ${a.lifecycle === "RECOVERY" ? "opacity-80" : ""}`}
    >
      <div className="flex items-center gap-2">
        <span className={`text-[11px] font-bold tracking-[0.16em] ${SEV_TEXT[a.severity]} ${flashing ? "hev-flash" : ""}`}>
          {a.kind === "CORRELATION" ? "R.I.D.G.E. ADVISORY" : severityLabel(a.severity)}
        </span>
        {a.simulated && <Chip className="border-hev-amber/60 text-hev-amber/90">SIM</Chip>}
        {a.occurrence_count > 1 && <Chip className="border-hev-dim text-hev-dim">x{a.occurrence_count}</Chip>}
        <span className="flex-1" />
        <span className="hev-num text-[11px] text-hev-dim">T+{fmtAge(ageFrom(a.created_at, now))}</span>
      </div>
      <div className="mt-0.5 text-[14px] font-semibold tracking-[0.06em] text-hev-white">{a.title}</div>
      <p className="m-0 mt-0.5 line-clamp-2 text-[12px] leading-snug text-hev-white/75">{a.message}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        {a.states.filter((s) => STATE_CHIPS[s]).map((s) => (
          <Chip key={s} className="border-hev-cyan/50 text-hev-cyan/90">{STATE_CHIPS[s]}</Chip>
        ))}
        <span className="flex-1" />
        <button type="button" data-testid="ack-btn" disabled={a.acknowledged}
          onClick={(e) => { e.stopPropagation(); void alertActions.ack(a.id); }}
          className="h-7 w-16 border border-hev-white/70 text-[11px] tracking-[0.14em] text-hev-white enabled:hover:bg-hev-white/10 disabled:border-hev-line disabled:text-hev-dim">
          ACK
        </button>
        <button type="button" data-testid="silence-btn" disabled={a.silenced}
          onClick={(e) => { e.stopPropagation(); void alertActions.silence(a.id); }}
          className="h-7 w-20 border border-hev-cyan/70 text-[11px] tracking-[0.14em] text-hev-cyan enabled:hover:bg-hev-cyan/10 disabled:border-hev-line disabled:text-hev-dim">
          SILENCE
        </button>
      </div>
    </article>
  );
}

export function AlertPanel() {
  const now = useNow(1000);
  const state = useHevStore((s) => s.state);
  const selectedId = useHevStore((s) => s.selectedAlertId);
  const alerts = state?.alerts ?? [];
  const sel = selectedId ?? alerts[0]?.id ?? null;
  return (
    <Panel title="Master caution & warning" testId="alert-panel"
      right={<span className="hev-label text-[10px]">{alerts.length} active</span>} bodyClassName="hev-scroll flex flex-col gap-1.5 p-2">
      {alerts.length === 0 && (
        <div className="flex h-full flex-col items-center justify-center text-center">
          <div className="text-[15px] tracking-[0.2em] text-hev-green">NO ACTIVE ALERTS</div>
          <div className="mt-1 text-[12px] text-hev-dim">Rules engine evaluating all instrumented parameters</div>
        </div>
      )}
      {alerts.map((a) => (
        <AlertCard key={a.id} a={a} selected={a.id === sel} now={now} />
      ))}
    </Panel>
  );
}
