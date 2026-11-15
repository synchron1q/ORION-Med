// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import { offlineCache } from "../../services/offlineCache";
import { useHevStore } from "../../store/useHevStore";
import { classifyResponse, nextDelayMs, RESPONSE_WINDOW_MS, summarize, TEST_DURATION_MS } from "./pvt";
import { Modal } from "./Modal";

type Phase = "intro" | "running" | "done";

export function PvtModal() {
  const setModal = useHevStore((s) => s.setModal);
  const connection = useHevStore((s) => s.connection);
  const setOutboxPending = useHevStore((s) => s.setOutboxPending);
  const [phase, setPhase] = useState<Phase>("intro");
  const [visible, setVisible] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [result, setResult] = useState<{ rts: number[]; misses: number; falseStarts: number; status: string } | null>(null);
  const [baseline, setBaseline] = useState<number | null>(null);
  const t0 = useRef(0);
  const onset = useRef<number | null>(null);
  const rts = useRef<number[]>([]);
  const misses = useRef(0);
  const falseStarts = useRef(0);
  const timers = useRef<number[]>([]);

  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  };
  const later = (fn: () => void, ms: number) => timers.current.push(window.setTimeout(fn, ms));

  const scheduleNext = useCallback(() => {
    const delay = nextDelayMs();
    if (performance.now() - t0.current + delay >= TEST_DURATION_MS) return;
    later(() => {
      onset.current = performance.now();
      setVisible(true);
      later(() => {
        if (onset.current !== null) {
          misses.current += 1;
          onset.current = null;
          setVisible(false);
          scheduleNext();
        }
      }, RESPONSE_WINDOW_MS);
    }, delay);
  }, []);

  const finish = useCallback(async () => {
    clearTimers();
    onset.current = null;
    setVisible(false);
    setPhase("done");
    const body = { reaction_times_ms: rts.current, misses: misses.current, false_starts: falseStarts.current, duration_s: TEST_DURATION_MS / 1000 };
    let status = "Stored in HEV-1 local database";
    try {
      if (connection !== "ONLINE") throw new Error("offline");
      await api.submitPvt(body);
    } catch {
      await offlineCache.queue("pvt", body);
      setOutboxPending((await offlineCache.pending()).length);
      status = "HEV-1 core unreachable - result queued locally and will be sent automatically";
    }
    setResult({ rts: [...rts.current], misses: misses.current, falseStarts: falseStarts.current, status });
  }, [connection, setOutboxPending]);

  const start = () => {
    rts.current = [];
    misses.current = 0;
    falseStarts.current = 0;
    t0.current = performance.now();
    setResult(null);
    setPhase("running");
    scheduleNext();
    later(() => void finish(), TEST_DURATION_MS);
  };

  const respond = useCallback(() => {
    if (phase !== "running") return;
    const r = classifyResponse(onset.current, performance.now());
    if (r.kind === "false_start") {
      falseStarts.current += 1;
      setFlash("FALSE START");
      window.setTimeout(() => setFlash(null), 400);
      return;
    }
    rts.current.push(r.rt);
    onset.current = null;
    setVisible(false);
    clearTimers();
    later(() => void finish(), Math.max(0, TEST_DURATION_MS - (performance.now() - t0.current)));
    scheduleNext();
  }, [phase, finish, scheduleNext]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        e.preventDefault();
        respond();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [respond]);

  useEffect(() => () => clearTimers(), []);
  useEffect(() => {
    api.pvtHistory().then((h) => {
      const prev = h.results.map((r) => r.mean_rt_ms).filter((x): x is number => x !== null).slice(0, 5);
      setBaseline(prev.length ? prev.reduce((a, b) => a + b, 0) / prev.length : null);
    }).catch(() => setBaseline(null));
  }, []);

  const sum = result ? summarize(result.rts) : null;
  return (
    <Modal title="Psychomotor vigilance test (10 s)" onClose={() => { clearTimers(); setModal(null); }}>
      {phase === "intro" && (
        <div className="flex flex-col gap-3 text-[13px]">
          <p className="m-0">A red square appears at random intervals. Respond as fast as possible by tapping the test area or pressing SPACE. Do not respond before the square appears.</p>
          <p className="m-0 text-hev-dim">Short demonstration version. Results are trends for fatigue awareness, not a medical or psychiatric diagnosis.</p>
          <button type="button" data-testid="pvt-start" onClick={start} className="h-10 border border-hev-cyan text-[13px] tracking-[0.2em] text-hev-cyan hover:bg-hev-cyan/10">START TEST</button>
        </div>
      )}
      {phase === "running" && (
        <button type="button" data-testid="pvt-area" onPointerDown={respond}
          className="relative flex h-[300px] w-full items-center justify-center border border-hev-line bg-black">
          {visible && <span className="block h-28 w-28 bg-hev-red" data-testid="pvt-stimulus" />}
          {!visible && <span className="text-[12px] tracking-[0.2em] text-hev-dim">{flash ?? "WAIT FOR STIMULUS"}</span>}
        </button>
      )}
      {phase === "done" && (
        <div className="flex flex-col gap-2 text-[13px]" data-testid="pvt-result">
          {!sum ? <div className="text-hev-dim">Submitting...</div> : (
            <>
              <div className="grid grid-cols-5 gap-2 text-center">
                {[
                  ["MEAN RT", sum.meanRt !== null ? `${sum.meanRt} ms` : "--"],
                  ["MEDIAN", sum.medianRt !== null ? `${sum.medianRt} ms` : "--"],
                  ["LAPSES >500", String(sum.lapses)],
                  ["MISSED", String(result?.misses ?? 0)],
                  ["FALSE STARTS", String(result?.falseStarts ?? 0)],
                ].map(([k, v]) => (
                  <div key={k} className="border border-hev-line p-2">
                    <div className="hev-label text-[10px]">{k}</div>
                    <div className="hev-num text-[18px] text-hev-cyan">{v}</div>
                  </div>
                ))}
              </div>
              <div className="text-hev-white/85">
                {baseline !== null && sum.meanRt !== null
                  ? `Compared with your recent average (${baseline.toFixed(0)} ms): ${sum.meanRt - baseline >= 0 ? "+" : ""}${(sum.meanRt - baseline).toFixed(0)} ms.`
                  : "No previous results for comparison yet."}
              </div>
              <div className="text-[11px] text-hev-dim">{result?.status}</div>
              <button type="button" onClick={start} className="h-9 border border-hev-cyan/70 text-[12px] tracking-[0.2em] text-hev-cyan">REPEAT TEST</button>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
