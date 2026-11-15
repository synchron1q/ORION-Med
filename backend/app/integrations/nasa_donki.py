# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""NASA DONKI space-weather integration (Solar Flares FLR + Solar Energetic Particles SEP).

Design rules
------------
* DONKI is *environmental context*. It never raises alerts, never changes
  telemetry and never overrides the emergency simulator scenarios.
* `/api/state` is polled at 1 Hz but must never wait for NASA: the context is
  always built from SQLite (`NasaWeatherCache`). When the cache is older than
  the 15-minute TTL a single background refresh is scheduled.
* DEMO_KEY allows ~30 requests/hour. One refresh = 2 requests. After a failed
  refresh the next attempt waits RETRY_AFTER_FAILURE (5 min) -> at most 24
  requests/hour even when NASA keeps failing.
* Every fetch attempt is recorded in `ExternalDataSnapshot` (provenance, HTTP
  status, error). A successful but empty response also counts as fresh data.
* FLR fallback: when `/DONKI/FLR` answers HTTP 404 (endpoint unavailable on
  api.nasa.gov, observed on 2026-11-14), flares are read from
  `/DONKI/notifications?type=FLR`. Notifications only cover significant
  flares (GOES threshold alerts, typically >= M5), so the fallback is marked
  in the per-feed status. Other errors (429, timeouts) never trigger it.

Resilience tiers
----------------
LIVE              every feed fetched successfully within the TTL
CACHED_OFFLINE    the last fetch failed (network, timeout, HTTP 429/4xx/5xx)
                  -> most recent cached event is served
OFFLINE_BASELINE  fetch failed / never succeeded AND the cache is empty
                  -> deterministic placeholder, explicitly NOT a NASA observation
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, TypedDict

import httpx
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ExternalDataSnapshot, NasaWeatherCache

log = logging.getLogger("orion.nasa_donki")

DONKI_BASE_URL = "https://api.nasa.gov/DONKI"
FEEDS: tuple[str, ...] = ("FLR", "SEP")
CACHE_TTL = timedelta(minutes=15)
RETRY_AFTER_FAILURE = timedelta(minutes=5)
MANUAL_REFRESH_MIN_INTERVAL = timedelta(seconds=60)
LOOKBACK_DAYS = 7
HTTP_TIMEOUT_S = 5.0
SEP_ACTIVE_WINDOW = timedelta(hours=24)
SNAPSHOT_SOURCE = "NASA_DONKI"

DonkiStatus = Literal["LIVE", "CACHED_OFFLINE", "OFFLINE_BASELINE"]
SpaceWeatherRisk = Literal["NOMINAL", "CAUTION", "WARNING"]

EVA_ADVISORY: dict[str, str] = {
    "WARNING": "EVA HOLD RECOMMENDED",
    "CAUTION": "MONITOR RADIATION",
    # Space-weather context alone cannot clear an EVA (NASA-STD-3001 context,
    # local dosimetry and mission control decide). Hence no "EVA PERMITTED".
    "NOMINAL": "NO DONKI EVA CONSTRAINT",
}

RADIATION_CONTEXT: dict[str, str] = {
    "WARNING": "NASA DONKI reports a significant solar event. DONKI describes the external solar environment only; crew exposure must be confirmed with the onboard dosimeter and vehicle shielding.",
    "CAUTION": "NASA DONKI reports moderate solar activity. This is external context only; correlate with the onboard dosimeter before any operational decision.",
    "NOMINAL": "No significant solar event in the DONKI context. DONKI is external context only and does not measure crew dose; the onboard dosimeter remains the exposure reference.",
}

OFFLINE_BASELINE_EVENT: dict[str, Any] = {
    "event_id": "OFFLINE-BASELINE",
    "event_type": "FLR",
    "class_type": "C2.4",
    "latest_event": "Solar Flare C2.4 (Offline Baseline - placeholder, not a NASA observation)",
}


class FeedStatus(TypedDict):
    last_attempt: str | None
    last_success: str | None
    last_status: str | None
    http_status: int | None
    error: str | None
    endpoint: str | None


class NasaDonkiContext(TypedDict):
    status: DonkiStatus
    latest_event: str
    event_id: str | None
    event_type: str | None
    class_type: str | None
    peak_time: str | None
    event_age_h: float | None
    link: str | None
    space_weather_risk: SpaceWeatherRisk
    eva_advisory: str
    radiation_context: str
    updated_at: str
    last_successful_fetch: str | None
    is_placeholder: bool
    refresh_in_progress: bool
    feeds: dict[str, FeedStatus]
    recent_events: list[dict[str, Any]]
    source: str
    provenance: str


class _RefreshState:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.last_manual: datetime | None = None


_state = _RefreshState()


# ----------------------------------------------------------------- helpers
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def api_key() -> str:
    return os.getenv("NASA_API_KEY", "DEMO_KEY") or "DEMO_KEY"


def parse_donki_time(raw: Any) -> datetime | None:
    """DONKI timestamps look like '2026-11-13T21:24Z' (UTC)."""
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def parse_flr(item: dict[str, Any]) -> dict[str, Any] | None:
    event_id = item.get("flrID")
    if not event_id:
        return None
    region = item.get("activeRegionNum")
    return {
        "event_id": str(event_id),
        "event_type": "FLR",
        "class_type": str(item.get("classType") or "UNKNOWN"),
        "peak_time": parse_donki_time(item.get("peakTime") or item.get("beginTime")),
        "active_region": str(region) if region else None,
        "link": item.get("link"),
    }


def parse_sep(item: dict[str, Any]) -> dict[str, Any] | None:
    event_id = item.get("sepID")
    if not event_id:
        return None
    return {
        "event_id": str(event_id),
        "event_type": "SEP",
        "class_type": "SEP_EVENT",
        "peak_time": parse_donki_time(item.get("eventTime")),
        "active_region": None,
        "link": item.get("link"),
    }


PARSERS = {"FLR": parse_flr, "SEP": parse_sep}

NOTIFICATION_DEDUP_WINDOW = timedelta(minutes=30)
_RE_CLASS = re.compile(r"Flare intensity:\s*([ABCMX]\d+(?:\.\d+)?)\s*class", re.I)
_RE_PEAK = re.compile(r"Flare peak time:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)", re.I)
_RE_REGION = re.compile(r"Active Region\s+(\d+)", re.I)
_RE_ACTIVITY = re.compile(r"Activity ID:\s*(\S+?-FLR-\d+)", re.I)
_RE_THRESHOLD = re.compile(r"crossed the threshold of\s*([CMX]\d+(?:\.\d+)?)", re.I)
_RE_CROSSING = re.compile(r"crossing time:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z)", re.I)


def parse_flr_notifications(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract flares from DONKI FLR notifications (fallback for /DONKI/FLR).

    * Detailed notices ("Flare intensity: M8.1 class") give class, peak time,
      active region and the DONKI activity ID (same format as flrID).
    * Auto-generated threshold notices only state "crossed the threshold of
      M5.0"; they are stored as class "M5.0+" (meaning at least M5.0) and
      dropped when a detailed notice exists within 30 minutes.
    """
    detailed: list[dict[str, Any]] = []
    thresholds: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("messageType") != "FLR":
            continue
        body = str(item.get("messageBody") or "")
        msg_id = str(item.get("messageID") or "")
        link = item.get("messageURL")
        cls = _RE_CLASS.search(body)
        if cls:
            act = _RE_ACTIVITY.search(body)
            peak = _RE_PEAK.search(body)
            region = _RE_REGION.search(body)
            detailed.append({
                "event_id": act.group(1) if act else f"NOTIF-{msg_id}",
                "event_type": "FLR",
                "class_type": cls.group(1).upper(),
                "peak_time": parse_donki_time(peak.group(1)) if peak else parse_donki_time(item.get("messageIssueTime")),
                "active_region": region.group(1) if region else None,
                "link": link,
            })
            continue
        thr = _RE_THRESHOLD.search(body)
        if thr:
            crossing = _RE_CROSSING.search(body)
            thresholds.append({
                "event_id": f"NOTIF-{msg_id}",
                "event_type": "FLR",
                "class_type": thr.group(1).upper() + "+",
                "peak_time": parse_donki_time(crossing.group(1)) if crossing else parse_donki_time(item.get("messageIssueTime")),
                "active_region": None,
                "link": link,
            })
    out = list(detailed)
    for t in thresholds:
        near = any(
            d["peak_time"] and t["peak_time"] and abs(d["peak_time"] - t["peak_time"]) <= NOTIFICATION_DEDUP_WINDOW
            for d in detailed
        )
        if not near:
            out.append(t)
    return out


def endpoint_label(request_url: str | None) -> str | None:
    if not request_url:
        return None
    return "notifications (FLR fallback)" if "/notifications" in request_url else request_url.split("?")[0].rsplit("/", 1)[-1]


def describe(event_type: str, class_type: str, region: str | None) -> str:
    if event_type == "SEP":
        return "SEP Event Detected"
    if class_type.endswith("+"):
        return f"Solar Flare >={class_type[:-1]} (DONKI threshold alert)"
    return f"Solar Flare {class_type}" + (f" (Region AR{region})" if region else "")


def classify_risk(event_type: str | None, class_type: str | None) -> SpaceWeatherRisk:
    if event_type == "SEP":
        return "WARNING"
    cls = (class_type or "").upper()
    if cls.startswith("X"):
        return "WARNING"
    if cls.startswith("M"):
        return "CAUTION"
    return "NOMINAL"


# ------------------------------------------------------------- fetching
async def fetch_feed(client: httpx.AsyncClient, feed: str, start_date: str) -> list[dict[str, Any]]:
    response = await client.get(f"{DONKI_BASE_URL}/{feed}", params={"startDate": start_date, "api_key": api_key()})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected DONKI {feed} payload type: {type(data).__name__}")
    return data


async def fetch_flr_notifications(client: httpx.AsyncClient, start_date: str, end_date: str) -> list[dict[str, Any]]:
    response = await client.get(f"{DONKI_BASE_URL}/notifications",
                                params={"startDate": start_date, "endDate": end_date, "type": "FLR", "api_key": api_key()})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected DONKI notifications payload type: {type(data).__name__}")
    return data


def _upsert(s: Session, row: dict[str, Any], fetched_at: datetime) -> None:
    existing = s.scalars(select(NasaWeatherCache).where(NasaWeatherCache.event_id == row["event_id"])).first()
    if existing is None:
        s.add(NasaWeatherCache(fetched_at=fetched_at, **row))
    else:
        for key, value in row.items():
            setattr(existing, key, value)
        existing.fetched_at = fetched_at


async def refresh_cache(
    session_factory: sessionmaker,
    *,
    now: datetime | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, str]:
    """Fetch FLR and SEP for the last 7 days and update the SQLite cache.

    Never raises: every failure is recorded and reported as 'ERROR'.
    """
    now = now or _utcnow()
    start_date = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")
    results: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, transport=transport) as client:
            for feed in FEEDS:
                logged_url = f"{DONKI_BASE_URL}/{feed}?startDate={start_date}&api_key=***"
                http_status: int | None = None
                try:
                    try:
                        items = await fetch_feed(client, feed, start_date)
                        rows = [r for r in (PARSERS[feed](i) for i in items if isinstance(i, dict)) if r]
                    except httpx.HTTPStatusError as exc:
                        if feed != "FLR" or exc.response.status_code != 404:
                            raise
                        log.warning("DONKI FLR returned 404 - using FLR notifications fallback")
                        logged_url = f"{DONKI_BASE_URL}/notifications?startDate={start_date}&endDate={end_date}&type=FLR&api_key=***"
                        rows = parse_flr_notifications(await fetch_flr_notifications(client, start_date, end_date))
                    with session_factory() as s:
                        for row in rows:
                            _upsert(s, row, now)
                        s.add(ExternalDataSnapshot(source=SNAPSHOT_SOURCE, feed=feed, request_url=logged_url, fetched_at=now,
                                                   status="OK", http_status=200, record_count=len(rows)))
                        s.commit()
                    results[feed] = "OK"
                except Exception as exc:  # network, timeout, HTTP 429/404/5xx, invalid JSON
                    if isinstance(exc, httpx.HTTPStatusError):
                        http_status = exc.response.status_code
                    error = f"{type(exc).__name__}: {exc}"[:300]
                    log.warning("DONKI %s fetch failed: %s", feed, error)
                    with session_factory() as s:
                        s.add(ExternalDataSnapshot(source=SNAPSHOT_SOURCE, feed=feed, request_url=logged_url, fetched_at=now,
                                                   status="ERROR", http_status=http_status, error=error, record_count=0))
                        s.commit()
                    results[feed] = "ERROR"
    except Exception as exc:  # pragma: no cover - defensive: e.g. database locked
        log.error("DONKI refresh aborted: %s", exc)
        for feed in FEEDS:
            results.setdefault(feed, "ERROR")
    return results


# --------------------------------------------------------------- status
def feed_status(db: Session) -> dict[str, FeedStatus]:
    out: dict[str, FeedStatus] = {}
    for feed in FEEDS:
        base = select(ExternalDataSnapshot).where(ExternalDataSnapshot.source == SNAPSHOT_SOURCE, ExternalDataSnapshot.feed == feed)
        last = db.scalars(base.order_by(desc(ExternalDataSnapshot.id)).limit(1)).first()
        ok = db.scalars(base.where(ExternalDataSnapshot.status == "OK").order_by(desc(ExternalDataSnapshot.id)).limit(1)).first()
        out[feed] = {
            "last_attempt": _iso(last.fetched_at) if last else None,
            "last_success": _iso(ok.fetched_at) if ok else None,
            "last_status": last.status if last else None,
            "http_status": last.http_status if last else None,
            "error": last.error if last else None,
            "endpoint": endpoint_label(last.request_url) if last else None,
        }
    return out


def _times(db: Session) -> tuple[datetime | None, datetime | None, datetime | None]:
    """(newest cache row, oldest per-feed last success or None, newest attempt)."""
    newest_cache = db.scalar(select(func.max(NasaWeatherCache.fetched_at)))
    successes: list[datetime | None] = []
    for feed in FEEDS:
        successes.append(db.scalar(select(func.max(ExternalDataSnapshot.fetched_at)).where(
            ExternalDataSnapshot.source == SNAPSHOT_SOURCE, ExternalDataSnapshot.feed == feed, ExternalDataSnapshot.status == "OK")))
    all_success = min(successes) if all(successes) else None  # type: ignore[type-var]
    last_attempt = db.scalar(select(func.max(ExternalDataSnapshot.fetched_at)).where(ExternalDataSnapshot.source == SNAPSHOT_SOURCE))
    return newest_cache, all_success, last_attempt


def needs_refresh(db: Session, now: datetime | None = None) -> bool:
    now = now or _utcnow()
    newest_cache, all_success, last_attempt = _times(db)
    freshest = max((t for t in (newest_cache, all_success) if t is not None), default=None)
    if freshest is not None and now - freshest < CACHE_TTL:
        return False
    if last_attempt is not None and now - last_attempt < RETRY_AFTER_FAILURE:
        return False
    return True


def build_context(db: Session, now: datetime | None = None) -> NasaDonkiContext:
    now = now or _utcnow()
    feeds = feed_status(db)
    _, all_success, _ = _times(db)
    live = all(
        f["last_status"] == "OK" and f["last_success"] is not None
        and now - parse_donki_time(f["last_success"]) < CACHE_TTL  # type: ignore[operator]
        for f in feeds.values()
    )
    window_start = now - timedelta(days=LOOKBACK_DAYS)
    ordered = select(NasaWeatherCache).order_by(desc(NasaWeatherCache.peak_time), desc(NasaWeatherCache.id))
    if live:
        latest = db.scalars(ordered.where(NasaWeatherCache.peak_time >= window_start).limit(1)).first()
    else:
        latest = db.scalars(ordered.limit(1)).first()
    recent = db.scalars(ordered.where(NasaWeatherCache.peak_time >= window_start).limit(10)).all()
    sep_active = db.scalars(select(NasaWeatherCache).where(
        NasaWeatherCache.event_type == "SEP", NasaWeatherCache.peak_time >= now - SEP_ACTIVE_WINDOW)).first() is not None

    placeholder = False
    if live:
        status: DonkiStatus = "LIVE"
    elif latest is not None:
        status = "CACHED_OFFLINE"
    else:
        status = "OFFLINE_BASELINE"

    if latest is not None:
        event_id, event_type, class_type = latest.event_id, latest.event_type, latest.class_type
        peak, link = latest.peak_time, latest.link
        text = describe(event_type, class_type, latest.active_region)
    elif status == "OFFLINE_BASELINE":
        placeholder = True
        event_id, event_type, class_type = OFFLINE_BASELINE_EVENT["event_id"], OFFLINE_BASELINE_EVENT["event_type"], OFFLINE_BASELINE_EVENT["class_type"]
        peak, link, text = None, None, OFFLINE_BASELINE_EVENT["latest_event"]
    else:  # LIVE with no events in the window
        event_id = event_type = class_type = None
        peak, link = None, None
        text = f"No FLR/SEP events reported in the last {LOOKBACK_DAYS} days"

    risk = classify_risk(event_type, class_type)
    if sep_active:
        risk = "WARNING"
    return {
        "status": status,
        "latest_event": text,
        "event_id": event_id,
        "event_type": event_type,
        "class_type": class_type,
        "peak_time": _iso(peak),
        "event_age_h": round((now - peak).total_seconds() / 3600, 1) if peak else None,
        "link": link,
        "space_weather_risk": risk,
        "eva_advisory": EVA_ADVISORY[risk],
        "radiation_context": RADIATION_CONTEXT[risk],
        "updated_at": _iso(now),  # type: ignore[typeddict-item]
        "last_successful_fetch": _iso(all_success),
        "is_placeholder": placeholder,
        "refresh_in_progress": _state.task is not None and not _state.task.done(),
        "feeds": feeds,
        "recent_events": [{
            "event_id": e.event_id, "event_type": e.event_type, "class_type": e.class_type,
            "peak_time": _iso(e.peak_time), "description": describe(e.event_type, e.class_type, e.active_region),
            "link": e.link, "fetched_at": _iso(e.fetched_at),
        } for e in recent],
        "source": "NASA DONKI via api.nasa.gov" + (
            " (flares from DONKI notifications: /DONKI/FLR unavailable)"
            if (feeds.get("FLR") or {}).get("endpoint") == "notifications (FLR fallback)" else ""),
        "provenance": "External space-weather context. Not an astronaut dose measurement.",
    }


async def _guarded_refresh(factory: sessionmaker) -> None:
    try:
        await refresh_cache(factory)
    except Exception as exc:  # pragma: no cover - refresh_cache never raises
        log.error("DONKI background refresh failed: %s", exc)


def schedule_refresh(db: Session, *, force: bool = False) -> bool:
    """Start one background refresh if needed. Returns True when a task was started."""
    if _state.task is not None and not _state.task.done():
        return False
    if not force and not needs_refresh(db):
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, future=True)
    _state.task = loop.create_task(_guarded_refresh(factory))
    return True


async def request_manual_refresh(db: Session) -> tuple[bool, str]:
    """Crew-initiated refresh, limited to once per minute to protect the API quota."""
    now = _utcnow()
    if _state.last_manual is not None and now - _state.last_manual < MANUAL_REFRESH_MIN_INTERVAL:
        return False, "Manual refresh is limited to once per minute (DEMO_KEY quota protection)"
    if _state.task is not None and not _state.task.done():
        return False, "A refresh is already in progress"
    _state.last_manual = now
    schedule_refresh(db, force=True)
    return True, "Refresh scheduled"


async def get_nasa_donki_context(db: Session, *, allow_fetch: bool = True) -> NasaDonkiContext:
    """Space-weather context for /api/state. Never blocks on, and never raises from, NASA."""
    try:
        if allow_fetch:
            schedule_refresh(db)
        return build_context(db)
    except Exception as exc:  # last line of defence: the state endpoint must render
        log.error("DONKI context failed: %s", exc)
        now = _iso(_utcnow()) or ""
        return {
            "status": "OFFLINE_BASELINE", "latest_event": OFFLINE_BASELINE_EVENT["latest_event"],
            "event_id": OFFLINE_BASELINE_EVENT["event_id"], "event_type": "FLR", "class_type": "C2.4",
            "peak_time": None, "event_age_h": None, "link": None, "space_weather_risk": "NOMINAL",
            "eva_advisory": EVA_ADVISORY["NOMINAL"], "radiation_context": RADIATION_CONTEXT["NOMINAL"],
            "updated_at": now, "last_successful_fetch": None, "is_placeholder": True, "refresh_in_progress": False,
            "feeds": {}, "recent_events": [], "source": "NASA DONKI via api.nasa.gov",
            "provenance": "External space-weather context. Not an astronaut dose measurement.",
        }
