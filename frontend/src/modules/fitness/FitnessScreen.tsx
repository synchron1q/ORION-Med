// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Chip, Panel } from "../../components/Panel";
import { type FitnessTab, useHevStore } from "../../store/useHevStore";
import { DemoTag, useFitnessData, useSessionDetail } from "./common";
import { EquipmentTab } from "./EquipmentTab";
import { PlannerTab } from "./PlannerTab";
import { RecoveryTab } from "./RecoveryTab";
import { ScheduleTab } from "./ScheduleTab";

const TABS: { id: FitnessTab; label: string }[] = [
  { id: "schedule", label: "CREW SCHEDULE" },
  { id: "planner", label: "MISSION PLANNER" },
  { id: "equipment", label: "EQUIPMENT STATUS" },
  { id: "recovery", label: "RECOVERY MONITOR" },
];

export function FitnessScreen() {
  const fitness = useHevStore((s) => s.state?.fitness);
  const tab = useHevStore((s) => s.fitnessTab);
  const setTab = useHevStore((s) => s.setFitnessTab);
  const selected = useHevStore((s) => s.selectedSessionId);
  const { data, error, refresh, tick } = useFitnessData();
  const detail = useSessionDetail(selected, tick);

  if (!fitness?.enabled) {
    return (
      <div data-testid="screen-fitness-view" className="flex flex-1 items-center justify-center p-4">
        <Panel title="Crew fitness management" bodyClassName="p-4 text-[13px] text-hev-white/80">
          CFMS is disabled. Set ORION_CFMS_ENABLED=true in .env and restart HEV-1.
        </Panel>
      </div>
    );
  }
  const counts = fitness.counts ?? {};
  return (
    <div data-testid="screen-fitness-view" className="flex min-h-0 flex-1 flex-col gap-2 p-2">
      <div className="flex h-9 shrink-0 items-center gap-2 border border-hev-line bg-hev-panel px-2">
        <span className="pr-2 text-[12px] font-bold tracking-[0.16em] text-hev-white">CFMS</span>
        <div className="flex gap-1" role="tablist" aria-label="Fitness views">
          {TABS.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} data-testid={`fitness-tab-${t.id}`} onClick={() => setTab(t.id)}
              className={`h-7 border px-3 text-[11px] tracking-[0.12em] ${tab === t.id ? "border-hev-cyan bg-hev-cyan/15 text-hev-cyan" : "border-hev-line text-hev-dim hover:text-hev-white"}`}>
              {t.label}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        {error && <span className="text-[11px] text-hev-offline">Planner data unavailable: {error}</span>}
        <span className="text-[11px] text-hev-white/75">{fitness.plan?.now_met} · {fitness.plan?.phase_now?.title ?? "--"}</span>
        <Chip className="border-hev-line text-hev-white/80">{counts.PLANNED ?? 0} planned · {counts.NOTIFIED ?? 0} notified · {counts.IN_PROGRESS ?? 0} active · {counts.UNSCHEDULED ?? 0} no window</Chip>
        <DemoTag text="DEMONSTRATION / SIMULATED" />
      </div>
      {tab === "schedule" && <ScheduleTab data={data} fitness={fitness} detail={detail} refresh={refresh} />}
      {tab === "planner" && <PlannerTab data={data} fitness={fitness} refresh={refresh} />}
      {tab === "equipment" && <EquipmentTab data={data} fitness={fitness} refresh={refresh} />}
      {tab === "recovery" && <RecoveryTab />}
    </div>
  );
}
