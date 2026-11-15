// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { api, ApiError } from "../../services/api";
import { audio } from "../../services/audio";
import { useHevStore } from "../../store/useHevStore";

async function run(fn: () => Promise<unknown>, okNotice?: string): Promise<boolean> {
  const store = useHevStore.getState();
  if (store.connection !== "ONLINE") {
    store.setNotice("HEV-1 core unreachable - action not sent. Alerts remain active.");
    return false;
  }
  try {
    await fn();
    store.setNotice(okNotice ?? null);
    return true;
  } catch (e) {
    store.setNotice(e instanceof ApiError ? e.message : "Action failed - core unreachable");
    return false;
  }
}

export const alertActions = {
  ack: (id: string) => {
    audio.stop();
    return run(() => api.ack(id));
  },
  silence: (id: string) => {
    audio.stop();
    return run(() => api.silence(id));
  },
  confirmStep: (id: string, i: number) => run(() => api.confirmStep(id, i)),
  clear: (id: string) => run(() => api.resolve(id), "Alert cleared and archived. History preserved in mission log."),
};
