# Data sources

| Source | Link | How it is used |
|---|---|---|
| NASA DONKI — Solar Flares (FLR) | https://api.nasa.gov/ (`/DONKI/FLR`) | Latest flare class, peak time and active region over the last 7 days; space-weather risk context (X → WARNING, M → CAUTION). Cached 15 min in SQLite. |
| NASA DONKI — Notifications, type FLR (fallback) | https://api.nasa.gov/ (`/DONKI/notifications?type=FLR`) | Used only when `/DONKI/FLR` answers HTTP 404. Parses class, peak time, active region and activity ID from detailed flare notices; GOES threshold notices become ">= class" entries. Covers significant flares only (typically M5 and above). |
| NASA DONKI — Solar Energetic Particles (SEP) | https://api.nasa.gov/ (`/DONKI/SEP`) | SEP events in the last 24 h → WARNING context, "EVA HOLD RECOMMENDED" advisory; also used by the R.I.D.G.E. dose-rate rule. |
| NASA OSDR | https://osdr.nasa.gov/ | Research references (metadata inspected on 2026-11-14 via `https://osdr.nasa.gov/osdr/data/osd/meta/<n>`; re-checked online by the app): [OSD-569](https://osdr.nasa.gov/bio/repo/data/studies/OSD-569) Inspiration4 whole blood (incl. CBC); [OSD-360](https://osdr.nasa.gov/bio/repo/data/studies/OSD-360) low-dose space radiation, splenic metabolome; [OSD-479](https://osdr.nasa.gov/bio/repo/data/studies/OSD-479) deep-space radiation and cognitive performance; [OSD-922](https://osdr.nasa.gov/bio/repo/data/studies/OSD-922) spaceflight effects on heart ventricles. |
| NASA-STD-3001 Vol. 1 | https://www.nasa.gov/reference/nasa-std-3001v1/ | Reference for crew-health requirements. |
| NASA-STD-3001 Vol. 2 | https://www.nasa.gov/reference/nasa-std-3001v2/ | Reference for environmental health and habitability (e.g. cabin atmosphere). |

## Provenance labels in the application
- `SENSOR` — posted by a real sensor through the API.
- `SIMULATED` — mission simulator output (`SIM` badge).
- `CREW_INPUT` — PVT result or self-check entered by the crew.
- `NASA DONKI` — external space-weather context with fetch time, per-feed status and HTTP code.
- `DEMONSTRATION` — every threshold and countermeasure text.

## Observed service status during development (2026-11-14)
- `GET https://api.nasa.gov/DONKI/FLR` returned HTTP 404 for any date range while CME, GST, SEP and notifications responded; since v1.0.2 the FLR notifications fallback keeps flare context live. DEMO_KEY also returned HTTP 429 after repeated test runs. Both cases are shown in the interface (per-feed status) and handled by the cache tiers.
- Use your own key from https://api.nasa.gov/ in `.env` for a higher rate limit.
