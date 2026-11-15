// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useState } from "react";
import { api } from "../../services/api";
import { offlineCache } from "../../services/offlineCache";
import { useHevStore } from "../../store/useHevStore";
import { Modal } from "./Modal";

const SCALES: { key: "mood" | "stress" | "fatigue" | "sleep_quality"; label: string; low: string; high: string }[] = [
  { key: "mood", label: "Mood", low: "very low", high: "very good" },
  { key: "stress", label: "Stress", low: "none", high: "very high" },
  { key: "fatigue", label: "Fatigue", low: "rested", high: "exhausted" },
  { key: "sleep_quality", label: "Sleep quality", low: "very poor", high: "very good" },
];

export function PsychModal() {
  const setModal = useHevStore((s) => s.setModal);
  const connection = useHevStore((s) => s.connection);
  const setOutboxPending = useHevStore((s) => s.setOutboxPending);
  const [values, setValues] = useState({ mood: 3, stress: 3, fatigue: 3, sleep_quality: 3 });
  const [shared, setShared] = useState(false);
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  const submit = async () => {
    const body = { ...values, notes, private: !shared };
    try {
      if (connection !== "ONLINE") throw new Error("offline");
      await api.submitPsych(body);
      setStatus(shared ? "Recorded and queued for the flight surgeon." : "Recorded privately on board. Not downlinked.");
    } catch {
      await offlineCache.queue("psych", body);
      setOutboxPending((await offlineCache.pending()).length);
      setStatus("HEV-1 core unreachable - stored locally and will be sent automatically.");
    }
  };

  return (
    <Modal title="Private self-check" onClose={() => setModal(null)}>
      <div className="flex flex-col gap-3 text-[13px]">
        {SCALES.map((s) => (
          <div key={s.key} className="flex items-center gap-3">
            <span className="w-[110px] tracking-[0.1em]">{s.label.toUpperCase()}</span>
            <span className="w-[70px] text-right text-[11px] text-hev-dim">{s.low}</span>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" aria-pressed={values[s.key] === n} data-testid={`psych-${s.key}-${n}`}
                  onClick={() => setValues({ ...values, [s.key]: n })}
                  className={`h-8 w-9 border text-[13px] ${values[s.key] === n ? "border-hev-cyan bg-hev-cyan/15 text-hev-cyan" : "border-hev-line text-hev-white/70"}`}>
                  {n}
                </button>
              ))}
            </div>
            <span className="text-[11px] text-hev-dim">{s.high}</span>
          </div>
        ))}
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} placeholder="Optional private note"
          className="h-16 resize-none border border-hev-line bg-black p-2 text-[12px] text-hev-white outline-none focus:border-hev-cyan" />
        <label className="flex items-center gap-2 text-[12px]">
          <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
          Share this entry with the flight surgeon (default: private, stays on board)
        </label>
        <p className="m-0 text-[11px] text-hev-dim">Self-assessments show personal trends only. HEV-1 never labels a crew member with a mental-health condition.</p>
        {status ? (
          <div className="text-[12px] text-hev-green" data-testid="psych-status">{status}</div>
        ) : (
          <button type="button" data-testid="psych-submit" onClick={() => void submit()}
            className="h-9 border border-hev-cyan text-[12px] tracking-[0.2em] text-hev-cyan hover:bg-hev-cyan/10">RECORD</button>
        )}
      </div>
    </Modal>
  );
}
