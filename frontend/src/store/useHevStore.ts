// AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import { create } from "zustand";
import type { HevSystemState, Protocol, ZoneId } from "../types/state";

export type Connection = "CONNECTING" | "ONLINE" | "OFFLINE";
export type Modal = null | "pvt" | "psych";
export type Screen = "command" | "engineering" | "fitness";
export type FitnessTab = "schedule" | "planner" | "equipment" | "recovery";

interface HevStore {
  state: HevSystemState | null;
  connection: Connection;
  lastOkAt: number | null;
  cachedSnapshotAt: string | null;
  protocols: Record<string, Protocol>;
  selectedZone: ZoneId | null;
  selectedAlertId: string | null;
  lastSeq: number | null;
  muted: boolean;
  audioArmed: boolean;
  modal: Modal;
  screen: Screen;
  fitnessTab: FitnessTab;
  selectedSessionId: string | null;
  viewCrewId: string | null;
  outboxPending: number;
  notice: string | null;
  setState: (s: HevSystemState) => void;
  setOffline: (cached?: HevSystemState | null, cachedAt?: string | null) => void;
  setProtocols: (p: Protocol[]) => void;
  selectZone: (z: ZoneId | null) => void;
  selectAlert: (id: string | null) => void;
  setMuted: (m: boolean) => void;
  setAudioArmed: (a: boolean) => void;
  setModal: (m: Modal) => void;
  setScreen: (s: Screen) => void;
  setFitnessTab: (t: FitnessTab) => void;
  selectSession: (id: string | null) => void;
  setViewCrew: (id: string | null) => void;
  setOutboxPending: (n: number) => void;
  setNotice: (n: string | null) => void;
}

export const useHevStore = create<HevStore>((set) => ({
  state: null,
  connection: "CONNECTING",
  lastOkAt: null,
  cachedSnapshotAt: null,
  protocols: {},
  selectedZone: null,
  selectedAlertId: null,
  lastSeq: null,
  muted: false,
  audioArmed: false,
  modal: null,
  screen: "command",
  fitnessTab: "schedule",
  selectedSessionId: null,
  viewCrewId: null,
  outboxPending: 0,
  notice: null,
  setState: (s) => set({ state: s, connection: "ONLINE", lastOkAt: Date.now(), cachedSnapshotAt: null, lastSeq: s.latest_event_seq }),
  setOffline: (cached, cachedAt) =>
    set((prev) => ({
      connection: "OFFLINE",
      state: prev.state ?? cached ?? null,
      cachedSnapshotAt: prev.state ? prev.cachedSnapshotAt ?? new Date(prev.lastOkAt ?? Date.now()).toISOString() : cachedAt ?? null,
    })),
  setProtocols: (p) => set({ protocols: Object.fromEntries(p.map((x) => [x.id, x])) }),
  selectZone: (z) => set({ selectedZone: z }),
  selectAlert: (id) => set({ selectedAlertId: id }),
  setMuted: (m) => set({ muted: m }),
  setAudioArmed: (a) => set({ audioArmed: a }),
  setModal: (m) => set({ modal: m }),
  setScreen: (s) => set({ screen: s }),
  setFitnessTab: (t) => set({ fitnessTab: t }),
  selectSession: (id) => set({ selectedSessionId: id }),
  setViewCrew: (id) => set({ viewCrewId: id }),
  setOutboxPending: (n) => set({ outboxPending: n }),
  setNotice: (n) => set({ notice: n }),
}));
