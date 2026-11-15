// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Panel } from "../../components/Panel";
import { fmtUtc, SEV_TEXT } from "../../services/format";
import { useHevStore } from "../../store/useHevStore";

const CAT_COLOR: Record<string, string> = {
  SIMULATOR: "text-hev-amber/80",
  COMM: "text-hev-offline",
  CREW: "text-hev-white/80",
  SYSTEM: "text-hev-dim",
};

export function MissionTimeline() {
  const state = useHevStore((s) => s.state);
  const selectAlert = useHevStore((s) => s.selectAlert);
  const items = state?.timeline ?? [];
  return (
    <Panel title="Mission event log" testId="timeline"
      right={<span className="hev-label text-[10px]">Persistent · UTC</span>} bodyClassName="hev-scroll px-2 py-1">
      <ul className="m-0 list-none p-0">
        {items.map((e) => (
          <li key={e.id} className="flex gap-2 border-b border-hev-line/40 py-[3px] text-[11.5px]"
            onClick={() => e.alert_id && selectAlert(e.alert_id)}>
            <span className="hev-num w-[70px] shrink-0 text-hev-dim">{fmtUtc(e.timestamp)}</span>
            <span className={`w-[64px] shrink-0 text-[10px] tracking-[0.1em] ${e.severity ? SEV_TEXT[e.severity] : CAT_COLOR[e.category] ?? "text-hev-dim"}`}>
              {e.category === "ALERT" ? e.severity : e.category}
            </span>
            <span className={`min-w-0 flex-1 truncate ${e.event_type === "CLEARED" ? "text-hev-green" : "text-hev-white/85"}`} title={e.message}>
              {e.message}
            </span>
            {e.source === "SIMULATED" && <span className="text-[9px] text-hev-amber/70">SIM</span>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
