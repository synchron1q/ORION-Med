// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { api } from "../services/api";
import { audio } from "../services/audio";
import { fmtMET, SEV_TEXT } from "../services/format";
import { useNow } from "../hooks/useNow";
import { useHevStore } from "../store/useHevStore";

function Annunciator({ label, lit, flashing, color, onClick, testId }: {
  label: string; lit: boolean; flashing: boolean; color: "red" | "amber"; onClick: () => void; testId: string;
}) {
  const on = color === "red" ? "bg-[#ff0000] text-black border-[#ff0000]" : "bg-[#ffb000] text-black border-[#ffb000]";
  const off = color === "red" ? "border-[#440000] bg-[#0a0000] text-[#661111]" : "border-[#442b00] bg-[#0a0600] text-[#664400]";
  const blink = color === "red" ? "blink-banner-red" : "blink-banner-amber";
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={lit}
      title="Press to silence audio for all alerts (alerts stay active)"
      onClick={onClick}
      className={`flex h-9 w-[116px] shrink-0 flex-col items-center justify-center border-2 hmi-mono text-[11px] font-black leading-tight tracking-[0.12em] ${lit ? on : off} ${lit && flashing ? blink : ""}`}
    >
      <span>MASTER</span>
      <span>{label}</span>
    </button>
  );
}

function Field({ label, value, className = "", wrapClass = "shrink-0" }: { label: string; value: string; className?: string; wrapClass?: string }) {
  return (
    <div className={`flex min-w-0 flex-col justify-center whitespace-nowrap border-r border-[#262626] pr-3 ${wrapClass}`}>
      <span className="hmi-mono text-[9px] font-bold uppercase tracking-[0.12em] text-[#777777] leading-none">{label}</span>
      <span className={`hmi-mono mt-1 truncate text-[13px] font-bold leading-none ${className}`} title={value}>{value}</span>
    </div>
  );
}

function ScreenTabs() {
  const screen = useHevStore((s) => s.screen);
  const setScreen = useHevStore((s) => s.setScreen);
  const fitness = useHevStore((s) => !!s.state?.fitness?.enabled);
  const tab = (id: "command" | "engineering" | "fitness", key: string, label: string) => (
    <button
      type="button"
      data-testid={`screen-${id}`}
      aria-pressed={screen === id}
      onClick={() => setScreen(id)}
      title={`Screen ${key} (keyboard ${key})`}
      className={`h-8 shrink-0 border px-2.5 hmi-mono text-[11px] font-black tracking-[0.1em] ${
        screen === id
          ? "border-[#00ff00] bg-[#002b0d] text-[#00ff00]"
          : "border-[#333333] bg-[#111111] text-[#999999] hover:border-[#777777] hover:text-white"
      }`}
    >
      [{key}] {label}
    </button>
  );
  return (
    <div className="flex shrink-0 gap-1" role="tablist" aria-label="Screens">
      {tab("command", "1", "COMMAND // HMI")}
      {tab("engineering", "2", "ENGINEERING")}
      {fitness && tab("fitness", "3", "FITNESS // CFMS")}
    </div>
  );
}

export function TopBar() {
  const now = useNow(1000);
  const state = useHevStore((s) => s.state);
  const connection = useHevStore((s) => s.connection);
  const lastOkAt = useHevStore((s) => s.lastOkAt);
  const muted = useHevStore((s) => s.muted);
  const armed = useHevStore((s) => s.audioArmed);
  const setMuted = useHevStore((s) => s.setMuted);
  const m = state?.master;
  const met = state ? state.mission.met_seconds + (connection === "ONLINE" && lastOkAt ? (now - lastOkAt) / 1000 : 0) : 0;
  const d = new Date(now);
  const utc = d.toISOString().slice(11, 19) + "Z";
  const local = d.toLocaleTimeString("en-GB", { hour12: false });
  const silenceAll = () => {
    audio.stop();
    void api.silenceAll().catch(() => undefined);
  };
  const health = state?.system_health.status ?? "--";
  const medical = state?.medical_status ?? "NOMINAL";
  return (
    <header className="flex h-12 shrink-0 items-center gap-2.5 overflow-hidden whitespace-nowrap border-b border-[#333333] bg-black px-3">
      <div className="flex shrink-0 items-center gap-2.5 border-r border-[#333333] bg-[#0d0d0d] px-2.5 py-1.5">
        <svg width="26" height="26" viewBox="0 0 64 64" aria-hidden>
          <path d="M32 6 54 18v28L32 58 10 46V18Z" fill="#001a00" stroke="#00ff00" strokeWidth="3.5" />
          <path d="M22 22v20M42 22v20M22 32h20" stroke="#ffffff" strokeWidth="4" />
        </svg>
        <div className="leading-none">
          <div className="hmi-sans text-[13px] font-black tracking-[0.14em] text-white">
            R.I.D.G.E. <span className="text-[#00ff00]">// ORION-MED HEV-1</span>
          </div>
          <div className="mt-0.5 hmi-mono text-[9px] tracking-[0.2em] text-[#888888]">AUTONOMOUS SPACE MEDICAL HMI</div>
        </div>
      </div>
      <ScreenTabs />
      <div className="h-8 w-px bg-[#333333]" />
      <Field label="Mission · Env" value={state ? `${state.mission.id} · ${state.mission.environment}` : "HEV-DEMO-01 · CISLUNAR"} wrapClass="max-w-[210px] shrink" />
      <Field label="MET (DDD:HH:MM:SS)" value={state ? fmtMET(met) : "003:04:42:10"} className="text-[#00ff00]" />
      <div className="flex-1" />
      <Annunciator testId="master-warning" label="WARNING" color="red" lit={!!m?.warning || !!m?.warning_unacked} flashing={!!m?.warning_unacked} onClick={silenceAll} />
      <Annunciator testId="master-caution" label="CAUTION" color="amber" lit={!!m?.caution || !!m?.caution_unacked} flashing={!!m?.caution_unacked} onClick={silenceAll} />
      <Field label="Med Status" value={medical} className={SEV_TEXT[medical]} />
      <Field
        label="Core Link"
        value={connection === "ONLINE" ? "ONLINE" : connection === "OFFLINE" ? "LINK LOST" : "SYNCING"}
        className={connection === "ONLINE" ? "text-[#00ff00]" : "text-[#ffb000]"}
      />
      <Field
        label="Earth Link"
        value={state ? (state.sync.link_up ? "AOS" : `LOS · ${state.sync.pending}Q`) : "AOS"}
        className={state?.sync.link_up ? "text-[#00ff00]" : "text-[#ffb000]"}
      />
      <Field label="Sys" value={health} className={health === "NOMINAL" ? "text-[#00ff00]" : "text-[#ffb000]"} />
      <Field label="UTC · Local" value={`${utc} ${local}`} className="text-white" />
      <button
        type="button"
        data-testid="audio-toggle"
        onClick={() => {
          audio.setMuted(!muted);
          setMuted(!muted);
        }}
        className={`h-8 w-[84px] shrink-0 border hmi-mono text-[10px] font-bold tracking-[0.12em] ${
          muted
            ? "border-[#555555] bg-[#141414] text-[#888888]"
            : armed
            ? "border-[#00ff00] bg-[#001f00] text-[#00ff00]"
            : "border-[#ffb000] bg-[#261a00] text-[#ffb000]"
        }`}
        title={armed ? "Mute or unmute HEV audio" : "Audio arms after the first interaction with the page"}
      >
        {muted ? "AUDIO OFF" : armed ? "AUDIO ON" : "ARM AUDIO"}
      </button>
    </header>
  );
}
