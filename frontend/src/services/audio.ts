// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
// HEV voice and tone notifications. Local only: Web Speech API (OS voices)
// plus prerecorded WAV tones in /public/audio. Visual alerts never depend on audio.
import type { AlertEventCue, Protocol } from "../types/state";

export type Tone = "advisory" | "caution" | "warning";

const PHRASES: Record<string, string> = {
  cabin_co2: "Elevated carbon dioxide detected.",
  heart_rate: "Heart rate exceeds configured limits.",
  hrv: "Heart rate variability outside configured limits.",
  dose_rate: "Radiation event detected. Review mission exposure status.",
  accumulated_dose: "Mission exposure indicator reached. Review mission exposure status.",
  spo2: "Blood oxygen saturation outside configured limits.",
  resp_rate: "Respiratory rate outside configured limits.",
  body_temp: "Core temperature outside configured limits.",
  cabin_pressure: "Cabin pressure outside configured limits.",
  cabin_o2: "Cabin oxygen outside configured limits.",
  cabin_temp: "Cabin temperature outside configured limits.",
  humidity: "Cabin humidity outside configured limits.",
  pvt_mean_rt: "Reaction time slower than configured limit.",
  sleep_hours: "Sleep duration below configured limit.",
};

const spokenKit = (kit: string) => kit.replace(/^KIT\s+/i, "medical kit ").replace(/-/g, " ");

export function cueFor(ev: AlertEventCue, protocols: Record<string, Protocol>): { tone?: Tone; text?: string } {
  if (ev.silenced) return {};
  const proto = ev.protocol_id ? protocols[ev.protocol_id] : undefined;
  const kitText = proto && proto.kit !== "NONE" ? ` Countermeasure protocol available. Retrieve ${spokenKit(proto.kit)}.` : "";
  switch (ev.event_type) {
    case "RAISED":
    case "ESCALATED":
    case "RECURRED": {
      if (ev.kind === "CORRELATION" || ev.severity === "ADVISORY") return { tone: "advisory" };
      const lead = ev.severity === "WARNING" ? "Warning." : "Attention.";
      if (ev.kind === "SENSOR_FAULT") return { tone: "caution", text: `${lead} Sensor fault. Telemetry unavailable.${kitText}` };
      if (ev.kind === "DATA_STALE") return { tone: "caution", text: `${lead} Telemetry stale. Measurement not current.` };
      const phrase = PHRASES[ev.parameter ?? ""] ?? `${ev.title.toLowerCase()}.`;
      return { tone: ev.severity === "WARNING" ? "warning" : "caution", text: `${lead} ${phrase}${kitText}` };
    }
    case "RECOVERY_STARTED":
      if (ev.severity === "WARNING" || ev.severity === "CAUTION")
        return { text: "Parameters returning to configured range. Recovery in progress." };
      return {};
    case "CLEARED":
      if (ev.severity === "WARNING" || ev.severity === "CAUTION") return { tone: "advisory", text: "Alert cleared. Event preserved in mission log." };
      return {};
    default:
      return {};
  }
}

class AudioManager {
  muted = false;
  armed = false;
  readonly speechAvailable = typeof window !== "undefined" && "speechSynthesis" in window;

  arm(): void {
    this.armed = true;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    if (muted) this.stop();
  }

  playTone(tone: Tone): void {
    if (this.muted || !this.armed || typeof Audio === "undefined") return;
    try {
      const el = new Audio(`/audio/${tone}.wav`);
      el.volume = tone === "advisory" ? 0.5 : 0.85;
      void el.play().catch(() => undefined);
    } catch {
      /* audio unavailable: visual alerts remain */
    }
  }

  speak(text: string, urgent = false): void {
    if (this.muted || !this.armed || !this.speechAvailable) return;
    try {
      const synth = window.speechSynthesis;
      if (urgent) synth.cancel();
      const u = new SpeechSynthesisUtterance(text);
      const voices = synth.getVoices();
      const voice = voices.find((v) => /en[-_](US|GB)/i.test(v.lang) && /female|zira|aria|jenny|samantha|google/i.test(v.name))
        ?? voices.find((v) => v.lang.toLowerCase().startsWith("en"));
      if (voice) u.voice = voice;
      u.rate = 0.98;
      u.pitch = 0.85;
      synth.speak(u);
    } catch {
      /* degrade silently */
    }
  }

  cue(ev: AlertEventCue, protocols: Record<string, Protocol>): void {
    const { tone, text } = cueFor(ev, protocols);
    if (tone) this.playTone(tone);
    if (text) window.setTimeout(() => this.speak(text, ev.severity === "WARNING"), tone === "warning" ? 1400 : 600);
  }

  stop(): void {
    if (this.speechAvailable) window.speechSynthesis.cancel();
  }
}

export const audio = new AudioManager();
