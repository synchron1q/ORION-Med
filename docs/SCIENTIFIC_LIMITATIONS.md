# Scientific limitations

- **Not a medical device.** HEV-1 is a hackathon prototype. It does not diagnose, treat or replace a flight surgeon or professional medical judgment.
- **Demonstration thresholds.** All limits in `config/demo_thresholds.yaml` were chosen to make the scenarios observable. None is taken from NASA-STD-3001 or any flight rule. Real missions would configure limits from approved standards and crew-specific baselines.
- **Demonstration procedures.** Countermeasure texts and kit identifiers (KIT ECLSS-03, KIT O2-A, ...) are original prototype content, not NASA-approved protocols or real hardware.
- **Simulated telemetry.** Without real sensors, all physiological, environmental and dosimeter values come from the deterministic simulator and are labeled `SIM`. Simulated dose rates are illustrative magnitudes only.
- **Space weather is context, not dose.** A DONKI event does not measure crew exposure and does not decide EVA safety; exposure requires dosimetry, shielding and mission-specific modeling. Hence the NOMINAL advisory reads "NO DONKI EVA CONSTRAINT", not "EVA permitted".
- **EVA readiness is decision support.** The four gates reuse the demonstration thresholds; "NO BLOCKERS FOUND" means no configured blocker was detected, not that an EVA is safe. Missing data always yields DATA INCOMPLETE.
- **Triage focus is not a diagnosis.** It only suggests which checklist to open first.
- **Correlation is not causation.** R.I.D.G.E. only reports temporal co-occurrence of configured observations.
- **PVT.** The 10-second test is a short demonstration version; validated PVT protocols are longer. Results are personal trends, not cognitive diagnoses.
- **Self-assessment** is private by default and never used to label a mental-health condition.
- **OSDR datasets** are research references, not real-time spacecraft telemetry.

## CFMS (Crew Fitness Management System)

- The Mission Plan is a fictional SIMULATED timeline. Activity buffers, the training program, exercise profiles
  and the clearance validity limit are DEMONSTRATION values chosen for the prototype, not NASA exercise
  prescriptions, flight rules or validated medical criteria.
- Exercise equipment is SIMULATED with neutral names; no hardware is controlled.
- "READY PER PLAN" means only that the DEMONSTRATION rules found no blocker. It is not a medical authorization.
- Medical Clearance records are SIMULATED and scoped (one crew member, one exercise type, limited validity).
- Recovery Monitor criteria (10-min window, 60-s drop of 12 bpm, baseline + 10 bpm) are DEMONSTRATION values, not a
  validated clinical heart-rate-recovery assessment. In the simulator the recovery is time-compressed.
