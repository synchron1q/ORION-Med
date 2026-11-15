// Unified R.I.D.G.E. // ORION-HMI Design (from Desktop/orion-med) + Full HEV-1 v1.0.7 Features & Details (from orion-med 1123)
import React, { useEffect, useRef, useState } from "react";
import { Chip, SourceBadge } from "./Panel";
import { api } from "../services/api";
import { audio } from "../services/audio";
import { ageFrom, fmtValue, SEV_BORDER, SEV_TEXT, unitLabel } from "../services/format";
import { useNow } from "../hooks/useNow";
import { useHevStore } from "../store/useHevStore";
import type { Alert, GateStatus, ParameterState, Readiness, SeverityName, ZoneId as HevZoneId } from "../types/state";
import { alertActions } from "../modules/alerts/actions";
import { paramSeverity } from "../modules/biometrics/ParamRow";
import { HumanTwin } from "../modules/digital-twin/HumanTwin";

export type CrewKey = "SMITH" | "DOE";
export type CadZoneId = "HEAD" | "LUNGS" | "HEART";
export type FaultMode = "NOMINAL" | "HYPOXIA" | "HEMORRHAGE" | "CO2_SPIKE" | "SOLAR_FLARE" | "TACHYCARDIA" | "SENSOR_FAILURE";
export type SystemPhase = "NOMINAL" | "EMERGENCY" | "HOLD_VERIFICATION";

interface TelemetryData {
  hr: number;
  abpSys: number;
  abpDia: number;
  abpMap: number;
  shockIndex: number;
  cardiacOutput: number;
  lactate: number;
  spo2: number;
  respRate: number;
  etCo2: number;
  pao2: number;
  minuteVent: number;
  suitO2Kpa: number;
  cogIndex: number;
  pvtRt: number;
  icpMmhg: number;
  cnsO2Sat: number;
  coreTemp: number;
  cabinCo2Ppm: number;
  cabinO2Pct: number;
  cabinPressKpa: number;
  doseRateUgy: number;
}

interface CrewProfile {
  id: CrewKey;
  hevId: string;
  code: string;
  name: string;
  role: string;
  suit: string;
  base: TelemetryData;
}

interface EmergencyProtocol {
  code: string;
  faultZone: CadZoneId;
  hevZone: HevZoneId;
  title: string;
  rootCause: string;
  kitCode: string;
  kitName: string;
  kitLocation: string;
  instructions: string[];
  holdCriteria: string;
}

interface CrewRuntimeState {
  fault: FaultMode;
  phase: SystemPhase;
  holdSeconds: number;
  elapsedSeconds: number;
  acked: boolean;
  stepsDone: boolean[];
  telemetry: TelemetryData;
}

interface TelemetryRowSpec {
  id: string;
  paramId?: string;
  zone: CadZoneId;
  systemLabel: string;
  paramLabel: string;
  getValue: (t: TelemetryData) => string;
  normLabel: string;
  evaluate: (t: TelemetryData) => "NOMINAL" | "CAUTION" | "CRITICAL";
}

const HOLD_TOTAL_S = 30.0;

const CREW_PROFILES: Record<CrewKey, CrewProfile> = {
  SMITH: {
    id: "SMITH",
    hevId: "CM-1",
    code: "CM-01",
    name: "Cmdr. Smith",
    role: "COMMANDER",
    suit: "ORION-IVA-01",
    base: {
      hr: 68,
      abpSys: 118,
      abpDia: 76,
      abpMap: 90,
      shockIndex: 0.58,
      cardiacOutput: 5.4,
      lactate: 1.0,
      spo2: 98.4,
      respRate: 14,
      etCo2: 38,
      pao2: 95,
      minuteVent: 7.2,
      suitO2Kpa: 21.3,
      cogIndex: 99,
      pvtRt: 234,
      icpMmhg: 11.2,
      cnsO2Sat: 74.5,
      coreTemp: 36.8,
      cabinCo2Ppm: 1120,
      cabinO2Pct: 20.9,
      cabinPressKpa: 101.3,
      doseRateUgy: 18.0,
    },
  },
  DOE: {
    id: "DOE",
    hevId: "CM-2",
    code: "CM-02",
    name: "Eng. Doe",
    role: "FLIGHT ENGINEER",
    suit: "ORION-IVA-02",
    base: {
      hr: 63,
      abpSys: 114,
      abpDia: 72,
      abpMap: 86,
      shockIndex: 0.55,
      cardiacOutput: 5.1,
      lactate: 0.9,
      spo2: 99.0,
      respRate: 13,
      etCo2: 37,
      pao2: 97,
      minuteVent: 6.8,
      suitO2Kpa: 21.4,
      cogIndex: 99,
      pvtRt: 222,
      icpMmhg: 10.8,
      cnsO2Sat: 75.2,
      coreTemp: 36.6,
      cabinCo2Ppm: 1120,
      cabinO2Pct: 20.9,
      cabinPressKpa: 101.3,
      doseRateUgy: 18.0,
    },
  },
};

const EMERGENCY_PROTOCOLS: Record<Exclude<FaultMode, "NOMINAL">, EmergencyProtocol> = {
  HYPOXIA: {
    code: "ALM-RESP-01 // HYPOXIA",
    faultZone: "LUNGS",
    hevZone: "respiratory",
    title: "ACUTE HYPOXIA // CRITICAL DESATURATION (SpO2 < 85%)",
    rootCause: "O2 PARTIAL PRESSURE DROP IN BREATHING LOOP (< 14.0 kPa) -> ALVEOLAR HYPOXIA",
    kitCode: "MED-KIT O2-MASK [B-02] / KIT ECLSS-03",
    kitName: "HIGH-FLOW DEMAND O2 MASK + 100% O2 CYLINDER",
    kitLocation: "MEDICAL AIRLOCK B-02 (FORWARD BULKHEAD)",
    instructions: [
      "DON DEMAND O2 MASK ON CREWMEMBER AND ENGAGE 100% O2 PURGE (15 L/MIN)",
      "SWITCH SUIT SUPPLY VALVE TO HIGH-PRESSURE BACKUP LOOP [AUX-O2 OPEN]",
      "MONITOR SpO2 RECOVERY ABOVE 92.0% AND PaO2 PARTIAL PRESSURE RESTORATION",
      "START 30-SECOND HOLD TIMER (HOLD TIME 30s) TO VERIFY RECOVERY",
    ],
    holdCriteria: "SpO2 >= 92.0% AND PaO2 >= 80 mmHg SUSTAINED FOR 30.0 SECONDS",
  },
  HEMORRHAGE: {
    code: "ALM-CARD-02 // HEMORRHAGE",
    faultZone: "HEART",
    hevZone: "cardiovascular",
    title: "CLASS III HEMORRHAGIC SHOCK // HYPOTENSION & TACHYCARDIA",
    rootCause: "ACUTE ARTERIAL BLOOD LOSS -> HYPOVOLEMIA (BP < 80/50 mmHg, HR > 130 BPM, SI > 1.8)",
    kitCode: "TRAUMA-KIT [KIT A-1]",
    kitName: "TOURNIQUET A-1 (C-A-T GEN-7) + HEMOSTATIC GAUZE + IV FLUID BAG",
    kitLocation: "TRAUMA BAY M-01 (RACK 2)",
    instructions: [
      "APPLY TOURNIQUET A-1 PROXIMAL TO BLEEDING SITE AND TIGHTEN WINDLASS UNTIL BLEEDING STOPS",
      "SECURE TOURNIQUET A-1 CLIP, LOG APPLICATION TIME (MET), AND PACK WOUND",
      "ESTABLISH 18G IV ACCESS AND BEGIN CRYSTALLOID BOLUS INFUSION (500 ML)",
      "CONFIRM ABP SYS >= 95 mmHg, HR <= 110 BPM AND START 30s HOLD TIME CHECK",
    ],
    holdCriteria: "ABP SYS >= 95 mmHg, HR <= 110 BPM, SHOCK INDEX < 0.90 FOR 30.0 SECONDS",
  },
  CO2_SPIKE: {
    code: "ALM-NEURO-03 // HYPERCAPNIA",
    faultZone: "HEAD",
    hevZone: "respiratory",
    title: "TOXIC HYPERCAPNIA // CO2 SCRUBBER FAILURE (> 6500 ppm)",
    rootCause: "CDRA BED-A DESORPTION VALVE JAM -> CO2 ACCUMULATION & CNS DEPRESSION",
    kitCode: "ECLSS-KIT [KIT ECLSS-03 / LiOH C-03]",
    kitName: "EMERGENCY LiOH C-03 SCRUBBER CARTRIDGE + CLOSED-LOOP PBA RESPIRATOR",
    kitLocation: "ECLSS ENGINEERING BAY E-04 (DECK B)",
    instructions: [
      "TRANSITION CREW TO PORTABLE BREATHING APPARATUS (PBA CLOSED-LOOP)",
      "MANUALLY OPEN CDRA BED-B BACKUP ABSORPTION LOOP BYPASS [VALVE V-204]",
      "INSTALL EMERGENCY LiOH C-03 CARTRIDGE INTO FORCED VENTILATION DUCT",
      "VERIFY CO2 DROP < 3500 ppm, COGNITIVE INDEX RECOVERY & HOLD TIME 30s",
    ],
    holdCriteria: "CABIN CO2 <= 3500 ppm AND COGNITIVE INDEX >= 90% FOR 30.0 SECONDS",
  },
  SOLAR_FLARE: {
    code: "ALM-RAD-04 // SOLAR PARTICLE EVENT",
    faultZone: "HEAD",
    hevZone: "radiation",
    title: "SPE RADIATION ALERT // SOLAR FLARE & PROTON STORM",
    rootCause: "X-CLASS FLARE (NASA DONKI SEP) -> EXPONENTIAL DOSE RATE SURGE (> 250 µGy/h)",
    kitCode: "RAD-KIT [STORM SHELTER R-01]",
    kitName: "PERSONAL DOSIMETER CPD + WATER-WALL SHIELDING PACK",
    kitLocation: "RADIATION STORM SHELTER (SECTOR C-01)",
    instructions: [
      "IMMEDIATELY RELOCATE CREW TO RADIATION STORM SHELTER AND ABORT EVA (EVA NO-GO)",
      "REINFORCE SHELTER WALLS WITH WATER CONTAINERS AND POLYETHYLENE SHIELDING BLOCKS",
      "CROSS-CHECK PERSONAL DOSIMETER READINGS AND CUMULATIVE DOSE AGAINST MISSION LIMIT",
      "REMAIN IN SHELTER UNTIL PROTON FLUX SUBSIDES AND VERIFY HOLD TIME 30s",
    ],
    holdCriteria: "DOSE RATE < 80 µGy/h AND BACKGROUND STABILIZED FOR 30.0 SECONDS",
  },
  TACHYCARDIA: {
    code: "ALM-CARD-05 // TACHYCARDIA",
    faultZone: "HEART",
    hevZone: "cardiovascular",
    title: "PAROXYSMAL TACHYCARDIA // RESTING HR > 135 BPM",
    rootCause: "SYMPATHOADRENAL OVERLOAD / ARRHYTHMIA WITH NORMAL ARTERIAL BLOOD PRESSURE",
    kitCode: "CARDIO-KIT [MED-PACK C-01]",
    kitName: "12-LEAD ECG MONITOR + ELECTROLYTE SOLUTION + PRESCRIBED BETA-BLOCKER",
    kitLocation: "MEDICAL RACK M-02",
    instructions: [
      "PLACE CREWMEMBER AT REST AND CEASE ALL PHYSICAL / OPERATOR EXERTION",
      "PERFORM VAGAL MANEUVERS (BREATHING MANEUVER) AND RECORD 12-LEAD ECG",
      "ADMINISTER ORAL REHYDRATION WITH ELECTROLYTE SOLUTION (500 ML)",
      "MONITOR HR REDUCTION <= 110 BPM AND COMPLETE 30-SECOND VERIFICATION",
    ],
    holdCriteria: "HR <= 110 BPM AND HRV RMSSD >= 30 ms FOR 30.0 SECONDS",
  },
  SENSOR_FAILURE: {
    code: "ALM-SYS-06 // SENSOR FAULT",
    faultZone: "HEART",
    hevZone: "cardiovascular",
    title: "BIOMETRIC SENSOR FAULT // TELEMETRY INTEGRITY LOSS",
    rootCause: "CHEST BIOSENSOR CM-1 CONTACT LOSS -> SENSOR_FAULT STATUS (DATA NOT TREATED AS NOMINAL)",
    kitCode: "DIAG-KIT [BIO-HARNESS S-02]",
    kitName: "BACKUP BIOMETRIC HARNESS + CONDUCTIVE GEL + TELEMETRY CABLE",
    kitLocation: "SUIT TECHNICAL LOCKER S-02",
    instructions: [
      "INSPECT TELEMETRY CABLE CONNECTOR AND BIO-HARNESS ELECTRODE CONTACT",
      "PERFORM MANUAL PULSE AND SpO2 CHECK WITH BACKUP FINGERTIP PULSE OXIMETER",
      "SWITCH BIOSENSOR CHANNEL TO BACKUP PATH B OR REPLACE SENSOR UNIT",
      "CONFIRM VALID TELEMETRY PACKETS (QUALITY: GOOD) SUSTAINED FOR 30.0 SECONDS",
    ],
    holdCriteria: "CHANNEL STATUS = OK (QUALITY: GOOD) FOR 30.0 SECONDS",
  },
};

const TELEMETRY_TABLE_ROWS: TelemetryRowSpec[] = [
  // HEART // HEART & HEMODYNAMICS
  {
    id: "hr",
    paramId: "heart_rate",
    zone: "HEART",
    systemLabel: "CARDIO // HEART",
    paramLabel: "HEART RATE (BPM)",
    getValue: (t) => `${String(Math.round(t.hr)).padStart(3, "0")} BPM`,
    normLabel: "050 .. 110 BPM",
    evaluate: (t) => (t.hr > 125 || t.hr < 45 ? "CRITICAL" : t.hr > 110 || t.hr < 50 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "abp",
    paramId: "bp_systolic",
    zone: "HEART",
    systemLabel: "CARDIO // HEART",
    paramLabel: "ARTERIAL BP (BLOOD PRESSURE)",
    getValue: (t) => `${String(Math.round(t.abpSys)).padStart(3, "0")}/${String(Math.round(t.abpDia)).padStart(2, "0")} mmHg`,
    normLabel: "095/60 .. 135/88 mmHg",
    evaluate: (t) => (t.abpSys < 85 || t.abpSys > 155 ? "CRITICAL" : t.abpSys < 95 || t.abpSys > 135 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "map",
    zone: "HEART",
    systemLabel: "CARDIO // HEART",
    paramLabel: "MEAN ARTERIAL PRESS (MAP)",
    getValue: (t) => `${String(Math.round(t.abpMap)).padStart(3, "0")} mmHg`,
    normLabel: "070 .. 105 mmHg",
    evaluate: (t) => (t.abpMap < 62 ? "CRITICAL" : t.abpMap < 70 || t.abpMap > 105 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "si",
    zone: "HEART",
    systemLabel: "CARDIO // HEART",
    paramLabel: "SHOCK INDEX (HR/SBP RATIO)",
    getValue: (t) => `${t.shockIndex.toFixed(2)} RATIO`,
    normLabel: "0.45 .. 0.85 RATIO",
    evaluate: (t) => (t.shockIndex >= 1.2 ? "CRITICAL" : t.shockIndex > 0.85 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "co",
    zone: "HEART",
    systemLabel: "CARDIO // HEART",
    paramLabel: "CARDIAC OUTPUT (CO)",
    getValue: (t) => `${t.cardiacOutput.toFixed(1)} L/min`,
    normLabel: "4.2 .. 6.5 L/min",
    evaluate: (t) => (t.cardiacOutput < 3.4 ? "CRITICAL" : t.cardiacOutput < 4.2 ? "CAUTION" : "NOMINAL"),
  },

  // LUNGS // LUNGS & GAS EXCHANGE
  {
    id: "spo2",
    paramId: "spo2",
    zone: "LUNGS",
    systemLabel: "RESP // LUNGS",
    paramLabel: "ARTERIAL SpO2 (O2 SATURATION)",
    getValue: (t) => `${t.spo2.toFixed(1)} %`,
    normLabel: "94.0 .. 100.0 %",
    evaluate: (t) => (t.spo2 < 85.0 ? "CRITICAL" : t.spo2 < 94.0 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "pao2",
    zone: "LUNGS",
    systemLabel: "RESP // LUNGS",
    paramLabel: "ALVEOLAR PaO2 (O2 PARTIAL PRESS.)",
    getValue: (t) => `${String(Math.round(t.pao2)).padStart(3, "0")} mmHg`,
    normLabel: "080 .. 105 mmHg",
    evaluate: (t) => (t.pao2 < 58 ? "CRITICAL" : t.pao2 < 80 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "rr",
    paramId: "resp_rate",
    zone: "LUNGS",
    systemLabel: "RESP // LUNGS",
    paramLabel: "RESPIRATION RATE (BREATHS/MIN)",
    getValue: (t) => `${String(Math.round(t.respRate)).padStart(2, "0")} rpm`,
    normLabel: "10 .. 20 rpm",
    evaluate: (t) => (t.respRate > 24 || t.respRate < 8 ? "CRITICAL" : t.respRate > 20 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "etco2",
    zone: "LUNGS",
    systemLabel: "RESP // LUNGS",
    paramLabel: "END-TIDAL CO2 (CAPNOGRAPHY EtCO2)",
    getValue: (t) => `${String(Math.round(t.etCo2)).padStart(2, "0")} mmHg`,
    normLabel: "35 .. 45 mmHg",
    evaluate: (t) => (t.etCo2 > 52 || t.etCo2 < 28 ? "CRITICAL" : t.etCo2 > 45 || t.etCo2 < 35 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "suito2",
    paramId: "cabin_o2",
    zone: "LUNGS",
    systemLabel: "RESP // LUNGS",
    paramLabel: "LOOP / CABIN O2 (LOOP O2 PRESSURE)",
    getValue: (t) => `${t.suitO2Kpa.toFixed(1)} kPa`,
    normLabel: "20.0 .. 22.5 kPa",
    evaluate: (t) => (t.suitO2Kpa < 15.5 ? "CRITICAL" : t.suitO2Kpa < 20.0 ? "CAUTION" : "NOMINAL"),
  },

  // HEAD // HEAD, CNS, RADIATION & ENVIRONMENT
  {
    id: "cog",
    zone: "HEAD",
    systemLabel: "NEURO // HEAD",
    paramLabel: "COGNITIVE INDEX",
    getValue: (t) => `${String(Math.round(t.cogIndex)).padStart(2, "0")} %`,
    normLabel: "90 .. 100 %",
    evaluate: (t) => (t.cogIndex < 70 ? "CRITICAL" : t.cogIndex < 90 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "cnso2",
    zone: "HEAD",
    systemLabel: "NEURO // HEAD",
    paramLabel: "CEREBRAL rSO2 (BRAIN OXYGENATION)",
    getValue: (t) => `${t.cnsO2Sat.toFixed(1)} %`,
    normLabel: "65.0 .. 80.0 %",
    evaluate: (t) => (t.cnsO2Sat < 55.0 ? "CRITICAL" : t.cnsO2Sat < 65.0 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "pvt",
    paramId: "pvt_mean_rt",
    zone: "HEAD",
    systemLabel: "NEURO // HEAD",
    paramLabel: "PVT REACTION TIME (LATENCY)",
    getValue: (t) => `${String(Math.round(t.pvtRt)).padStart(3, "0")} ms`,
    normLabel: "200 .. 280 ms",
    evaluate: (t) => (t.pvtRt > 380 ? "CRITICAL" : t.pvtRt > 280 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "co2cabin",
    paramId: "cabin_co2",
    zone: "HEAD",
    systemLabel: "ECLSS // CABIN",
    paramLabel: "CABIN CO2 (CONCENTRATION)",
    getValue: (t) => `${String(Math.round(t.cabinCo2Ppm)).padStart(4, "0")} ppm`,
    normLabel: "0400 .. 3500 ppm",
    evaluate: (t) => (t.cabinCo2Ppm > 5000 ? "CRITICAL" : t.cabinCo2Ppm > 3500 ? "CAUTION" : "NOMINAL"),
  },
  {
    id: "doserate",
    paramId: "dose_rate",
    zone: "HEAD",
    systemLabel: "RAD // RADIATION",
    paramLabel: "RADIATION DOSE RATE",
    getValue: (t) => `${t.doseRateUgy.toFixed(1)} µGy/h`,
    normLabel: "10.0 .. 80.0 µGy/h",
    evaluate: (t) => (t.doseRateUgy > 200 ? "CRITICAL" : t.doseRateUgy > 80 ? "CAUTION" : "NOMINAL"),
  },
];

const EVA_TEXT: Record<Readiness["eva"]["status"], { text: string; sev: SeverityName }> = {
  NO_BLOCKERS: { text: "NO BLOCKERS FOUND", sev: "NOMINAL" },
  REVIEW: { text: "REVIEW REQUIRED", sev: "CAUTION" },
  DATA_INCOMPLETE: { text: "DATA INCOMPLETE", sev: "CAUTION" },
  HOLD_RECOMMENDED: { text: "HOLD RECOMMENDED", sev: "WARNING" },
};

const GATE_STYLE: Record<GateStatus, string> = {
  CLEAR: "border-[#00ff00] bg-[#001a00] text-[#00ff00]",
  REVIEW: "border-[#ffb000] bg-[#261a00] text-[#ffb000]",
  UNKNOWN: "border-[#7f8fa6] bg-[#14181f] text-[#7f8fa6]",
  HOLD: "border-[#ff0000] bg-[#2b0000] text-[#ff0000]",
};

const STATUS_TEXT: Record<string, string> = {
  STALE: "DATA STALE",
  SENSOR_FAULT: "SENSOR FAULT",
  NO_DATA: "NO DATA",
  NOT_INSTRUMENTED: "NO SENSOR",
};

const SCENARIO_TO_FAULT: Record<string, FaultMode> = {
  nominal: "NOMINAL",
  hypoxia: "HYPOXIA",
  hemorrhage: "HEMORRHAGE",
  high_co2: "CO2_SPIKE",
  solar_flare: "SOLAR_FLARE",
  tachycardia: "TACHYCARDIA",
  sensor_failure: "SENSOR_FAILURE",
};

// ============================================================================
// TECHNICAL CAD WIREFRAME HUMAN SVG (ANTERIOR VIEW — CLICKABLE ZONES)
// ============================================================================
interface HumanWireframeSvgProps {
  selectedZone: CadZoneId | null;
  onSelectZone: (zone: CadZoneId) => void;
  fault: FaultMode;
  phase: SystemPhase;
  telemetry: TelemetryData;
}

const HumanWireframeSvg: React.FC<HumanWireframeSvgProps> = ({
  selectedZone,
  onSelectZone,
  fault,
  phase,
  telemetry,
}) => {
  const headCritical =
    (fault === "CO2_SPIKE" || fault === "HYPOXIA" || fault === "SOLAR_FLARE") && phase !== "NOMINAL";
  const lungsCritical =
    (fault === "HYPOXIA" || fault === "CO2_SPIKE") && phase !== "NOMINAL";
  const heartCritical =
    (fault === "HEMORRHAGE" || fault === "TACHYCARDIA" || fault === "SENSOR_FAILURE") && phase !== "NOMINAL";

  const getZoneClass = (_zone: CadZoneId, isCrit: boolean) => {
    if (isCrit && phase === "EMERGENCY") return "svg-pulse-red";
    if (isCrit && phase === "HOLD_VERIFICATION") return "svg-pulse-amber";
    return "";
  };

  const getZoneStroke = (zone: CadZoneId, isCrit: boolean) => {
    if (isCrit && phase === "EMERGENCY") return "#ff0000";
    if (isCrit && phase === "HOLD_VERIFICATION") return "#ffb000";
    if (selectedZone === zone) return "#00ff00";
    return "#1f7a3a";
  };

  const getZoneFill = (zone: CadZoneId, isCrit: boolean) => {
    if (isCrit && phase === "EMERGENCY") return "#440000";
    if (isCrit && phase === "HOLD_VERIFICATION") return "#332200";
    if (selectedZone === zone) return "#002b0d";
    return "#06150a";
  };

  return (
    <svg
      viewBox="0 0 560 540"
      className="block h-full w-full bg-black"
      data-testid="human-wireframe-svg"
    >
      {/* 1. CAD COORDINATE GRID & RETICLE LINES */}
      <g stroke="#121212" strokeWidth="1">
        {Array.from({ length: 14 }).map((_, i) => (
          <line key={`vx-${i}`} x1={i * 40} y1={0} x2={i * 40} y2={540} />
        ))}
        {Array.from({ length: 14 }).map((_, i) => (
          <line key={`hy-${i}`} x1={0} y1={i * 40} x2={560} y2={i * 40} />
        ))}
      </g>

      <line x1="280" y1="10" x2="280" y2="530" stroke="#242424" strokeWidth="1" strokeDasharray="4 4" />
      <line x1="20" y1="72" x2="540" y2="72" stroke="#1e1e1e" strokeWidth="1" />
      <line x1="20" y1="185" x2="540" y2="185" stroke="#1e1e1e" strokeWidth="1" />
      <line x1="20" y1="225" x2="540" y2="225" stroke="#1e1e1e" strokeWidth="1" />

      {/* CAD Frame Corner Brackets */}
      <path d="M 10 26 L 10 10 L 26 10" fill="none" stroke="#444444" strokeWidth="1.5" />
      <path d="M 534 10 L 550 10 L 550 26" fill="none" stroke="#444444" strokeWidth="1.5" />
      <path d="M 10 514 L 10 530 L 26 530" fill="none" stroke="#444444" strokeWidth="1.5" />
      <path d="M 534 530 L 550 530 L 550 514" fill="none" stroke="#444444" strokeWidth="1.5" />

      <text x="18" y="24" fill="#666666" fontSize="9" fontFamily="monospace">
        CAD // BIOMED-WIREFRAME REV 4.2 [ANTERIOR PROJECTION]
      </text>
      <text x="405" y="24" fill="#00ff00" fontSize="9" fontFamily="monospace">
        CLICK ZONE TO SYNC DRAWER
      </text>

      {/* 2. OUTER HUMAN BODY WIREFRAME CONTOUR */}
      <g fill="#030805" stroke="#245232" strokeWidth="1.5">
        <polygon points="248,112 312,112 348,130 362,162 342,272 332,332 228,332 218,272 198,162 212,130" />
        <polygon points="264,96 296,96 302,112 258,112" />
        <polygon points="348,130 374,142 394,218 408,292 390,298 372,226 346,168" />
        <polygon points="212,130 186,142 166,218 152,292 170,298 188,226 214,168" />
        <polygon points="284,332 332,332 324,428 318,512 292,512 292,428" />
        <polygon points="228,332 276,332 268,428 268,512 242,512 236,428" />
      </g>

      {/* Internal Skeletal & Vascular Reference Lines */}
      <g fill="none" stroke="#1b3b24" strokeWidth="1">
        <line x1="216" y1="134" x2="344" y2="134" />
        <line x1="230" y1="158" x2="330" y2="158" />
        <line x1="226" y1="182" x2="334" y2="182" />
        <line x1="228" y1="206" x2="332" y2="206" />
        <line x1="232" y1="230" x2="328" y2="230" />
        <line x1="280" y1="98" x2="280" y2="332" />
        <polygon points="236,304 324,304 312,330 248,330" />
        <polyline
          points="280,235 280,310 256,410 254,495"
          stroke={heartCritical ? "#ff0000" : "#1f4d2b"}
          strokeWidth={heartCritical ? "2" : "1"}
        />
        <polyline
          points="280,310 304,410 306,495"
          stroke={heartCritical ? "#ff0000" : "#1f4d2b"}
          strokeWidth={heartCritical ? "2" : "1"}
        />
      </g>

      {/* INTERACTIVE ZONE 1: HEAD // HEAD & CNS */}
      <g
        data-testid="svg-zone-head"
        onClick={() => onSelectZone("HEAD")}
        className="cursor-pointer"
      >
        <polyline
          points="280,52 185,52 155,52"
          fill="none"
          stroke={getZoneStroke("HEAD", headCritical)}
          strokeWidth="1.5"
        />
        <polygon
          points="262,32 298,32 312,48 310,76 296,96 264,96 250,76 248,48"
          fill={getZoneFill("HEAD", headCritical)}
          stroke={getZoneStroke("HEAD", headCritical)}
          strokeWidth={selectedZone === "HEAD" || headCritical ? "2.5" : "1.8"}
          className={getZoneClass("HEAD", headCritical)}
        />
        <polygon
          points="266,40 294,40 303,52 300,70 280,76 260,70 257,52"
          fill="none"
          stroke={getZoneStroke("HEAD", headCritical)}
          strokeWidth="1"
        />
        <line
          x1="280"
          y1="36"
          x2="280"
          y2="82"
          stroke={getZoneStroke("HEAD", headCritical)}
          strokeWidth="1"
        />
        <rect
          x="14"
          y="34"
          width="142"
          height="42"
          fill="#080808"
          stroke={getZoneStroke("HEAD", headCritical)}
          strokeWidth={selectedZone === "HEAD" || headCritical ? "2" : "1"}
        />
        <text x="20" y="48" fill={getZoneStroke("HEAD", headCritical)} fontSize="10" fontWeight="bold" fontFamily="monospace">
          [01] HEAD // NEURO
        </text>
        <text x="20" y="61" fill="#cccccc" fontSize="9.5" fontFamily="monospace">
          COG: {Math.round(telemetry.cogIndex)}% | rSO2: {telemetry.cnsO2Sat.toFixed(0)}%
        </text>
        <text x="20" y="72" fill="#888888" fontSize="9" fontFamily="monospace">
          CO2: {Math.round(telemetry.cabinCo2Ppm)} ppm
        </text>
      </g>

      {/* INTERACTIVE ZONE 2: LUNGS // LUNGS & RESPIRATION */}
      <g
        data-testid="svg-zone-lungs"
        onClick={() => onSelectZone("LUNGS")}
        className="cursor-pointer"
      >
        <polyline
          points="277,102 277,145 256,165"
          fill="none"
          stroke={getZoneStroke("LUNGS", lungsCritical)}
          strokeWidth="2"
        />
        <polyline
          points="283,102 283,145 304,165"
          fill="none"
          stroke={getZoneStroke("LUNGS", lungsCritical)}
          strokeWidth="2"
        />
        <polygon
          points="266,136 240,140 226,162 224,208 232,232 266,226 268,180"
          fill={getZoneFill("LUNGS", lungsCritical)}
          stroke={getZoneStroke("LUNGS", lungsCritical)}
          strokeWidth={selectedZone === "LUNGS" || lungsCritical ? "2.5" : "1.8"}
          className={getZoneClass("LUNGS", lungsCritical)}
        />
        <polygon
          points="294,136 320,140 334,162 336,208 328,232 298,226 302,196 292,180"
          fill={getZoneFill("LUNGS", lungsCritical)}
          stroke={getZoneStroke("LUNGS", lungsCritical)}
          strokeWidth={selectedZone === "LUNGS" || lungsCritical ? "2.5" : "1.8"}
          className={getZoneClass("LUNGS", lungsCritical)}
        />
        <polyline
          points="334,175 392,175 404,155"
          fill="none"
          stroke={getZoneStroke("LUNGS", lungsCritical)}
          strokeWidth="1.5"
        />
        <rect
          x="404"
          y="132"
          width="142"
          height="46"
          fill="#080808"
          stroke={getZoneStroke("LUNGS", lungsCritical)}
          strokeWidth={selectedZone === "LUNGS" || lungsCritical ? "2" : "1"}
        />
        <text x="410" y="146" fill={getZoneStroke("LUNGS", lungsCritical)} fontSize="10" fontWeight="bold" fontFamily="monospace">
          [02] LUNGS // RESP
        </text>
        <text
          x="410"
          y="160"
          fill={telemetry.spo2 < 85 ? "#ff0000" : "#cccccc"}
          fontSize="10"
          fontWeight="bold"
          fontFamily="monospace"
        >
          SpO2: {telemetry.spo2.toFixed(1)}% | RR:{Math.round(telemetry.respRate)}
        </text>
        <text x="410" y="172" fill="#888888" fontSize="9" fontFamily="monospace">
          PaO2: {Math.round(telemetry.pao2)} mmHg
        </text>
      </g>

      {/* INTERACTIVE ZONE 3: HEART // HEART & VASCULAR */}
      <g
        data-testid="svg-zone-heart"
        onClick={() => onSelectZone("HEART")}
        className="cursor-pointer"
      >
        <path
          d="M 276 176 L 276 154 L 292 154 L 292 176"
          fill="none"
          stroke={getZoneStroke("HEART", heartCritical)}
          strokeWidth="2"
        />
        <polygon
          points="272,174 298,174 306,194 294,222 272,222 264,198"
          fill={getZoneFill("HEART", heartCritical)}
          stroke={getZoneStroke("HEART", heartCritical)}
          strokeWidth={selectedZone === "HEART" || heartCritical ? "2.5" : "1.8"}
          className={getZoneClass("HEART", heartCritical)}
        />
        <polyline
          points="269,198 277,198 281,186 286,210 291,194 296,198 302,198"
          fill="none"
          stroke={heartCritical ? "#ffffff" : "#00ff00"}
          strokeWidth="1.4"
        />
        <polyline
          points="266,202 180,202 156,202"
          fill="none"
          stroke={getZoneStroke("HEART", heartCritical)}
          strokeWidth="1.5"
        />
        <rect
          x="14"
          y="180"
          width="142"
          height="46"
          fill="#080808"
          stroke={getZoneStroke("HEART", heartCritical)}
          strokeWidth={selectedZone === "HEART" || heartCritical ? "2" : "1"}
        />
        <text x="20" y="194" fill={getZoneStroke("HEART", heartCritical)} fontSize="10" fontWeight="bold" fontFamily="monospace">
          [03] HEART // CARDIO
        </text>
        <text
          x="20"
          y="208"
          fill={telemetry.hr > 130 ? "#ff0000" : "#cccccc"}
          fontSize="10"
          fontWeight="bold"
          fontFamily="monospace"
        >
          HR: {String(Math.round(telemetry.hr)).padStart(3, "0")} BPM
        </text>
        <text
          x="20"
          y="220"
          fill={telemetry.abpSys < 90 ? "#ff0000" : "#888888"}
          fontSize="9.5"
          fontFamily="monospace"
        >
          ABP: {Math.round(telemetry.abpSys)}/{Math.round(telemetry.abpDia)} mmHg
        </text>
      </g>

      {/* Bottom Legend inside SVG */}
      <rect x="14" y="492" width="240" height="32" fill="#080808" stroke="#333333" strokeWidth="1" />
      <text x="22" y="505" fill="#888888" fontSize="9" fontFamily="monospace">
        SELECTED ZONE:{" "}
        <tspan fill="#00ff00" fontWeight="bold">
          {selectedZone ?? "ALL SUBSYSTEMS"}
        </tspan>
      </text>
      <text x="22" y="518" fill="#666666" fontSize="9" fontFamily="monospace">
        STATUS: {phase === "NOMINAL" ? "ALL CONTOURS NOMINAL" : `ALERT // ${fault}`}
      </text>
    </svg>
  );
};

// ============================================================================
// HEV-1 METRIC CARD (FOR ALL INSTRUMENTED PARAMETERS FROM 1123)
// ============================================================================
function MetricCard({ p, emergency = false }: { p: ParameterState; emergency?: boolean }) {
  const alerts = useHevStore((s) => s.state?.alerts ?? []);
  const selectZone = useHevStore((s) => s.selectZone);
  const ok = p.status === "OK";
  const sev = paramSeverity(p, alerts);
  const dim = emergency && ok && sev === "NOMINAL";
  return (
    <button
      type="button"
      data-testid={`metric-${p.id}`}
      onClick={() => selectZone(p.zone)}
      className={`flex min-w-0 flex-col border border-l-2 bg-[#080808] px-2 py-1 text-left ${dim ? "hev-dimmed" : ""} ${
        !ok ? "border-[#ffb000]" : sev === "NOMINAL" ? "border-[#262626] border-l-[#00ff00]" : SEV_BORDER[sev]
      }`}
    >
      <div className="flex items-center gap-1">
        <span className="hmi-mono text-[10.5px] font-bold tracking-[0.08em] text-white">{p.short}</span>
        {ok ? <SourceBadge source={p.source} /> : <Chip className="border-[#ffb000] text-[#ffb000]">{STATUS_TEXT[p.status] ?? p.status}</Chip>}
        {p.limits_context && (
          <Chip className="border-[#00c8ff] text-[#00c8ff]">
            <span title={`Alarm limits: ${p.limits_context}`} data-testid={`ex-limits-${p.id}`}>EX LIMITS</span>
          </Chip>
        )}
        <span className="flex-1" />
        {ok && <span className={`hmi-mono text-[9.5px] font-bold ${sev === "NOMINAL" ? "text-[#00ff00]" : SEV_TEXT[sev]}`}>{sev}</span>}
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`hmi-mono text-[18px] font-bold leading-tight ${!ok ? "text-[#ffb000]" : sev === "NOMINAL" ? "text-[#00ff00]" : SEV_TEXT[sev]} ${sev === "WARNING" && ok ? "hev-flash" : ""}`}>
          {ok ? fmtValue(p.value) : "----"}
        </span>
        <span className="hmi-mono text-[10px] text-[#888888]">{ok ? unitLabel(p.unit) : p.value !== null ? `last ${fmtValue(p.value)}` : ""}</span>
      </div>
      <span className="truncate text-[9.5px] text-[#777777]">{p.label}</span>
    </button>
  );
}

// ============================================================================
// MAIN COMMAND SCREEN (R.I.D.G.E. HMI + HEV-1 1123 CORE)
// ============================================================================
export function ActionCentricHud() {
  const now = useNow(1000);
  const state = useHevStore((s) => s.state);
  const protocols = useHevStore((s) => s.protocols);
  const selectedAlertId = useHevStore((s) => s.selectedAlertId);
  const selectAlert = useHevStore((s) => s.selectAlert);
  const selectHevZone = useHevStore((s) => s.selectZone);
  const viewCrew = useHevStore((s) => s.viewCrewId);
  const setViewCrew = useHevStore((s) => s.setViewCrew);
  const setModal = useHevStore((s) => s.setModal);
  const setNotice = useHevStore((s) => s.setNotice);
  const setAudioArmed = useHevStore((s) => s.setAudioArmed);
  const setScreen = useHevStore((s) => s.setScreen);
  const selectSession = useHevStore((s) => s.selectSession);
  const setFitnessTab = useHevStore((s) => s.setFitnessTab);

  const [activeCrew, setActiveCrew] = useState<CrewKey>("SMITH");
  const [selectedZone, setSelectedZone] = useState<CadZoneId | null>(null);
  const [twinMode, setTwinMode] = useState<"CAD" | "ANATOMICAL">("CAD");
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);
  const [showTwinInEmergency, setShowTwinInEmergency] = useState<boolean>(false);
  const [clearArmed, setClearArmed] = useState<boolean>(false);

  const [crewStates, setCrewStates] = useState<Record<CrewKey, CrewRuntimeState>>(() => ({
    SMITH: {
      fault: "NOMINAL",
      phase: "NOMINAL",
      holdSeconds: HOLD_TOTAL_S,
      elapsedSeconds: 0,
      acked: false,
      stepsDone: [false, false, false, false],
      telemetry: { ...CREW_PROFILES.SMITH.base },
    },
    DOE: {
      fault: "NOMINAL",
      phase: "NOMINAL",
      holdSeconds: HOLD_TOTAL_S,
      elapsedSeconds: 0,
      acked: false,
      stepsDone: [false, false, false, false],
      telemetry: { ...CREW_PROFILES.DOE.base },
    },
  }));

  const rowRefs = useRef<Record<string, HTMLTableRowElement | null>>({});

  // Sync backend scenario / alerts with the deterministic CAD runtime when CM-1 is active
  const backendScenario = state?.mode.scenario ?? "nominal";
  const backendAlerts: Alert[] = state?.alerts ?? [];
  const focusBackendAlert: Alert | null =
    backendAlerts.find((x) => x.id === selectedAlertId) ?? backendAlerts[0] ?? null;

  useEffect(() => {
    if (!clearArmed) return;
    const t = setTimeout(() => setClearArmed(false), 4000);
    return () => clearTimeout(t);
  }, [clearArmed]);

  // Sync backend scenario transitions into SMITH's runtime state
  useEffect(() => {
    const mapped = SCENARIO_TO_FAULT[backendScenario] ?? "NOMINAL";
    setCrewStates((prev) => {
      const st = prev.SMITH;
      if (mapped !== "NOMINAL" && st.fault !== mapped) {
        return {
          ...prev,
          SMITH: {
            ...st,
            fault: mapped,
            phase: "EMERGENCY",
            holdSeconds: HOLD_TOTAL_S,
            elapsedSeconds: 0,
            acked: false,
            stepsDone: [false, false, false, false],
          },
        };
      }
      if (mapped === "NOMINAL" && st.phase === "EMERGENCY") {
        return {
          ...prev,
          SMITH: {
            ...st,
            phase: "HOLD_VERIFICATION",
            holdSeconds: HOLD_TOTAL_S,
          },
        };
      }
      return prev;
    });
  }, [backendScenario]);

  // 10Hz Deterministic Telemetry & Hold Timer Loop + Backend Telemetry Blending
  useEffect(() => {
    const timer = setInterval(() => {
      const liveState = useHevStore.getState().state;
      const getParamVal = (id: string): number | null => {
        const p = liveState?.parameters.find((x) => x.id === id);
        return p && p.status === "OK" && typeof p.value === "number" ? p.value : null;
      };

      setCrewStates((prev) => {
        const next: Record<CrewKey, CrewRuntimeState> = { ...prev };

        (["SMITH", "DOE"] as CrewKey[]).forEach((cid) => {
          const st = { ...next[cid] };
          const base = CREW_PROFILES[cid].base;
          const t = { ...st.telemetry };
          const noise = (amp: number) => (Math.random() - 0.5) * 2 * amp;

          let tgtHr = base.hr;
          let tgtSys = base.abpSys;
          let tgtDia = base.abpDia;
          let tgtCo = base.cardiacOutput;
          let tgtLac = base.lactate;

          let tgtSpo2 = base.spo2;
          let tgtPao2 = base.pao2;
          let tgtRr = base.respRate;
          let tgtEtco2 = base.etCo2;
          let tgtSuitO2 = base.suitO2Kpa;

          let tgtCog = base.cogIndex;
          let tgtCnsO2 = base.cnsO2Sat;
          let tgtPvt = base.pvtRt;
          let tgtCabinCo2 = base.cabinCo2Ppm;
          let tgtDose = base.doseRateUgy;

          // If SMITH (CM-1) and backend is online in nominal/exercise, blend real backend values
          if (cid === "SMITH" && st.phase === "NOMINAL") {
            const bHr = getParamVal("heart_rate");
            const bSpo2 = getParamVal("spo2");
            const bSys = getParamVal("bp_systolic");
            const bRr = getParamVal("resp_rate");
            const bPvt = getParamVal("pvt_mean_rt");
            const bCo2 = getParamVal("cabin_co2");
            const bO2 = getParamVal("cabin_o2");
            const bDose = getParamVal("dose_rate");
            if (bHr !== null) tgtHr = bHr;
            if (bSpo2 !== null) tgtSpo2 = bSpo2;
            if (bSys !== null) tgtSys = bSys;
            if (bRr !== null) tgtRr = bRr;
            if (bPvt !== null) tgtPvt = bPvt;
            if (bCo2 !== null) tgtCabinCo2 = Math.round(bCo2 * 1315); // mmHg to ppm approx
            if (bO2 !== null) tgtSuitO2 = bO2;
            if (bDose !== null) tgtDose = bDose;
          }

          if (st.phase === "EMERGENCY") {
            st.elapsedSeconds = Number((st.elapsedSeconds + 0.1).toFixed(1));

            if (st.fault === "HYPOXIA") {
              tgtSpo2 = 78.2;
              tgtPao2 = 46;
              tgtSuitO2 = 13.4;
              tgtRr = 26;
              tgtEtco2 = 30;
              tgtHr = 114;
              tgtCnsO2 = 54.0;
              tgtCog = 76;
              tgtPvt = 360;
              tgtLac = 2.8;
            } else if (st.fault === "HEMORRHAGE") {
              tgtSys = 72;
              tgtDia = 44;
              tgtHr = 142;
              tgtCo = 2.9;
              tgtLac = 5.2;
              tgtSpo2 = 91.5;
              tgtRr = 24;
              tgtCnsO2 = 58.5;
              tgtCog = 78;
              tgtPvt = 340;
            } else if (st.fault === "CO2_SPIKE") {
              tgtCabinCo2 = 7180;
              tgtEtco2 = 57;
              tgtCog = 58;
              tgtPvt = 455;
              tgtCnsO2 = 61.0;
              tgtRr = 25;
              tgtHr = 104;
            } else if (st.fault === "SOLAR_FLARE") {
              tgtDose = 340.0;
              tgtHr = 98;
              tgtPvt = 310;
              tgtCog = 86;
            } else if (st.fault === "TACHYCARDIA") {
              tgtHr = 144;
              tgtSys = 128;
              tgtDia = 84;
              tgtRr = 22;
            }
          } else if (st.phase === "HOLD_VERIFICATION") {
            st.elapsedSeconds = Number((st.elapsedSeconds + 0.1).toFixed(1));
            const rem = Number(Math.max(0, st.holdSeconds - 0.1).toFixed(1));
            st.holdSeconds = rem;
            if (rem <= 0) {
              st.phase = "NOMINAL";
              st.fault = "NOMINAL";
              st.holdSeconds = HOLD_TOTAL_S;
              st.elapsedSeconds = 0;
              st.acked = false;
              st.stepsDone = [false, false, false, false];
            }
          }

          const alpha = st.phase === "HOLD_VERIFICATION" ? 0.12 : 0.08;

          t.hr = Number((t.hr + (tgtHr - t.hr) * alpha + noise(0.2)).toFixed(0));
          t.abpSys = Number((t.abpSys + (tgtSys - t.abpSys) * alpha + noise(0.2)).toFixed(0));
          t.abpDia = Number((t.abpDia + (tgtDia - t.abpDia) * alpha + noise(0.15)).toFixed(0));
          t.abpMap = Math.round(t.abpDia + (t.abpSys - t.abpDia) / 3);
          t.shockIndex = Number((t.hr / Math.max(40, t.abpSys)).toFixed(2));
          t.cardiacOutput = Number((t.cardiacOutput + (tgtCo - t.cardiacOutput) * alpha).toFixed(1));
          t.lactate = Number((t.lactate + (tgtLac - t.lactate) * alpha).toFixed(1));

          t.spo2 = Number(Math.min(100, Math.max(60, t.spo2 + (tgtSpo2 - t.spo2) * alpha + noise(0.05))).toFixed(1));
          t.pao2 = Number((t.pao2 + (tgtPao2 - t.pao2) * alpha + noise(0.2)).toFixed(0));
          t.respRate = Number((t.respRate + (tgtRr - t.respRate) * alpha).toFixed(0));
          t.etCo2 = Number((t.etCo2 + (tgtEtco2 - t.etCo2) * alpha).toFixed(0));
          t.suitO2Kpa = Number((t.suitO2Kpa + (tgtSuitO2 - t.suitO2Kpa) * alpha).toFixed(1));

          t.cogIndex = Number((t.cogIndex + (tgtCog - t.cogIndex) * alpha).toFixed(0));
          t.cnsO2Sat = Number((t.cnsO2Sat + (tgtCnsO2 - t.cnsO2Sat) * alpha).toFixed(1));
          t.pvtRt = Number((t.pvtRt + (tgtPvt - t.pvtRt) * alpha).toFixed(0));
          t.cabinCo2Ppm = Math.round(t.cabinCo2Ppm + (tgtCabinCo2 - t.cabinCo2Ppm) * alpha + noise(2));
          t.doseRateUgy = Number(Math.max(5, t.doseRateUgy + (tgtDose - t.doseRateUgy) * alpha + noise(0.3)).toFixed(1));

          st.telemetry = t;
          next[cid] = st;
        });

        return next;
      });
    }, 100);

    return () => clearInterval(timer);
  }, []);

  const curState = crewStates[activeCrew];
  const { fault, phase, holdSeconds, elapsedSeconds, acked, stepsDone, telemetry: tel } = curState;

  // Determine if we are in an Emergency / Recovery state (either via local CAD trigger or backend Alert)
  const hasBackendCriticalAlert =
    focusBackendAlert && (focusBackendAlert.severity === "WARNING" || focusBackendAlert.severity === "CAUTION");
  const backendAlertFault: FaultMode =
    focusBackendAlert?.kind === "SENSOR_FAULT" || focusBackendAlert?.kind === "DATA_STALE"
      ? "SENSOR_FAILURE"
      : focusBackendAlert?.parameter === "cabin_co2"
      ? "CO2_SPIKE"
      : focusBackendAlert?.parameter === "bp_systolic"
      ? "HEMORRHAGE"
      : focusBackendAlert?.parameter === "heart_rate"
      ? "TACHYCARDIA"
      : focusBackendAlert?.parameter === "dose_rate"
      ? "SOLAR_FLARE"
      : "HYPOXIA";
  const scenarioFault = SCENARIO_TO_FAULT[backendScenario] ?? "NOMINAL";
  const effectiveFault: FaultMode =
    fault !== "NOMINAL"
      ? fault
      : hasBackendCriticalAlert
      ? scenarioFault !== "NOMINAL"
        ? scenarioFault
        : backendAlertFault
      : "NOMINAL";
  const effectivePhase: SystemPhase =
    phase !== "NOMINAL"
      ? phase
      : focusBackendAlert?.lifecycle === "RECOVERY"
      ? "HOLD_VERIFICATION"
      : hasBackendCriticalAlert
      ? "EMERGENCY"
      : "NOMINAL";

  const activeProto = effectiveFault !== "NOMINAL" ? EMERGENCY_PROTOCOLS[effectiveFault] : null;
  const backendProto = focusBackendAlert?.protocol_id ? protocols[focusBackendAlert.protocol_id] : undefined;

  const armAudio = () => {
    audio.arm();
    setAudioArmed(true);
  };

  const runApi = (p: Promise<unknown>, msg: string) =>
    p.then(() => setNotice(msg)).catch((e: Error) => setNotice(e.message || "Command failed"));

  const handleSelectZone = (zone: CadZoneId) => {
    setSelectedZone(zone);
    const mapHev: Record<CadZoneId, HevZoneId> = {
      HEAD: "head",
      LUNGS: "respiratory",
      HEART: "cardiovascular",
    };
    selectHevZone(mapHev[zone]);
    setIsDrawerOpen(true);
    setTimeout(() => {
      const firstRow = TELEMETRY_TABLE_ROWS.find((r) => r.zone === zone);
      if (firstRow && rowRefs.current[firstRow.id]) {
        rowRefs.current[firstRow.id]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }, 60);
  };

  const handleTriggerFault = (mode: Exclude<FaultMode, "NOMINAL">, backendId: string, label: string) => {
    armAudio();
    const proto = EMERGENCY_PROTOCOLS[mode];
    setShowTwinInEmergency(false);
    setCrewStates((prev) => ({
      ...prev,
      [activeCrew]: {
        ...prev[activeCrew],
        fault: mode,
        phase: "EMERGENCY",
        holdSeconds: HOLD_TOTAL_S,
        elapsedSeconds: 0,
        acked: false,
        stepsDone: [false, false, false, false],
      },
    }));
    setSelectedZone(proto.faultZone);
    selectHevZone(proto.hevZone);
    setIsDrawerOpen(true);
    void runApi(api.scenario(backendId), `Scenario ${label} activated (simulated data through the normal rules engine)`);
  };

  const handleRecover = () => {
    armAudio();
    setCrewStates((prev) => ({
      ...prev,
      [activeCrew]: {
        ...prev[activeCrew],
        phase: prev[activeCrew].phase === "NOMINAL" ? "NOMINAL" : "HOLD_VERIFICATION",
        holdSeconds: HOLD_TOTAL_S,
        acked: true,
        stepsDone: [true, true, true, true],
      },
    }));
    void runApi(api.scenario("nominal"), "Scenario NOMINAL activated — verifying 30s recovery hold time");
  };

  const handleToggleStep = (index: number) => {
    setCrewStates((prev) => {
      const st = prev[activeCrew];
      const nextSteps = [...st.stepsDone];
      nextSteps[index] = !nextSteps[index];
      return {
        ...prev,
        [activeCrew]: { ...st, stepsDone: nextSteps },
      };
    });
    if (focusBackendAlert) {
      void alertActions.confirmStep(focusBackendAlert.id, index);
    }
  };

  const handleFastForwardHold = () => {
    setCrewStates((prev) => {
      const st = prev[activeCrew];
      const nextHold = Number(Math.max(0, st.holdSeconds - 10.0).toFixed(1));
      if (nextHold <= 0) {
        return {
          ...prev,
          [activeCrew]: {
            ...st,
            phase: "NOMINAL",
            fault: "NOMINAL",
            holdSeconds: HOLD_TOTAL_S,
            elapsedSeconds: 0,
            acked: false,
            stepsDone: [false, false, false, false],
          },
        };
      }
      return {
        ...prev,
        [activeCrew]: { ...st, holdSeconds: nextHold },
      };
    });
  };

  // Readiness, CFMS, and Vitals from HEV-1 state
  const readiness = state?.readiness;
  const eva = readiness ? EVA_TEXT[readiness.eva.status] : { text: "NO BLOCKERS FOUND", sev: "NOMINAL" as SeverityName };
  const triage = readiness?.triage;
  const fitness = state?.fitness;
  const cfmsEnabled = !!fitness?.enabled;
  const monitoredCrewId = state?.mission.monitored_crew_id ?? "CM-1";
  const shownCrewId = viewCrew ?? monitoredCrewId;
  const isUnmonitoredCrew = shownCrewId !== monitoredCrewId;

  const counts = { WARNING: 0, CAUTION: 0, ADVISORY: 0 };
  backendAlerts.forEach((a) => (counts[a.severity] += 1));

  // CFMS summary card data
  const nextEx = fitness?.next_by_crew?.find((n) => n.monitored)?.session ?? null;
  const liveEx = fitness?.in_progress?.[0] ?? null;
  const recEx = fitness?.recovery?.find((r) => r.crew_id === monitoredCrewId && !r.final) ?? null;
  const targetSession = liveEx ?? nextEx;

  // Backend hold calculation if backend alert is in RECOVERY
  const backendHeldS =
    focusBackendAlert?.lifecycle === "RECOVERY"
      ? Math.min(focusBackendAlert.recovery_hold_s, ageFrom(focusBackendAlert.recovery_since, now) ?? 0)
      : 0;
  const displayHoldRemaining =
    phase === "HOLD_VERIFICATION"
      ? holdSeconds
      : focusBackendAlert?.lifecycle === "RECOVERY"
      ? Math.max(0, focusBackendAlert.recovery_hold_s - backendHeldS)
      : HOLD_TOTAL_S;

  const isEmergencyLayout = effectivePhase !== "NOMINAL" && !!activeProto && !showTwinInEmergency;

  // All 14 backend parameters for the HEV-1 Core Strip
  const allParams = state?.parameters ?? [];
  const donkiCtx = state?.space_weather_simulation ?? state?.nasa_donki;

  return (
    <div
      data-testid="screen-command-view"
      className="flex min-h-0 flex-1 flex-col bg-black text-[#e6e6e6] overflow-hidden select-none"
    >
      {/* =====================================================================
          1. TOP DECISION-SUPPORT STRIP (HEV-1 CORE CARDS IN R.I.D.G.E. HMI STYLE)
         ===================================================================== */}
      <div
        className={`grid shrink-0 border-b border-[#333333] bg-black ${
          cfmsEnabled ? "grid-cols-4" : "grid-cols-3"
        }`}
      >
        {/* CARD 1: MISSION STATUS */}
        <section
          data-testid="hud-mission-status"
          className={`flex flex-col justify-between border-r border-[#333333] border-l-4 px-3.5 py-2 ${
            effectivePhase === "NOMINAL"
              ? "border-l-[#00ff00] bg-[#050505]"
              : effectivePhase === "EMERGENCY"
              ? "border-l-[#ff0000] bg-[#140000]"
              : "border-l-[#ffb000] bg-[#140e00]"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="hmi-mono text-[10px] font-bold uppercase tracking-[0.12em] text-[#888888]">
              01 // MISSION STATUS · {shownCrewId}
            </span>
            <Chip className="border-[#ffb000] bg-[#1a1100] text-[#ffb000]">
              SIM · {effectiveFault === "NOMINAL" ? "NOMINAL" : effectiveFault}
            </Chip>
          </div>
          <div
            className={`mt-0.5 truncate hmi-mono text-[17px] font-black tracking-[0.08em] ${
              effectivePhase === "NOMINAL"
                ? "text-[#00ff00]"
                : effectivePhase === "EMERGENCY"
                ? "text-[#ff0000]"
                : "text-[#ffb000]"
            }`}
          >
            {effectivePhase === "NOMINAL"
              ? "NOMINAL // ALL CONTOURS STABLE"
              : `ACTION REQUIRED · ${effectiveFault}`}
          </div>
          <div className="mt-0.5 truncate hmi-mono text-[10.5px] text-[#aaaaaa]">
            {focusBackendAlert
              ? focusBackendAlert.title
              : "All monitored parameters inside configured demonstration ranges"}{" "}
            · {counts.WARNING}W {counts.CAUTION}C {counts.ADVISORY}A
          </div>
        </section>

        {/* CARD 2: R.I.D.G.E. FOCUS & CORRELATION */}
        <section
          data-testid="hud-triage"
          className={`flex flex-col justify-between border-r border-[#333333] border-l-4 px-3.5 py-2 ${
            !triage || triage.severity === "NOMINAL"
              ? "border-l-[#00ff00] bg-[#050505]"
              : triage.severity === "WARNING"
              ? "border-l-[#ff0000] bg-[#140000]"
              : "border-l-[#ffb000] bg-[#140e00]"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="hmi-mono text-[10px] font-bold uppercase tracking-[0.12em] text-[#888888]">
              02 // R.I.D.G.E. CORRELATION FOCUS
            </span>
            {triage?.alert_id && triage?.protocol_id && (
              <button
                type="button"
                data-testid="hud-open-checklist"
                onClick={() => {
                  selectAlert(triage.alert_id);
                  setShowTwinInEmergency(false);
                }}
                className="border border-[#00c8ff] bg-[#001824] px-2 py-0.5 hmi-mono text-[9.5px] font-bold text-[#00c8ff] hover:bg-[#00c8ff] hover:text-black"
              >
                OPEN {triage.protocol_id}
                {triage.kit && triage.kit !== "NONE" ? ` · ${triage.kit}` : ""}
              </button>
            )}
          </div>
          <div
            className={`mt-0.5 truncate hmi-mono text-[16px] font-black tracking-[0.06em] ${
              !triage || triage.severity === "NOMINAL" ? "text-[#00ff00]" : SEV_TEXT[triage.severity]
            }`}
          >
            {(triage?.title ?? "NOMINAL AUTONOMOUS LOOP").toUpperCase()}
          </div>
          <div className="truncate hmi-mono text-[10.5px] text-[#cccccc]" title={triage?.rationale}>
            {triage?.context?.length
              ? `Correlated: ${triage.context.join(" · ")}`
              : triage?.rationale ?? "Correlation engine evaluating human, cabin & DONKI feeds"}
          </div>
        </section>

        {/* CARD 3: EVA READINESS (4 GATES) */}
        <section
          data-testid="hud-eva"
          className={`flex flex-col justify-between border-r border-[#333333] border-l-4 px-3.5 py-2 ${
            eva.sev === "NOMINAL"
              ? "border-l-[#00ff00] bg-[#050505]"
              : eva.sev === "WARNING"
              ? "border-l-[#ff0000] bg-[#140000]"
              : "border-l-[#ffb000] bg-[#140e00]"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="hmi-mono text-[10px] font-bold uppercase tracking-[0.12em] text-[#888888]">
              03 // EVA READINESS · DECISION SUPPORT
            </span>
            <span className="hmi-mono text-[10.5px] font-bold text-[#00ff00]">
              {readiness ? `${readiness.eva.gates_clear}/${readiness.eva.gates_total} GATES CLEAR` : "4/4 GATES CLEAR"}
            </span>
          </div>
          <div
            className={`mt-0.5 truncate hmi-mono text-[16px] font-black tracking-[0.08em] ${
              eva.sev === "NOMINAL" ? "text-[#00ff00]" : SEV_TEXT[eva.sev]
            }`}
          >
            {eva.text}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-1">
            {(readiness?.eva.gates ?? []).map((g) => (
              <Chip key={g.id} className={GATE_STYLE[g.status]}>
                <span title={g.reasons.join("; ") || "clear"}>
                  {g.label} · {g.status}
                </span>
              </Chip>
            ))}
          </div>
        </section>

        {/* CARD 4: CFMS NEXT EXERCISE / IN-SESSION MONITOR */}
        {cfmsEnabled && (
          <section
            data-testid="hud-next-exercise"
            className="flex flex-col justify-between border-l-4 border-l-[#00c8ff] bg-[#050505] px-3.5 py-2"
          >
            <button
              type="button"
              onClick={() => {
                if (targetSession) selectSession(targetSession.id);
                setFitnessTab("schedule");
                setScreen("fitness");
              }}
              className="text-left"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="hmi-mono text-[10px] font-bold uppercase tracking-[0.12em] text-[#888888]">
                  04 // {liveEx ? "IN SESSION · CFMS" : "NEXT EXERCISE · CFMS"}
                </span>
                <Chip className="border-[#00c8ff] bg-[#001824] text-[#00c8ff]">OPEN [3]</Chip>
              </div>
              <div className="mt-0.5 truncate hmi-mono text-[16px] font-black tracking-[0.06em] text-[#00c8ff]">
                {targetSession ? `${targetSession.crew_id} ${targetSession.exercise_type}` : "NO SESSION"}
              </div>
              <div className="mt-0.5 truncate hmi-mono text-[10.5px] text-[#cccccc]">
                {liveEx && liveEx.profile
                  ? `HR ${liveEx.profile.heart_rate?.value?.toFixed(0) ?? "--"} bpm · ${liveEx.profile.overall.replace(/_/g, " ")}`
                  : recEx
                  ? `Recovery ${recEx.status.replace(/_/g, " ")} · ${Math.round(recEx.elapsed_s)}s`
                  : targetSession
                  ? `${targetSession.planned_start_met ?? "--"} · ${targetSession.device_id ?? "--"} · ${targetSession.gate?.status.replace(/_/g, " ") ?? "--"}`
                  : "Press [3] for Crew Fitness Management"}
              </div>
            </button>
          </section>
        )}
      </div>

      {/* =====================================================================
          2. CENTRAL WORKSPACE:
             [LEFT: INTERACTIVE CAD HUMAN SVG / ANATOMICAL TWIN]
             [CENTER: EMERGENCY ACTION PANEL OR NOMINAL SUBSYSTEM + HEV-1 CARDS]
             [RIGHT: DOCKED Debug SYS_CTRL]
         ===================================================================== */}
      <div className="grid min-h-0 flex-1 grid-cols-[1fr_290px] border-b border-[#333333]">
        <div className="grid min-h-0 grid-cols-[520px_1fr] bg-black">
          {/* COLUMN 1: INTERACTIVE HUMAN WIREFRAME SVG / ANATOMICAL TWIN */}
          <div data-testid="hud-twin" className="flex min-h-0 flex-col border-r border-[#333333] bg-black">
            <div className="flex items-center justify-between border-b border-[#333333] bg-[#0a0a0a] px-2.5 py-1.5">
              <div className="flex items-center gap-1.5">
                <span className="hmi-sans text-[10.5px] font-bold tracking-[0.08em] text-white">
                  BIOMEDICAL TWIN
                </span>
                <button
                  type="button"
                  onClick={() => setTwinMode((m) => (m === "CAD" ? "ANATOMICAL" : "CAD"))}
                  className="border border-[#00c8ff] bg-[#001824] px-1.5 py-0.5 hmi-mono text-[9px] font-bold text-[#00c8ff] hover:bg-[#00c8ff] hover:text-black"
                  title="Switch between CAD Wireframe and Full 6-Zone Anatomical Twin"
                >
                  {twinMode === "CAD" ? "VIEW: CAD WIREFRAME" : "VIEW: 6-ZONE ANATOMY"}
                </button>
              </div>
              <div className="flex items-center gap-1 hmi-mono text-[9.5px]">
                {(["HEAD", "LUNGS", "HEART"] as CadZoneId[]).map((z) => (
                  <button
                    key={z}
                    type="button"
                    onClick={() => handleSelectZone(z)}
                    className={`border px-2 py-0.5 font-bold ${
                      selectedZone === z
                        ? "border-[#00ff00] bg-[#002b0d] text-[#00ff00]"
                        : "border-[#333333] bg-[#111111] text-[#999999] hover:border-[#666666]"
                    }`}
                  >
                    {z}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 bg-black">
              {twinMode === "CAD" ? (
                <HumanWireframeSvg
                  selectedZone={selectedZone}
                  onSelectZone={handleSelectZone}
                  fault={effectiveFault}
                  phase={effectivePhase}
                  telemetry={tel}
                />
              ) : (
                state && (
                  <HumanTwin
                    alerts={state.alerts}
                    params={state.parameters}
                    selected={state.alerts[0]?.zone ?? "cardiovascular"}
                    onSelect={(z) => selectHevZone(z)}
                  />
                )
              )}
            </div>
          </div>

          {/* COLUMN 2: EMERGENCY ACTION PANEL OR NOMINAL ZONE MATRIX + HEV-1 PARAMETERS */}
          <div className="flex min-h-0 flex-col bg-black overflow-y-auto hev-scroll">
            {isEmergencyLayout && activeProto ? (
              /* ===============================================================
                 EMERGENCY ACTION PANEL
                 =============================================================== */
              <div
                data-testid="emergency-panel"
                className={`flex h-full flex-col justify-between border-4 ${
                  effectivePhase === "EMERGENCY"
                    ? "border-[#ff0000] bg-[#140000]"
                    : "border-[#ffb000] bg-[#140e00]"
                }`}
              >
                <div data-testid="emergency-band">
                  {/* MASSIVE HIGH-CONTRAST HEADER */}
                  <div
                    className={`flex items-center justify-between border-b-2 border-black px-4 py-2 ${
                      effectivePhase === "EMERGENCY" ? "bg-[#ff0000] text-black" : "bg-[#ffb000] text-black"
                    }`}
                  >
                    <div className="min-w-0 flex-1 pr-3">
                      <div className="flex items-center gap-2 hmi-mono text-[10.5px] font-black tracking-[0.12em]">
                        <span>
                          {effectivePhase === "EMERGENCY"
                            ? "MASTER WARNING // EMERGENCY ACTION DIRECTIVE // IMMEDIATE INTERVENTION"
                            : "MASTER CAUTION // RECOVERY VERIFICATION // HOLD TIME 30.0s ACTIVE"}
                        </span>
                        {focusBackendAlert && (
                          <span>
                            · {focusBackendAlert.rule_id} · {focusBackendAlert.lifecycle}
                            {focusBackendAlert.acknowledged || acked ? " · ACK" : " · UNACKED"}
                          </span>
                        )}
                      </div>
                      <div
                        data-testid="emergency-title"
                        className="truncate hmi-sans text-[18px] font-black tracking-[0.02em] leading-tight"
                      >
                        {focusBackendAlert ? `${focusBackendAlert.title.toUpperCase()} — ${activeProto.title}` : activeProto.title}
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-1.5">
                      <button
                        type="button"
                        data-testid="ack-btn"
                        onClick={() => {
                          setCrewStates((prev) => ({
                            ...prev,
                            [activeCrew]: { ...prev[activeCrew], acked: true },
                          }));
                          if (focusBackendAlert) void alertActions.ack(focusBackendAlert.id);
                          else audio.stop();
                        }}
                        className="border-2 border-black bg-black px-2.5 py-1 hmi-mono text-[11px] font-black text-[#00ff00] hover:bg-[#1a1a1a]"
                      >
                        ACK
                      </button>
                      <button
                        type="button"
                        data-testid="silence-btn"
                        onClick={() => {
                          audio.stop();
                          if (focusBackendAlert) void alertActions.silence(focusBackendAlert.id);
                        }}
                        className="border-2 border-black bg-black px-2.5 py-1 hmi-mono text-[11px] font-black text-[#00c8ff] hover:bg-[#1a1a1a]"
                      >
                        SILENCE
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setTwinMode((m) => (m === "ANATOMICAL" ? "CAD" : "ANATOMICAL"));
                        }}
                        className="border-2 border-black bg-black px-2.5 py-1 hmi-mono text-[11px] font-black text-white hover:bg-[#1a1a1a]"
                      >
                        SHOW TWIN
                      </button>
                      <span className="bg-black px-2.5 py-1 hmi-mono text-[11px] font-black text-white">
                        ZONE: {activeProto.faultZone} // T+{elapsedSeconds.toFixed(1)}s
                      </span>
                    </div>
                  </div>

                  {/* ACTIVE BACKEND ALERTS SWITCHER (IF MULTIPLE ALERTS) */}
                  {backendAlerts.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5 border-b border-[#333333] bg-[#0a0a0a] px-4 py-1.5">
                      <span className="hmi-mono text-[9.5px] font-bold text-[#888888]">ACTIVE ALERTS ({backendAlerts.length}):</span>
                      {backendAlerts.map((a) => (
                        <button
                          key={a.id}
                          type="button"
                          data-testid={`alert-${a.rule_id}`}
                          onClick={() => selectAlert(a.id)}
                          className={`border px-2 py-0.5 hmi-mono text-[10px] font-bold ${
                            focusBackendAlert?.id === a.id
                              ? "border-white bg-[#260000] text-white"
                              : "border-[#444444] bg-black text-[#aaaaaa] hover:text-white"
                          }`}
                        >
                          {a.severity} · {a.title} ({a.lifecycle})
                        </button>
                      ))}
                    </div>
                  )}

                  {/* BLOCK 1: ROOT CAUSE & R.I.D.G.E. CORRELATION */}
                  <div className="border-b border-[#333333] bg-black px-4 py-2">
                    <div className="hmi-mono text-[10px] font-bold tracking-[0.1em] text-[#ff0000]">
                      01 // ROOT CAUSE & R.I.D.G.E. CORRELATION:
                    </div>
                    <div className="mt-0.5 hmi-mono text-[12.5px] font-bold text-white">
                      {activeProto.rootCause}
                    </div>
                    {focusBackendAlert && (
                      <div className="mt-0.5 hmi-mono text-[11px] text-[#ffb000]">
                        HEV-1 CORE: {triage?.context?.length ? `Correlated: ${triage.context.join(" · ")}` : focusBackendAlert.message}
                      </div>
                    )}
                  </div>

                  {/* BLOCK 2: REQUIRED MEDICAL KIT */}
                  <div
                    className={`border-b-2 border-black px-4 py-2 ${
                      effectivePhase === "EMERGENCY" ? "bg-[#ff0000] text-black" : "bg-[#ffb000] text-black"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span data-testid="emergency-kit" className="hmi-mono text-[11px] font-black tracking-[0.1em]">
                        02 // REQUIRED KIT: <span data-testid="cm-kit">{backendProto?.kit ?? activeProto.kitCode}</span>
                      </span>
                      <span className="bg-black px-2 py-0.5 hmi-mono text-[10px] font-bold text-[#ffb000]">
                        {activeProto.kitLocation}
                      </span>
                    </div>
                    <div className="mt-0.5 hmi-mono text-[14px] font-black">
                      {activeProto.kitCode} — {activeProto.kitName}
                    </div>
                    {backendProto?.kit_contents?.length ? (
                      <div className="hmi-mono text-[11px] font-bold">
                        CONTENTS: {backendProto.kit_contents.join(" · ")}
                      </div>
                    ) : null}
                  </div>

                  {/* BLOCK 3: MANDATORY CHECKLIST STEPS */}
                  <div className="border-b border-[#333333] bg-black px-4 py-2">
                    <div className="mb-1.5 flex items-center justify-between">
                      <span className="hmi-mono text-[10px] font-bold tracking-[0.1em] text-[#cccccc]">
                        03 // ACTION PROTOCOL (CLICK TO CONFIRM · SYNCED WITH HEV-1):
                      </span>
                      <span className="hmi-mono text-[10px] font-bold text-[#00ff00]">
                        CONFIRMED: {stepsDone.filter(Boolean).length}/{activeProto.instructions.length}
                      </span>
                    </div>
                    <div className="grid grid-cols-1 gap-1.5">
                      {(backendProto?.steps ?? activeProto.instructions).map((inst, idx) => {
                        const done = stepsDone[idx] || (focusBackendAlert?.cm_steps_done ?? []).includes(idx);
                        const ruHint = activeProto.instructions[idx];
                        return (
                          <button
                            key={idx}
                            type="button"
                            data-testid={`step-${idx}`}
                            onClick={() => handleToggleStep(idx)}
                            className={`flex items-center justify-between border px-3 py-1.5 text-left hmi-mono text-[11px] ${
                              done
                                ? "border-[#00ff00] bg-[#001f00] text-[#00ff00]"
                                : "border-[#444444] bg-[#111111] text-white hover:border-white"
                            }`}
                          >
                            <div className="min-w-0 flex-1 pr-2">
                              <div>
                                <span className="font-bold">
                                  {done ? "[X]" : "[ ]"} STEP 0{idx + 1}:
                                </span>{" "}
                                {inst}
                              </div>
                              {backendProto && ruHint && ruHint !== inst && (
                                <div className="text-[10px] text-[#888888]">{ruHint}</div>
                              )}
                            </div>
                            <span className="ml-2 shrink-0 text-[10px] font-bold">
                              {done ? "DONE" : "CONFIRM"}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* BLOCK 4: HOLD TIME 30s VERIFICATION & TWO-STEP CLEAR */}
                <div className="border-t-2 border-[#333333] bg-[#080808] px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div
                        data-testid="emergency-hold"
                        className="hmi-mono text-[11px] font-bold tracking-[0.06em] text-[#ffb000]"
                      >
                        {focusBackendAlert?.resolution_verified
                          ? "04 // RECOVERY VERIFIED · CLEAR AVAILABLE (PRESS TWICE)"
                          : effectivePhase === "HOLD_VERIFICATION"
                          ? `04 // VERIFYING RECOVERY: ${(HOLD_TOTAL_S - displayHoldRemaining).toFixed(0)} / 30 s OF FRESH NOMINAL DATA`
                          : "04 // HOLD 30 s STARTS WHEN VALUES RETURN WITHIN LIMITS"}
                      </div>
                      <div className="truncate hmi-mono text-[10px] text-[#999999]">
                        CRITERIA: {activeProto.holdCriteria}
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      {effectivePhase === "EMERGENCY" ? (
                        <button
                          type="button"
                          onClick={handleRecover}
                          className="border-2 border-[#00ff00] bg-[#00ff00] px-3 py-1.5 hmi-mono text-[11px] font-black text-black hover:bg-white"
                        >
                          START RECOVERY (30s HOLD)
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={handleFastForwardHold}
                          className="border border-[#ffb000] bg-[#261a00] px-2.5 py-1 hmi-mono text-[10px] font-bold text-[#ffb000] hover:bg-[#3d2900]"
                        >
                          [-10s FAST TEST]
                        </button>
                      )}

                      {focusBackendAlert && (
                        <button
                          type="button"
                          data-testid="clear-btn"
                          disabled={!focusBackendAlert.can_clear}
                          onClick={() => {
                            if (!clearArmed) setClearArmed(true);
                            else {
                              setClearArmed(false);
                              void alertActions.clear(focusBackendAlert.id);
                            }
                          }}
                          className={`border px-2.5 py-1.5 hmi-mono text-[10.5px] font-black disabled:border-[#333333] disabled:text-[#555555] ${
                            clearArmed
                              ? "border-[#ffb000] bg-[#ffb000] text-black"
                              : "border-[#00ff00] bg-[#001f00] text-[#00ff00]"
                          }`}
                        >
                          {clearArmed ? "PRESS AGAIN TO CLEAR" : "CLEAR"}
                        </button>
                      )}

                      <div className="border border-[#444444] bg-black px-3 py-1 text-right">
                        <div className="hmi-mono text-[9px] text-[#777777]">HOLD TIMER</div>
                        <div
                          data-testid="hold-timer"
                          className={`hmi-mono text-[20px] font-black leading-none ${
                            effectivePhase === "HOLD_VERIFICATION" ? "text-[#ffb000]" : "text-[#555555]"
                          }`}
                        >
                          {displayHoldRemaining.toFixed(1)}s
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 30-SEGMENT SOLID PROGRESS BAR */}
                  <div className="mt-2 grid grid-cols-30 gap-[2px] border border-[#333333] bg-black p-1">
                    {Array.from({ length: 30 }).map((_, idx) => {
                      const doneSec = HOLD_TOTAL_S - displayHoldRemaining;
                      const activeSeg = effectivePhase === "HOLD_VERIFICATION" && doneSec >= idx + 0.5;
                      return (
                        <div
                          key={idx}
                          className={`h-[8px] ${
                            activeSeg
                              ? "bg-[#00ff00]"
                              : effectivePhase === "HOLD_VERIFICATION"
                              ? "bg-[#332200]"
                              : "bg-[#1a1a1a]"
                          }`}
                        />
                      );
                    })}
                  </div>
                </div>

                {/* DIMMED HEV-1 CORE TELEMETRY STRIP IN EMERGENCY MODE */}
                <div data-testid="hud-vitals" className="border-t border-[#333333] bg-[#060606] p-2">
                  <div data-testid="hud-cabin" className="grid grid-cols-5 gap-1.5">
                    {allParams.map((p) => (
                      <MetricCard key={p.id} p={p} emergency={true} />
                    ))}
                  </div>
                </div>
              </div>
            ) : isUnmonitoredCrew ? (
              <div
                data-testid="crew-no-link"
                className="flex h-full flex-col items-center justify-center gap-2 border border-[#333333] bg-black p-6 text-center"
              >
                <span className="hmi-mono text-[18px] font-black tracking-[0.14em] text-[#ffb000]">
                  {shownCrewId} · NO TELEMETRY LINK
                </span>
                <span className="max-w-[420px] hmi-mono text-[12px] text-[#888888]">
                  No biosensor is configured for this crew member in the prototype. Values are not shown and are never assumed normal.
                </span>
                <button
                  type="button"
                  onClick={() => setViewCrew(null)}
                  className="mt-2 border border-[#00ff00] bg-[#001f00] px-4 py-1.5 hmi-mono text-[11px] font-bold text-[#00ff00]"
                >
                  RETURN TO CM-1 (LIVE TELEMETRY)
                </button>
              </div>
            ) : (
              /* ===============================================================
                 NOMINAL MODE: 3 ANATOMICAL SUBSYSTEM BLOCKS + HEV-1 CORE METRICS
                 =============================================================== */
              <div
                data-testid="nominal-summary-panel"
                className="flex h-full flex-col justify-between bg-black p-2.5 gap-2"
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between border-b border-[#333333] pb-1.5">
                    <div>
                      <div className="hmi-sans text-[12px] font-black tracking-[0.08em] text-[#00ff00]">
                        {effectivePhase === "NOMINAL"
                          ? "SYSTEM STATUS: NOMINAL // NO ACTIVE ALERTS"
                          : `ACTIVE ALERT OVERLAY HIDDEN (${effectiveFault})`}
                      </div>
                      <div className="hmi-mono text-[9.5px] text-[#888888]">
                        CLICK ANATOMICAL ZONE ON WIREFRAME TO INSPECT & SYNC ENGINEERING DRAWER
                      </div>
                    </div>
                    {effectivePhase !== "NOMINAL" ? (
                      <button
                        type="button"
                        onClick={() => setShowTwinInEmergency(false)}
                        className="border border-[#ff0000] bg-[#ff0000] px-2.5 py-1 hmi-mono text-[10.5px] font-black text-black"
                      >
                        RETURN TO EMERGENCY DIRECTIVE
                      </button>
                    ) : (
                      <span className="border border-[#00ff00] bg-[#001f00] px-2.5 py-0.5 hmi-mono text-[10.5px] font-bold text-[#00ff00]">
                        ALL GATES CLEAR
                      </span>
                    )}
                  </div>

                  {/* 3 ANATOMICAL SUBSYSTEM BLOCKS (HEAD, LUNGS, HEART) */}
                  <div className="grid grid-cols-1 gap-2">
                    {/* Z-01: HEAD / NEURO */}
                    <div
                      onClick={() => handleSelectZone("HEAD")}
                      className={`cursor-pointer border p-2 ${
                        selectedZone === "HEAD"
                          ? "border-[#00ff00] bg-[#001400]"
                          : "border-[#333333] bg-[#080808] hover:border-[#666666]"
                      }`}
                    >
                      <div className="flex items-center justify-between border-b border-[#222222] pb-1">
                        <span className="hmi-sans text-[10.5px] font-bold tracking-[0.08em] text-white">
                          [01] HEAD // CNS & NEUROLOGICAL SUBSYSTEM
                        </span>
                        <span className="hmi-mono text-[10px] font-bold text-[#00ff00]">NOMINAL</span>
                      </div>
                      <div className="mt-1.5 grid grid-cols-4 gap-1.5 hmi-mono">
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">COGNITIVE IDX</div>
                          <div className="text-[17px] font-bold text-[#00ff00]">{Math.round(tel.cogIndex)}%</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">CEREBRAL rSO2</div>
                          <div className="text-[17px] font-bold text-white">{tel.cnsO2Sat.toFixed(1)}%</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">PVT REACTION</div>
                          <div className="text-[17px] font-bold text-white">{Math.round(tel.pvtRt)}ms</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">CABIN CO2</div>
                          <div className="text-[17px] font-bold text-[#00ff00]">{tel.cabinCo2Ppm}ppm</div>
                        </div>
                      </div>
                    </div>

                    {/* Z-02: LUNGS / RESPIRATORY */}
                    <div
                      onClick={() => handleSelectZone("LUNGS")}
                      className={`cursor-pointer border p-2 ${
                        selectedZone === "LUNGS"
                          ? "border-[#00ff00] bg-[#001400]"
                          : "border-[#333333] bg-[#080808] hover:border-[#666666]"
                      }`}
                    >
                      <div className="flex items-center justify-between border-b border-[#222222] pb-1">
                        <span className="hmi-sans text-[10.5px] font-bold tracking-[0.08em] text-white">
                          [02] LUNGS // RESPIRATORY & OXYGENATION
                        </span>
                        <span className="hmi-mono text-[10px] font-bold text-[#00ff00]">NOMINAL</span>
                      </div>
                      <div className="mt-1.5 grid grid-cols-4 gap-1.5 hmi-mono">
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">ARTERIAL SpO2</div>
                          <div className="text-[17px] font-bold text-[#00ff00]">{tel.spo2.toFixed(1)}%</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">ALVEOLAR PaO2</div>
                          <div className="text-[17px] font-bold text-white">{Math.round(tel.pao2)}mmHg</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">RESP RATE</div>
                          <div className="text-[17px] font-bold text-white">{Math.round(tel.respRate)}rpm</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">LOOP O2 PRESS</div>
                          <div className="text-[17px] font-bold text-[#00ff00]">{tel.suitO2Kpa.toFixed(1)}kPa</div>
                        </div>
                      </div>
                    </div>

                    {/* Z-03: HEART / CARDIOVASCULAR */}
                    <div
                      onClick={() => handleSelectZone("HEART")}
                      className={`cursor-pointer border p-2 ${
                        selectedZone === "HEART"
                          ? "border-[#00ff00] bg-[#001400]"
                          : "border-[#333333] bg-[#080808] hover:border-[#666666]"
                      }`}
                    >
                      <div className="flex items-center justify-between border-b border-[#222222] pb-1">
                        <span className="hmi-sans text-[10.5px] font-bold tracking-[0.08em] text-white">
                          [03] HEART // CARDIOVASCULAR & HEMODYNAMICS
                        </span>
                        <span className="hmi-mono text-[10px] font-bold text-[#00ff00]">NOMINAL</span>
                      </div>
                      <div className="mt-1.5 grid grid-cols-4 gap-1.5 hmi-mono">
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">HEART RATE</div>
                          <div className="text-[17px] font-bold text-[#00ff00]">{Math.round(tel.hr)} BPM</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">ABP SYS/DIA</div>
                          <div className="text-[17px] font-bold text-white">
                            {Math.round(tel.abpSys)}/{Math.round(tel.abpDia)}
                          </div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">MEAN ABP (MAP)</div>
                          <div className="text-[17px] font-bold text-white">{Math.round(tel.abpMap)}mmHg</div>
                        </div>
                        <div className="border border-[#222222] bg-black px-2 py-1">
                          <div className="text-[8.5px] text-[#777777]">SHOCK INDEX</div>
                          <div className="text-[17px] font-bold text-[#00ff00]">{tel.shockIndex.toFixed(2)}</div>
                        </div>
                      </div>
                    </div>

                    {/* Z-04: HEV-1 CORE BIOMETRICS, CABIN ECLSS & NASA DONKI SPACE WEATHER */}
                    <div
                      data-testid="hud-vitals"
                      className="border border-[#333333] bg-[#080808] p-2"
                    >
                      <div className="flex items-center justify-between border-b border-[#222222] pb-1">
                        <span className="hmi-sans text-[10.5px] font-bold tracking-[0.08em] text-white">
                          [04] HEV-1 CORE TELEMETRY // VITALS, ECLSS & NASA DONKI SPACE WEATHER
                        </span>
                        {donkiCtx && (
                          <span
                            data-testid="hud-space-weather"
                            className={`hmi-mono text-[9.5px] font-bold ${SEV_TEXT[donkiCtx.space_weather_risk]}`}
                          >
                            SPACE WX ({donkiCtx.status.replace("_", " ")}): {donkiCtx.space_weather_risk}
                          </span>
                        )}
                      </div>
                      <div data-testid="hud-cabin" className="mt-1.5 grid grid-cols-5 gap-1.5">
                        {allParams.map((p) => (
                          <MetricCard key={p.id} p={p} emergency={false} />
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* -------------------------------------------------------------------
            3. SIMULATION PANEL (Debug SYS_CTRL — DOCKED RIGHT)
           ------------------------------------------------------------------- */}
        <aside
          data-testid="debug-sys-ctrl"
          className="flex h-full flex-col justify-between border-l border-[#444444] bg-[#181818] text-[#dcdcdc] overflow-y-auto hev-scroll"
        >
          <div data-testid="hud-simulator">
            <div className="border-b border-[#444444] bg-[#262626] px-3 py-1.5">
              <div className="hmi-mono text-[12px] font-black tracking-[0.1em] text-white">
                Debug SYS_CTRL
              </div>
              <div className="hmi-mono text-[9.5px] text-[#999999]">
                SIMULATION, CREW & FAULT INJECTION
              </div>
            </div>

            {/* CREW SELECTOR */}
            <div className="border-b border-[#333333] p-2.5">
              <div className="mb-1 flex items-center justify-between hmi-mono text-[9.5px] font-bold tracking-[0.08em] text-[#aaaaaa]">
                <span>01 // CREW SELECTOR</span>
                {state && (
                  <select
                    data-testid="crew-select"
                    aria-label="Crew member"
                    value={viewCrew ?? state.mission.monitored_crew_id ?? "CM-1"}
                    onChange={(e) => {
                      const val = e.target.value;
                      setViewCrew(val === state.mission.monitored_crew_id ? null : val);
                      if (val === "CM-1") setActiveCrew("SMITH");
                      if (val === "CM-2") setActiveCrew("DOE");
                    }}
                    className="border border-[#555555] bg-black px-1 py-0.5 hmi-mono text-[9.5px] text-white"
                  >
                    {state.mission.crew.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.id} · {c.monitored ? "LIVE" : "NO LINK"}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="grid grid-cols-1 gap-1">
                {(["SMITH", "DOE"] as CrewKey[]).map((cid) => {
                  const prof = CREW_PROFILES[cid];
                  const st = crewStates[cid];
                  const active = activeCrew === cid && !isUnmonitoredCrew;
                  return (
                    <button
                      key={cid}
                      type="button"
                      data-testid={`crew-select-${cid.toLowerCase()}`}
                      onClick={() => {
                        setActiveCrew(cid);
                        setViewCrew(null);
                      }}
                      className={`ctrl-btn flex items-center justify-between ${
                        active ? "border-white bg-[#303030] text-white" : ""
                      }`}
                    >
                      <span>
                        {active ? ">> " : "   "}
                        {prof.name} [{prof.code}]
                      </span>
                      <span
                        className={`px-1.5 py-0.5 text-[9px] font-bold ${
                          st.phase === "EMERGENCY"
                            ? "bg-[#ff0000] text-black"
                            : st.phase === "HOLD_VERIFICATION"
                            ? "bg-[#ffb000] text-black"
                            : "bg-[#00ff00] text-black"
                        }`}
                      >
                        {st.phase === "NOMINAL" ? "NOM" : st.fault}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* FAULT TRIGGERS (ALL 6 SCENARIOS FROM 1123 + DESKTOP DESCRIPTIONS) */}
            <div className="border-b border-[#333333] p-2.5">
              <div className="mb-1 hmi-mono text-[9.5px] font-bold tracking-[0.08em] text-[#aaaaaa]">
                02 // SCENARIO TRIGGERS
              </div>
              <div className="flex flex-col gap-1.5">
                <button
                  type="button"
                  data-testid="scenario-hypoxia"
                  onClick={() => handleTriggerFault("HYPOXIA", "hypoxia", "HYPOXIA")}
                  className={`ctrl-btn ${
                    effectiveFault === "HYPOXIA" && effectivePhase === "EMERGENCY" ? "ctrl-btn-active-red" : ""
                  }`}
                >
                  <div>TRG: HYPOXIA</div>
                  <div className="text-[8.5px] font-normal">Lungs Red | SpO2 &lt; 85% | Req O2 Mask</div>
                </button>

                <button
                  type="button"
                  data-testid="scenario-hemorrhage"
                  onClick={() => handleTriggerFault("HEMORRHAGE", "hemorrhage", "HEMORRHAGE")}
                  className={`ctrl-btn ${
                    effectiveFault === "HEMORRHAGE" && effectivePhase === "EMERGENCY" ? "ctrl-btn-active-red" : ""
                  }`}
                >
                  <div>TRG: HEMORRHAGE</div>
                  <div className="text-[8.5px] font-normal">Heart Red | BP Drop, HR &gt; 130 | KIT A-1</div>
                </button>

                <button
                  type="button"
                  data-testid="scenario-high_co2"
                  onClick={() => handleTriggerFault("CO2_SPIKE", "high_co2", "HIGH CO2")}
                  className={`ctrl-btn ${
                    effectiveFault === "CO2_SPIKE" && effectivePhase === "EMERGENCY" ? "ctrl-btn-active-red" : ""
                  }`}
                >
                  <div>TRG: CO2 SPIKE</div>
                  <div className="text-[8.5px] font-normal">Head/Lungs Red | CO2 &gt; 6500ppm | LiOH Kit</div>
                </button>

                <button
                  type="button"
                  data-testid="scenario-solar_flare"
                  onClick={() => handleTriggerFault("SOLAR_FLARE", "solar_flare", "SOLAR FLARE")}
                  className={`ctrl-btn ${
                    effectiveFault === "SOLAR_FLARE" && effectivePhase === "EMERGENCY" ? "ctrl-btn-active-red" : ""
                  }`}
                >
                  <div>TRG: SOLAR FLARE</div>
                  <div className="text-[8.5px] font-normal">Radiation | DONKI SEP Spike | Shelter</div>
                </button>

                <button
                  type="button"
                  data-testid="scenario-tachycardia"
                  onClick={() => handleTriggerFault("TACHYCARDIA", "tachycardia", "TACHYCARDIA")}
                  className={`ctrl-btn ${
                    effectiveFault === "TACHYCARDIA" && effectivePhase === "EMERGENCY" ? "ctrl-btn-active-red" : ""
                  }`}
                >
                  <div>TRG: TACHYCARDIA</div>
                  <div className="text-[8.5px] font-normal">Heart Red | HR &gt; 135 bpm | Rest Protocol</div>
                </button>

                <button
                  type="button"
                  data-testid="scenario-sensor_failure"
                  onClick={() => handleTriggerFault("SENSOR_FAILURE", "sensor_failure", "SENSOR FAILURE")}
                  className={`ctrl-btn ${
                    effectiveFault === "SENSOR_FAILURE" && effectivePhase === "EMERGENCY" ? "ctrl-btn-active-red" : ""
                  }`}
                >
                  <div>TRG: SENSOR FAIL</div>
                  <div className="text-[8.5px] font-normal">Data Integrity | SENSOR_FAULT | Check Leads</div>
                </button>
              </div>
            </div>

            {/* RECOVERY & CREW OPERATIONS */}
            <div className="border-b border-[#333333] p-2.5">
              <div className="mb-1 hmi-mono text-[9.5px] font-bold tracking-[0.08em] text-[#aaaaaa]">
                03 // RECOVERY & CREW OPS
              </div>
              <div className="flex flex-col gap-1.5">
                <button
                  type="button"
                  data-testid="scenario-nominal"
                  onClick={handleRecover}
                  className={`ctrl-btn ${
                    effectivePhase === "HOLD_VERIFICATION" ? "ctrl-btn-active-amber" : "border-[#00ff00] text-[#00ff00]"
                  }`}
                >
                  <div>SYS: RECOVER TO NOMINAL</div>
                  <div className="text-[8.5px] font-normal">Return to Nominal via 30s Hold Timer</div>
                </button>

                {effectivePhase === "HOLD_VERIFICATION" && (
                  <button
                    type="button"
                    onClick={handleFastForwardHold}
                    className="ctrl-btn border-[#ffb000] text-[#ffb000]"
                  >
                    DBG: Skip -10s Hold Timer
                  </button>
                )}

                <button
                  type="button"
                  data-testid="link-toggle"
                  onClick={() => {
                    armAudio();
                    const up = state?.sync.link_up ?? true;
                    void runApi(api.link(!up), up ? "Earth link lost (simulated)" : "Earth link restored");
                  }}
                  className="ctrl-btn"
                >
                  {state?.sync.link_up !== false
                    ? "SYS: SIMULATE LOSS OF SIGNAL"
                    : `SYS: RESTORE LINK · ${state?.sync.pending ?? 0} QUEUED`}
                </button>

                <div className="grid grid-cols-2 gap-1">
                  <button
                    type="button"
                    data-testid="open-pvt"
                    onClick={() => setModal("pvt")}
                    className="ctrl-btn text-center text-[#00c8ff]"
                  >
                    10s PVT TEST
                  </button>
                  <button
                    type="button"
                    data-testid="open-psych"
                    onClick={() => setModal("psych")}
                    className="ctrl-btn text-center text-[#00c8ff]"
                  >
                    SELF-CHECK
                  </button>
                </div>
              </div>
            </div>

            {/* TELEMETRY SYNC DIAGNOSTICS */}
            <div className="p-2.5 hmi-mono text-[9.5px]">
              <div className="mb-1 font-bold text-[#aaaaaa]">04 // SYNC STATE</div>
              <div className="grid grid-cols-2 gap-y-0.5 border border-[#333333] bg-[#101010] p-2">
                <span className="text-[#777777]">PHASE:</span>
                <span
                  className={`text-right font-bold ${
                    effectivePhase === "NOMINAL"
                      ? "text-[#00ff00]"
                      : effectivePhase === "EMERGENCY"
                      ? "text-[#ff0000]"
                      : "text-[#ffb000]"
                  }`}
                >
                  {effectivePhase}
                </span>
                <span className="text-[#777777]">SVG ZONE:</span>
                <span className="text-right font-bold text-white">{selectedZone ?? "NONE"}</span>
                <span className="text-[#777777]">DRAWER:</span>
                <span className="text-right text-[#00ff00]">
                  {isDrawerOpen ? "EXPANDED" : "COLLAPSED"}
                </span>
                <span className="text-[#777777]">HOLD 30s:</span>
                <span className="text-right text-[#ffb000]">{displayHoldRemaining.toFixed(1)}s</span>
              </div>
            </div>

            {/* 05 // KSP 1 LIVE TELEMETRY BRIDGE */}
            <div data-testid="ksp-bridge-panel" className="border-t border-[#333333] p-2.5 hmi-mono text-[9.5px]">
              <div className="mb-1 flex items-center justify-between font-bold text-[#aaaaaa]">
                <span>05 // KSP 1 TELEMETRY BRIDGE</span>
                <span
                  data-testid="ksp-link-badge"
                  className={`px-1.5 py-0.5 text-[8.5px] font-black ${
                    state?.ksp?.connected
                      ? "bg-[#00ff00] text-black"
                      : "border border-[#ffb000] bg-[#1a1100] text-[#ffb000]"
                  }`}
                >
                  {state?.ksp?.connected ? "KSP ONLINE (1Hz)" : "KSP STANDBY"}
                </span>
              </div>
              <div className="border border-[#333333] bg-[#101010] p-2">
                {state?.ksp?.connected ? (
                  <div className="flex flex-col gap-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[#777777]">VESSEL:</span>
                      <span className="truncate font-bold text-[#00ff00]">{state.ksp.vessel_name}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[#777777]">SITUATION:</span>
                      <span className="text-white">
                        {state.ksp.situation} @ {state.ksp.body}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[#777777]">G-LOAD / ALT:</span>
                      <span className="text-[#00c8ff]">
                        {state.ksp.g_force.toFixed(2)}G · {(state.ksp.altitude_m / 1000).toFixed(1)}km
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-[#777777]">FLIGHT PHASE:</span>
                      <span
                        className={`font-bold ${
                          state.ksp.hazard_phase && state.ksp.hazard_phase !== "NOMINAL_PAD"
                            ? "text-[#ff0000]"
                            : "text-[#00ff00]"
                        }`}
                      >
                        {state.ksp.hazard_phase ?? "NOMINAL_PAD"}
                      </span>
                    </div>
                    {state.ksp.hazard_label && state.ksp.hazard_phase !== "NOMINAL_PAD" && (
                      <div className="border border-[#ff0000] bg-[#260000] px-1.5 py-0.5 text-[8.5px] font-bold text-[#ffb000]">
                        {state.ksp.hazard_label}
                      </div>
                    )}
                    <div className="flex items-center justify-between">
                      <span className="text-[#777777]">KERBAL STATE:</span>
                      <span
                        className={`font-bold ${
                          state.ksp.consciousness === "Unconscious"
                            ? "text-[#ff0000]"
                            : state.ksp.consciousness === "CognitivelyImpaired"
                            ? "text-[#ffb000]"
                            : "text-[#00ff00]"
                        }`}
                      >
                        {state.ksp.emotion.toUpperCase()} / {state.ksp.consciousness.toUpperCase()}
                      </span>
                    </div>
                    {state.ksp.crew.length > 0 && (
                      <div className="mt-1 border-t border-[#262626] pt-1">
                        {state.ksp.crew.map((c) => (
                          <div key={c.name} className="flex items-center justify-between text-[8.5px]">
                            <span className="truncate text-[#cccccc]">{c.name}</span>
                            <span
                              className={`font-bold ${
                                c.inactive
                                  ? "text-[#ff0000]"
                                  : c.type === "Tourist"
                                  ? "text-[#ffb000]"
                                  : "text-[#00ff00]"
                              }`}
                            >
                              {c.state_label}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-[8.5px] leading-snug text-[#888888]">
                    <div>DLL: GameData/OrionMedKSP/Plugins/OrionMedKSP.dll</div>
                    <div className="mt-0.5 text-[#aaaaaa]">
                      Launch KSP 1 Flight Scene to stream live Kerbal biometrics & G-load at 1 Hz.
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="border-t border-[#333333] bg-[#121212] px-3 py-1.5 hmi-mono text-[8.5px] text-[#777777]">
            <div>DISPLAY: R.I.D.G.E. // ORION-MED HEV-1 v1.0.7</div>
            <div>ZERO ALPHA // ZERO RADIUS // PURE #000</div>
          </div>
        </aside>
      </div>

      {/* =====================================================================
          3. BOTTOM BLOCK: COLLAPSIBLE ENGINEERING TELEMETRY DRAWER
             [+]/[-] EXPAND/COLLAPSE + SYNCHRONIZED TABLE
         ===================================================================== */}
      <section className="shrink-0 bg-black" data-testid="engineering-drawer">
        {/* FULL-WIDTH TOGGLE BAR */}
        <div className="flex h-[34px] items-stretch border-b border-[#333333] bg-[#111111]">
          <button
            type="button"
            data-testid="toggle-engineering-drawer"
            onClick={() => setIsDrawerOpen((o) => !o)}
            className="flex flex-1 items-center justify-between px-4 text-left hmi-mono text-[11.5px] font-bold tracking-[0.08em] text-white hover:bg-[#1c1c1c]"
          >
            <div className="flex items-center gap-3">
              <span className="text-[#00ff00]">
                {isDrawerOpen
                  ? "[-] COLLAPSE ENGINEERING TELEMETRY"
                  : "[+] EXPAND ENGINEERING TELEMETRY"}
              </span>
              {selectedZone && (
                <span className="border border-[#00ff00] bg-[#002200] px-2 py-0.5 text-[10px] text-[#00ff00]">
                  SYNCED ZONE: {selectedZone}
                </span>
              )}
              {effectivePhase !== "NOMINAL" && (
                <span className="bg-[#ff0000] px-2 py-0.5 text-[10px] font-black text-black">
                  FORCED OPEN BY EMERGENCY ({effectiveFault})
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 text-[11px] text-[#999999]">
              <span>
                SpO2:{" "}
                <strong className={tel.spo2 < 85 ? "text-[#ff0000]" : "text-[#00ff00]"}>
                  {tel.spo2.toFixed(1)}%
                </strong>
              </span>
              <span>
                HR:{" "}
                <strong className={tel.hr > 125 ? "text-[#ff0000]" : "text-[#00ff00]"}>
                  {Math.round(tel.hr)} BPM
                </strong>
              </span>
              <span>
                ABP:{" "}
                <strong className={tel.abpSys < 90 ? "text-[#ff0000]" : "text-[#00ff00]"}>
                  {Math.round(tel.abpSys)}/{Math.round(tel.abpDia)} mmHg
                </strong>
              </span>
              <span>
                CO2:{" "}
                <strong className={tel.cabinCo2Ppm > 4000 ? "text-[#ff0000]" : "text-[#00ff00]"}>
                  {tel.cabinCo2Ppm} ppm
                </strong>
              </span>
            </div>
          </button>

          {selectedZone && (
            <button
              type="button"
              onClick={() => setSelectedZone(null)}
              className="border-l border-[#333333] bg-[#1a1a1a] px-3 hmi-mono text-[10px] font-bold text-[#cccccc] hover:bg-[#2a2a2a]"
            >
              [CLEAR ZONE]
            </button>
          )}
          <button
            type="button"
            onClick={() => setScreen("engineering")}
            className="border-l border-[#333333] bg-[#0d181c] px-3 hmi-mono text-[10px] font-bold text-[#00c8ff] hover:bg-[#00c8ff] hover:text-black"
          >
            [2 · FULL ENGINEERING]
          </button>
          {cfmsEnabled && (
            <button
              type="button"
              onClick={() => setScreen("fitness")}
              className="border-l border-[#333333] bg-[#001a00] px-3 hmi-mono text-[10px] font-bold text-[#00ff00] hover:bg-[#00ff00] hover:text-black"
            >
              [3 · CFMS FITNESS]
            </button>
          )}
        </div>

        {/* EXPANDABLE TABLE CONTAINER */}
        <div
          style={{ height: isDrawerOpen ? "245px" : "0px" }}
          className="telemetry-drawer overflow-y-auto bg-black hev-scroll"
        >
          <table className="w-full border-collapse hmi-mono text-[11px]">
            <thead className="sticky top-0 bg-[#141414] text-left text-[10px] text-[#999999]">
              <tr className="border-b border-[#333333]">
                <th className="border-r border-[#333333] px-3 py-1.5 w-[170px]">SYSTEM</th>
                <th className="border-r border-[#333333] px-3 py-1.5">PARAMETER</th>
                <th className="border-r border-[#333333] px-3 py-1.5 w-[180px]">CURRENT VALUE</th>
                <th className="border-r border-[#333333] px-3 py-1.5 w-[180px]">NOMINAL RANGE</th>
                <th className="border-r border-[#333333] px-3 py-1.5 w-[110px]">SOURCE</th>
                <th className="px-3 py-1.5 w-[160px]">STATUS</th>
              </tr>
            </thead>
            <tbody>
              {TELEMETRY_TABLE_ROWS.map((row) => {
                const status = row.evaluate(tel);
                const isZoneSelected = selectedZone === row.zone;
                const isCritical = status === "CRITICAL";
                const isCaution = status === "CAUTION";
                const backendParam = row.paramId ? allParams.find((p) => p.id === row.paramId) : undefined;

                let rowBg = "bg-black";
                if (isCritical) {
                  rowBg = "bg-[#2b0000]";
                } else if (isZoneSelected) {
                  rowBg = "bg-[#002209]";
                } else if (isCaution) {
                  rowBg = "bg-[#241800]";
                }

                return (
                  <tr
                    key={row.id}
                    ref={(el) => {
                      rowRefs.current[row.id] = el;
                    }}
                    onClick={() => handleSelectZone(row.zone)}
                    className={`cursor-pointer border-b border-[#262626] ${rowBg} hover:bg-[#1a1a1a]`}
                  >
                    <td className="border-r border-[#333333] px-3 py-1.5 font-bold">
                      <span
                        className={
                          isZoneSelected
                            ? "text-[#00ff00]"
                            : isCritical
                            ? "text-[#ff0000]"
                            : "text-[#bbbbbb]"
                        }
                      >
                        {isZoneSelected ? ">> " : "   "}
                        {row.systemLabel}
                      </span>
                    </td>
                    <td className="border-r border-[#333333] px-3 py-1.5 text-white">
                      {row.paramLabel}
                    </td>
                    <td
                      className={`border-r border-[#333333] px-3 py-1.5 font-bold ${
                        isCritical
                          ? "text-[#ff0000]"
                          : isCaution
                          ? "text-[#ffb000]"
                          : "text-[#00ff00]"
                      }`}
                    >
                      {row.getValue(tel)}
                    </td>
                    <td className="border-r border-[#333333] px-3 py-1.5 text-[#888888]">
                      {row.normLabel}
                    </td>
                    <td className="border-r border-[#333333] px-3 py-1.5 text-[#ffb000]">
                      {backendParam?.source ?? "SIMULATED"}
                    </td>
                    <td className="px-3 py-1.5 font-black">
                      {isCritical ? (
                        <span className="inline-block bg-[#ff0000] px-2 py-0.5 text-[10px] text-black">
                          CRITICAL // ACTION
                        </span>
                      ) : isCaution ? (
                        <span className="inline-block bg-[#ffb000] px-2 py-0.5 text-[10px] text-black">
                          CAUTION // DEVIATION
                        </span>
                      ) : (
                        <span className="inline-block border border-[#006600] bg-[#001a00] px-2 py-0.5 text-[10px] text-[#00ff00]">
                          NOMINAL
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
