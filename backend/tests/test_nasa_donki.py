# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.integrations import nasa_donki as nd
from app.models import ExternalDataSnapshot, NasaWeatherCache

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
FLR = [{"flrID": "2026-11-12T08:10:00-FLR-001", "classType": "M4.2", "peakTime": "2026-11-12T08:31Z",
        "beginTime": "2026-11-12T08:10Z", "activeRegionNum": 3889, "link": "https://example/flr"}]
SEP = [{"sepID": "2026-11-10T02:00:00-SEP-001", "eventTime": "2026-11-10T02:00Z", "link": "https://example/sep"}]


@pytest.fixture(autouse=True)
def reset_state():
    nd._state.task = None
    nd._state.last_manual = None


def transport(flr=FLR, sep=SEP, status=200, exc=None):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if exc:
            raise exc
        feed = request.url.path.rsplit("/", 1)[-1]
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return httpx.Response(200, json=flr if feed == "FLR" else sep)

    t = httpx.MockTransport(handler)
    t.calls = calls  # type: ignore[attr-defined]
    return t


def refresh(core, t, now=NOW):
    return asyncio.run(nd.refresh_cache(core.Session, now=now, transport=t))


def test_request_format(core):
    t = transport()
    assert refresh(core, t) == {"FLR": "OK", "SEP": "OK"}
    urls = [str(r.url) for r in t.calls]
    assert any("/DONKI/FLR" in u for u in urls) and any("/DONKI/SEP" in u for u in urls)
    assert all("startDate=2026-11-07" in u and "api_key=" in u for u in urls)
    with core.Session() as s:
        snaps = s.scalars(select(ExternalDataSnapshot)).all()
        assert all("api_key=***" in x.request_url for x in snaps), "API key must never be stored"


def test_live_tier_and_mapping(core):
    refresh(core, transport(sep=[]))
    with core.Session() as s:
        ctx = nd.build_context(s, NOW + timedelta(minutes=1))
        rows = s.scalars(select(NasaWeatherCache)).all()
    assert ctx["status"] == "LIVE"
    assert ctx["latest_event"] == "Solar Flare M4.2 (Region AR3889)"
    assert ctx["space_weather_risk"] == "CAUTION" and ctx["eva_advisory"] == "MONITOR RADIATION"
    assert ctx["class_type"] == "M4.2" and ctx["peak_time"] == "2026-11-12T08:31:00Z"
    assert "dosimeter" in ctx["radiation_context"]
    assert rows[0].event_id == FLR[0]["flrID"] and rows[0].fetched_at == NOW


def test_recent_sep_is_warning(core):
    sep = [{"sepID": "S-1", "eventTime": "2026-11-14T06:00Z"}]
    refresh(core, transport(flr=[], sep=sep))
    with core.Session() as s:
        ctx = nd.build_context(s, NOW)
    assert ctx["latest_event"] == "SEP Event Detected" and ctx["space_weather_risk"] == "WARNING"
    assert ctx["eva_advisory"] == "EVA HOLD RECOMMENDED"


@pytest.mark.parametrize("event_type,cls,risk", [("FLR", "X1.1", "WARNING"), ("FLR", "M1.0", "CAUTION"),
                                                 ("FLR", "C2.4", "NOMINAL"), ("SEP", "SEP_EVENT", "WARNING"),
                                                 (None, None, "NOMINAL")])
def test_risk_mapping(event_type, cls, risk):
    assert nd.classify_risk(event_type, cls) == risk


def test_cached_offline_on_429(core):
    refresh(core, transport())
    later = NOW + timedelta(minutes=20)
    assert refresh(core, transport(status=429), now=later) == {"FLR": "ERROR", "SEP": "ERROR"}
    with core.Session() as s:
        ctx = nd.build_context(s, later)
    assert ctx["status"] == "CACHED_OFFLINE"
    assert ctx["latest_event"].startswith("Solar Flare M4.2")
    assert ctx["feeds"]["FLR"]["http_status"] == 429 and ctx["feeds"]["FLR"]["last_success"] == "2026-11-14T12:00:00Z"


def test_offline_baseline_when_network_down_and_cache_empty(core):
    res = refresh(core, transport(exc=httpx.ConnectError("no route to Earth")))
    assert res == {"FLR": "ERROR", "SEP": "ERROR"}
    with core.Session() as s:
        ctx = nd.build_context(s, NOW)
    assert ctx["status"] == "OFFLINE_BASELINE" and ctx["is_placeholder"]
    assert ctx["class_type"] == "C2.4" and ctx["event_type"] == "FLR"
    assert "not a NASA observation" in ctx["latest_event"]
    assert ctx["space_weather_risk"] == "NOMINAL"


def test_timeout_is_caught(core):
    res = refresh(core, transport(exc=httpx.ReadTimeout("slow")))
    assert res == {"FLR": "ERROR", "SEP": "ERROR"}


def test_empty_success_is_live_and_fresh(core):
    refresh(core, transport(flr=[], sep=[]))
    with core.Session() as s:
        ctx = nd.build_context(s, NOW + timedelta(minutes=5))
        assert not nd.needs_refresh(s, NOW + timedelta(minutes=5)), "empty success must count toward TTL"
    assert ctx["status"] == "LIVE" and "No FLR/SEP events" in ctx["latest_event"]


def test_ttl_and_failure_backoff(core):
    with core.Session() as s:
        assert nd.needs_refresh(s, NOW)
    refresh(core, transport())
    with core.Session() as s:
        assert not nd.needs_refresh(s, NOW + timedelta(minutes=14))
        assert nd.needs_refresh(s, NOW + timedelta(minutes=16))
    t2 = NOW + timedelta(minutes=16)
    refresh(core, transport(status=503), now=t2)
    with core.Session() as s:
        assert not nd.needs_refresh(s, t2 + timedelta(minutes=4)), "retry backoff after failure"
        assert nd.needs_refresh(s, t2 + timedelta(minutes=6))


def test_partial_feed_failure(core):
    def handler(request):
        if request.url.path.endswith("FLR"):
            return httpx.Response(500, json={"status": 500})
        return httpx.Response(200, json=[])

    asyncio.run(nd.refresh_cache(core.Session, now=NOW, transport=httpx.MockTransport(handler)))
    with core.Session() as s:
        ctx = nd.build_context(s, NOW)
        assert s.scalar(select(func.count()).select_from(NasaWeatherCache)) == 0
    assert ctx["status"] == "OFFLINE_BASELINE"
    assert ctx["feeds"]["FLR"]["http_status"] == 500 and ctx["feeds"]["SEP"]["last_status"] == "OK"


def test_upsert_does_not_duplicate(core):
    refresh(core, transport())
    refresh(core, transport(), now=NOW + timedelta(minutes=20))
    with core.Session() as s:
        assert s.scalar(select(func.count()).select_from(NasaWeatherCache)) == 2


def test_context_never_raises(core, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(nd, "build_context", boom)
    with core.Session() as s:
        ctx = asyncio.run(nd.get_nasa_donki_context(s, allow_fetch=False))
    assert ctx["status"] == "OFFLINE_BASELINE" and ctx["is_placeholder"]


def test_donki_never_raises_alerts_or_changes_scenario(core):
    refresh(core, transport(flr=[{"flrID": "X", "classType": "X9.0", "peakTime": "2026-11-14T11:00Z"}], sep=[]))
    core.tick_monitor()
    assert core.list_alerts() == [] or all(a["kind"] != "THRESHOLD" for a in core.list_alerts())
    assert core.simulator.scenario == "nominal"


# ---------------------------------------------------------------- FLR fallback
_HDR = "## Community Coordinated Modeling Center Database Of Notifications, Knowledge, Information ( CCMC DONKI )\n## Summary:\n\n"
NOTIFS = [
    {"messageType": "FLR", "messageID": "20261113-AL-001", "messageIssueTime": "2026-11-13T09:41Z", "messageURL": "https://example/a1",
     "messageBody": _HDR + "Significant flare detected by GOES.  Flare intensity has crossed the threshold of M5.0.\n\nFlare M5.0 crossing time: 2026-11-13T09:37Z. \n"},
    {"messageType": "FLR", "messageID": "20261113-AL-002", "messageIssueTime": "2026-11-13T09:51Z", "messageURL": "https://example/a2",
     "messageBody": _HDR + "Significant flare detected by GOES.\n\nFlare start time: 2026-11-13T09:32Z. \n\nFlare peak time: 2026-11-13T09:42Z.\n\n"
                    "Flare intensity: M8.1 class.\n\nSource region: N05E80 (Active Region 14513) (based on SDO imagery).\n\n"
                    "Activity ID: 2026-11-13T09:32:00-FLR-001.\n"},
    {"messageType": "FLR", "messageID": "20261110-AL-001", "messageIssueTime": "2026-11-10T03:00Z", "messageURL": "https://example/a3",
     "messageBody": _HDR + "Flare intensity has crossed the threshold of X1.0.\n\nFlare X1.0 crossing time: 2026-11-10T02:55Z.\n"},
    {"messageType": "CME", "messageID": "ignored", "messageBody": "Flare intensity: X9.9 class."},
]


def test_parse_flr_notifications():
    rows = {r["event_id"]: r for r in nd.parse_flr_notifications(NOTIFS)}
    detailed = rows["2026-11-13T09:32:00-FLR-001"]
    assert detailed["class_type"] == "M8.1" and detailed["active_region"] == "14513"
    assert detailed["peak_time"] == datetime(2026, 11, 13, 9, 42, tzinfo=timezone.utc)
    assert "NOTIF-20261113-AL-001" not in rows, "threshold notice of the same flare is deduplicated"
    assert rows["NOTIF-20261110-AL-001"]["class_type"] == "X1.0+"
    assert len(rows) == 2
    assert nd.describe("FLR", "X1.0+", None) == "Solar Flare >=X1.0 (DONKI threshold alert)"
    assert nd.classify_risk("FLR", "X1.0+") == "WARNING" and nd.classify_risk("FLR", "M5.0+") == "CAUTION"


def fallback_transport(flr_status=404, notif_status=200, notifs=NOTIFS):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path.endswith("/FLR"):
            return httpx.Response(flr_status, json={"status": flr_status})
        if path.endswith("/notifications"):
            return httpx.Response(notif_status, json=notifs if notif_status == 200 else {"error": "x"})
        return httpx.Response(200, json=[])

    t = httpx.MockTransport(handler)
    t.calls = calls  # type: ignore[attr-defined]
    return t


def test_flr_404_uses_notifications_and_is_live(core):
    t = fallback_transport()
    assert refresh(core, t) == {"FLR": "OK", "SEP": "OK"}
    notif = [r for r in t.calls if r.url.path.endswith("/notifications")]
    assert len(notif) == 1 and notif[0].url.params["type"] == "FLR"
    assert notif[0].url.params["startDate"] == "2026-11-07" and notif[0].url.params["endDate"] == "2026-11-14"
    with core.Session() as s:
        ctx = nd.build_context(s, NOW)
        snap = s.scalars(select(ExternalDataSnapshot).where(ExternalDataSnapshot.feed == "FLR")).one()
    assert "api_key=***" in snap.request_url and "/notifications" in snap.request_url
    assert ctx["status"] == "LIVE"
    assert ctx["latest_event"] == "Solar Flare M8.1 (Region AR14513)" and ctx["space_weather_risk"] == "CAUTION"
    assert ctx["feeds"]["FLR"]["endpoint"] == "notifications (FLR fallback)"
    assert ctx["feeds"]["SEP"]["endpoint"] == "SEP"
    assert "notifications" in ctx["source"]


def test_no_fallback_on_rate_limit(core):
    t = fallback_transport(flr_status=429)
    assert refresh(core, t)["FLR"] == "ERROR"
    assert not any(r.url.path.endswith("/notifications") for r in t.calls), "429 must not spend more quota"


def test_fallback_failure_is_recorded(core):
    assert refresh(core, fallback_transport(notif_status=503))["FLR"] == "ERROR"
    with core.Session() as s:
        ctx = nd.build_context(s, NOW)
    assert ctx["feeds"]["FLR"]["http_status"] == 503 and ctx["feeds"]["FLR"]["endpoint"] == "notifications (FLR fallback)"
    assert ctx["status"] == "OFFLINE_BASELINE"
