// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useEffect } from "react";
import { ActionCentricHud } from "./components/ActionCentricHud";
import { FooterStrip, MissionBanner, NoticeStrip, OfflineBanner } from "./components/StatusStrips";
import { TopBar } from "./components/TopBar";
import { useHevPolling } from "./hooks/useHevPolling";
import { AlertPanel } from "./modules/alerts/AlertPanel";
import { CountermeasureGuide } from "./modules/alerts/CountermeasureGuide";
import { MissionTimeline } from "./modules/alerts/MissionTimeline";
import { EnvironmentPanel } from "./modules/biometrics/EnvironmentPanel";
import { VitalsPanel } from "./modules/biometrics/VitalsPanel";
import { TwinPanel } from "./modules/digital-twin/TwinPanel";
import { FitnessScreen } from "./modules/fitness/FitnessScreen";
import { PsychModal } from "./modules/mental-health/PsychModal";
import { PvtModal } from "./modules/mental-health/PvtModal";
import { RadiationPanel } from "./modules/radiation/RadiationPanel";
import { SimulatorPanel } from "./modules/simulator/SimulatorPanel";
import { audio } from "./services/audio";
import { useHevStore } from "./store/useHevStore";

export default function App() {
  useHevPolling();
  const modal = useHevStore((s) => s.modal);
  const connection = useHevStore((s) => s.connection);
  const setAudioArmed = useHevStore((s) => s.setAudioArmed);
  const screen = useHevStore((s) => s.screen);
  const setScreen = useHevStore((s) => s.setScreen);

  // Screen switching: keys 1 / 2 / 3 (ignored while typing or during a modal test).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (useHevStore.getState().modal || (el && /INPUT|TEXTAREA|SELECT/.test(el.tagName))) return;
      if (e.key === "1") setScreen("command");
      if (e.key === "2") setScreen("engineering");
      if (e.key === "3" && useHevStore.getState().state?.fitness?.enabled) setScreen("fitness");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setScreen]);

  // Browsers only allow audio after a user gesture: arm on the first interaction.
  useEffect(() => {
    const armOnce = () => {
      audio.arm();
      setAudioArmed(true);
    };
    window.addEventListener("pointerdown", armOnce, { once: true });
    window.addEventListener("keydown", armOnce, { once: true });
    return () => {
      window.removeEventListener("pointerdown", armOnce);
      window.removeEventListener("keydown", armOnce);
    };
  }, [setAudioArmed]);

  return (
    <div className="flex h-screen w-screen flex-col bg-black text-[#e6e6e6] overflow-hidden select-none">
      <TopBar />
      <MissionBanner />
      <OfflineBanner />
      {screen === "command" ? (
        <div className={`flex min-h-0 flex-1 flex-col ${connection === "OFFLINE" ? "opacity-70 saturate-50" : ""}`}>
          <ActionCentricHud />
        </div>
      ) : screen === "fitness" ? (
        <div className={`flex min-h-0 flex-1 flex-col ${connection === "OFFLINE" ? "opacity-70 saturate-50" : ""}`}>
          <FitnessScreen />
        </div>
      ) : (
        <main
          data-testid="screen-engineering-view"
          className={`grid min-h-0 flex-1 grid-cols-[390px_minmax(0,1fr)_540px] grid-rows-[minmax(0,1fr)_292px] gap-2 p-2 ${
            connection === "OFFLINE" ? "opacity-70 saturate-50" : ""
          }`}
        >
          <VitalsPanel />
          <TwinPanel />
          <div className="grid min-h-0 min-w-0 grid-rows-[minmax(0,0.9fr)_minmax(0,1.25fr)] gap-2">
            <AlertPanel />
            <CountermeasureGuide />
          </div>
          <div className="col-span-3 grid min-h-0 grid-cols-[minmax(0,1fr)_540px_400px_330px] gap-2">
            <MissionTimeline />
            <RadiationPanel />
            <EnvironmentPanel />
            <SimulatorPanel />
          </div>
        </main>
      )}
      <FooterStrip />
      <NoticeStrip />
      {modal === "pvt" && <PvtModal />}
      {modal === "psych" && <PsychModal />}
    </div>
  );
}
