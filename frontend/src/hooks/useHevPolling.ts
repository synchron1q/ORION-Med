// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { useEffect } from "react";
import { api } from "../services/api";
import { audio } from "../services/audio";
import { offlineCache } from "../services/offlineCache";
import { useHevStore } from "../store/useHevStore";
import type { HevSystemState, Protocol } from "../types/state";

const POLL_MS = 1000;
const SNAPSHOT_EVERY_MS = 5000;
const WARNING_REPEAT_MS = 5000;

async function flushOutbox(): Promise<number> {
  const items = await offlineCache.pending();
  for (const item of items) {
    try {
      if (item.kind === "pvt") await api.submitPvt(item.payload as Parameters<typeof api.submitPvt>[0]);
      if (item.kind === "psych") await api.submitPsych(item.payload as Parameters<typeof api.submitPsych>[0]);
      if (item.id !== undefined) await offlineCache.remove(item.id);
    } catch {
      break; // keep order; retry on next successful poll
    }
  }
  return (await offlineCache.pending()).length;
}

/** 1 Hz state polling, audio cues, offline snapshot and outbox flushing. */
export function useHevPolling(): void {
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let lastSnapshot = 0;
    let lastWarningTone = 0;

    api.protocols()
      .then((p) => {
        useHevStore.getState().setProtocols(p);
        void offlineCache.put("protocols", p);
      })
      .catch(async () => {
        const cached = await offlineCache.get<Protocol[]>("protocols");
        if (cached) useHevStore.getState().setProtocols(cached);
      });

    const loop = async () => {
      const store = useHevStore.getState();
      const since = store.lastSeq;
      try {
        const s = await api.state(since);
        if (stopped) return;
        const wasOffline = store.connection === "OFFLINE";
        store.setState(s);
        if (since !== null) {
          for (const ev of s.events) {
            audio.cue(ev, useHevStore.getState().protocols);
            if ((ev.event_type === "RAISED" || ev.event_type === "ESCALATED") && (ev.severity === "WARNING" || ev.severity === "CAUTION")) {
              const cur = useHevStore.getState();
              const selected = s.alerts.find((a) => a.id === cur.selectedAlertId);
              const rank = { ADVISORY: 1, CAUTION: 2, WARNING: 3, NOMINAL: 0 } as const;
              if (!selected || rank[ev.severity] >= rank[selected.severity]) {
                cur.selectAlert(ev.alert_id);
                const a = s.alerts.find((x) => x.id === ev.alert_id);
                if (a) cur.selectZone(a.zone);
              }
            }
          }
        }
        const now = Date.now();
        const warningSounding = s.alerts.some((a) => a.severity === "WARNING" && a.audio_required);
        if (warningSounding && now - lastWarningTone > WARNING_REPEAT_MS) {
          if (lastWarningTone !== 0) audio.playTone("warning");
          lastWarningTone = now;
        } else if (!warningSounding) {
          lastWarningTone = 0;
        }
        if (now - lastSnapshot > SNAPSHOT_EVERY_MS) {
          lastSnapshot = now;
          void offlineCache.put("snapshot", { savedAt: new Date().toISOString(), state: s });
        }
        if (wasOffline || store.outboxPending > 0) useHevStore.getState().setOutboxPending(await flushOutbox());
      } catch {
        if (stopped) return;
        if (!useHevStore.getState().state) {
          const snap = await offlineCache.get<{ savedAt: string; state: HevSystemState }>("snapshot");
          useHevStore.getState().setOffline(snap?.state ?? null, snap?.savedAt ?? null);
        } else {
          useHevStore.getState().setOffline();
        }
      } finally {
        if (!stopped) timer = setTimeout(loop, POLL_MS);
      }
    };
    void loop();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, []);
}
