// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { Panel } from "../../components/Panel";
import { api } from "../../services/api";
import { audio } from "../../services/audio";
import { useHevStore } from "../../store/useHevStore";

export function SimulatorPanel() {
  const state = useHevStore((s) => s.state);
  const setNotice = useHevStore((s) => s.setNotice);
  const setAudioArmed = useHevStore((s) => s.setAudioArmed);
  if (!state) return <Panel title="Mission simulator"><div /></Panel>;
  const { mode, sync } = state;
  const run = (p: Promise<unknown>, msg: string) =>
    p.then(() => setNotice(msg)).catch((e: Error) => setNotice(e.message || "Simulator command failed"));
  const arm = () => {
    audio.arm();
    setAudioArmed(true);
  };
  return (
    <Panel title="Mission simulator" testId="simulator-panel"
      right={<span className="text-[10px] tracking-[0.16em] text-hev-amber">{mode.demo_mode ? "DEMONSTRATION MODE" : "FLIGHT MODE"}</span>}
      bodyClassName="flex flex-col gap-1.5 p-2">
      {!mode.demo_mode ? (
        <div className="text-[12px] text-hev-dim">Simulator disabled (ORION_DEMO_MODE=false). Waiting for real sensor telemetry.</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-1.5">
            {mode.scenarios.map((s) => (
              <button key={s.id} type="button" data-testid={`scenario-${s.id}`} title={s.description}
                disabled={!mode.simulator_enabled}
                onClick={() => {
                  arm();
                  void run(api.scenario(s.id), `Scenario ${s.label} activated (simulated data)`);
                }}
                className={`h-8 border text-[11px] tracking-[0.14em] disabled:opacity-40 ${s.active ? "border-hev-amber bg-hev-amber/15 text-hev-amber" : "border-hev-line text-hev-white/85 hover:border-hev-amber/60"} ${s.id === "nominal" ? "col-span-2" : ""}`}>
                {s.label}
              </button>
            ))}
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            <button type="button" data-testid="link-toggle"
              onClick={() => { arm(); void run(api.link(!sync.link_up), sync.link_up ? "Earth link lost (simulated)" : "Earth link restored"); }}
              className={`h-7 flex-1 border text-[10.5px] tracking-[0.12em] ${sync.link_up ? "border-hev-line text-hev-white/80" : "border-hev-offline text-hev-offline"}`}>
              {sync.link_up ? "SIMULATE LOSS OF SIGNAL" : "RESTORE EARTH LINK"}
            </button>
            <button type="button" data-testid="sim-toggle"
              onClick={() => void run(api.simulatorEnabled(!mode.simulator_enabled), mode.simulator_enabled ? "Simulator stopped - sensors go stale" : "Simulator running")}
              className="h-7 w-[86px] border border-hev-line text-[10.5px] tracking-[0.12em] text-hev-white/80">
              {mode.simulator_enabled ? "SIM STOP" : "SIM START"}
            </button>
          </div>
          <div className="text-[10.5px] leading-snug text-hev-dim">
            Downlink queue: <span className="text-hev-white/85">{sync.pending}</span> pending · {sync.sent} sent ·
            target {sync.target.replace(/_/g, " ")}
          </div>
          <div className="mt-auto text-[10px] leading-snug text-hev-amber/80">
            Scenarios inject SIMULATED sensor values through the normal ingest and rules engine. No separate alert path.
          </div>
        </>
      )}
    </Panel>
  );
}
