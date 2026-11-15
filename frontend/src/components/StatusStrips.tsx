// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useEffect } from "react";
import { fmtUtc, severityLabel } from "../services/format";
import { useHevStore } from "../store/useHevStore";

export function OfflineBanner() {
  const connection = useHevStore((s) => s.connection);
  const cachedAt = useHevStore((s) => s.cachedSnapshotAt);
  const state = useHevStore((s) => s.state);
  const outbox = useHevStore((s) => s.outboxPending);
  if (connection === "ONLINE" && outbox === 0) return null;
  if (connection === "CONNECTING" && !state) {
    return <div className="border-b border-[#333333] bg-[#141414] px-4 py-1 hmi-mono text-[11px] tracking-[0.12em] text-[#aaaaaa]">CONNECTING TO HEV-1 CORE...</div>;
  }
  return (
    <div data-testid="offline-banner" className="flex gap-4 border-b border-[#ffb000] bg-[#261a00] px-4 py-1 hmi-mono text-[11px] font-bold tracking-[0.1em] text-[#ffb000]">
      {connection === "OFFLINE" && (
        <span>
          HEV-1 CORE LINK LOST - {state ? `DISPLAYING CACHED TELEMETRY FROM ${fmtUtc(cachedAt)}. VALUES ARE NOT CURRENT.` : "NO CACHED TELEMETRY AVAILABLE."} ALERT ACTIONS UNAVAILABLE.
        </span>
      )}
      {outbox > 0 && <span>{outbox} CREW INPUT(S) QUEUED LOCALLY</span>}
    </div>
  );
}

export function NoticeStrip() {
  const notice = useHevStore((s) => s.notice);
  const setNotice = useHevStore((s) => s.setNotice);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice, setNotice]);
  if (!notice) return null;
  return (
    <div role="status" data-testid="notice" className="fixed bottom-7 left-1/2 z-40 -translate-x-1/2 border-2 border-[#00ff00] bg-black px-4 py-1.5 hmi-mono text-[12px] font-bold tracking-[0.08em] text-[#00ff00]">
      {notice}
    </div>
  );
}

export function FooterStrip() {
  const version = useHevStore((s) => s.state?.version);
  return (
    <footer className="flex h-5 shrink-0 items-center justify-between border-t border-[#333333] bg-black px-4 hmi-mono text-[10px] tracking-[0.12em] text-[#777777]">
      <span>PROTOTYPE - NOT A CERTIFIED MEDICAL DEVICE · ALL LIMITS ARE DEMONSTRATION VALUES · SIMULATED DATA IS LABELED SIM</span>
      <span>NASA DONKI · NASA OSDR · NASA-STD-3001 (REFERENCE) · R.I.D.G.E. // HEV-1 v{version ?? "1.0.7"}</span>
    </footer>
  );
}

const EVA_BANNER: Record<string, [string, string]> = {
  NO_BLOCKERS: ["EVA: NO BLOCKERS", "text-[#00ff00]"],
  REVIEW: ["EVA: REVIEW", "bg-[#ffb000] px-2 text-black"],
  DATA_INCOMPLETE: ["EVA: DATA INCOMPLETE", "bg-[#ffb000] px-2 text-black"],
  HOLD_RECOMMENDED: ["EVA: NO-GO (HOLD)", "bg-[#ff0000] px-2 text-black"],
};

/** Narrow mission banner: overall status left, EVA decision-support result right (never "GO"). */
export function MissionBanner() {
  const state = useHevStore((s) => s.state);
  const selectedZone = useHevStore((s) => s.selectedZone);
  const viewCrew = useHevStore((s) => s.viewCrewId);
  if (!state) return null;
  const sev = state.medical_status;
  const top = state.alerts[0];
  const m = state.master;
  const flashing = (sev === "WARNING" && m.warning_unacked) || (sev === "CAUTION" && m.caution_unacked);
  const left = sev === "NOMINAL" ? "MISSION STATUS: NOMINAL"
    : sev === "ADVISORY" ? `MISSION STATUS: ADVISORY · ${top?.title ?? ""}`
    : `MISSION STATUS: ACTION REQUIRED · ${severityLabel(sev)} · ${top?.title ?? ""}`;
  const tone = sev === "NOMINAL" ? "text-[#00ff00]" : sev === "ADVISORY" ? "text-[#00c8ff]"
    : sev === "CAUTION" ? "bg-[#ffb000] px-3 text-black" : "bg-[#ff0000] px-3 text-black";
  const eva = state.readiness ? EVA_BANNER[state.readiness.eva.status] : null;
  const activeCrewId = viewCrew ?? state.mission.monitored_crew_id ?? "CM-1";
  const activeCrewObj = state.mission.crew.find((c) => c.id === activeCrewId) ?? state.mission.crew[0];
  return (
    <div data-testid="mission-banner" className="grid h-8 shrink-0 grid-cols-[auto_1fr_auto] items-stretch border-b border-[#333333] bg-black hmi-mono text-[12px] font-black tracking-[0.1em]">
      <div className="flex items-stretch border-r border-[#333333]">
        <span data-testid="banner-mission-status" className={`flex items-center px-4 ${tone} ${flashing ? (sev === "WARNING" ? "blink-banner-red" : "blink-banner-amber") : ""}`}>
          {left}
        </span>
      </div>
      <div className="flex items-center justify-between border-r border-[#333333] px-4 text-[11px] font-normal">
        <div className="flex items-center gap-3">
          <span>
            <span className="text-[#777777]">CREW: </span>
            <span className="font-bold text-white">{activeCrewObj ? `${activeCrewObj.name.toUpperCase()} [${activeCrewObj.id}]` : "CMDR. SMITH [CM-1]"}</span>
          </span>
          <span className="text-[#333333]">|</span>
          <span>
            <span className="text-[#777777]">ZONE FOCUS: </span>
            <span className="font-bold text-[#00ff00] uppercase">{selectedZone ?? "ALL SUBSYSTEMS"}</span>
          </span>
          {state.readiness?.triage && (
            <>
              <span className="text-[#333333]">|</span>
              <span>
                <span className="text-[#777777]">R.I.D.G.E.: </span>
                <span className={state.readiness.triage.severity === "NOMINAL" ? "font-bold text-[#00ff00]" : "font-bold text-[#ffb000]"}>
                  {state.readiness.triage.title.toUpperCase()}
                </span>
              </span>
            </>
          )}
        </div>
        <span className="text-[10px] tracking-[0.1em] text-[#777777]">DECISION SUPPORT · GO / NO-GO BELONGS TO CREW, FLIGHT SURGEON & MCC</span>
      </div>
      <div className="flex items-stretch">
        {eva && (
          <span data-testid="banner-eva" className={`flex items-center px-4 font-black tracking-[0.1em] ${eva[1]}`}>
            {eva[0]}
          </span>
        )}
      </div>
    </div>
  );
}
