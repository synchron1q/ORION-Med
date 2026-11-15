# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import httpx
from sqlalchemy import func, select

from app.models import GroundReceipt, SyncQueueItem

from conftest import feed


def pending(core):
    with core.Session() as s:
        return s.scalar(select(func.count()).select_from(SyncQueueItem).where(SyncQueueItem.status == "PENDING"))


def test_queue_while_los_then_deliver_in_order(core, clock):
    core.sync.set_link(False)
    feed(core, clock, {"cabin_co2": 7.0})
    n = pending(core)
    assert n > 0 and core.sync.run_once()["reason"] == "LOS"
    assert pending(core) == n
    core.sync.set_link(True)
    total = 0
    while (r := core.sync.run_once()).get("sent"):
        total += r["sent"]
    assert pending(core) == 0
    with core.Session() as s:
        seqs = [i.seq for i in s.scalars(select(SyncQueueItem).order_by(SyncQueueItem.sent_at, SyncQueueItem.seq))]
        assert seqs == sorted(seqs)
        assert s.scalar(select(func.count()).select_from(GroundReceipt)) == total
    st = core.sync.status()
    assert st["target"] == "SIMULATED_GROUND_STATION" and st["last_success_at"]


def test_duplicate_delivery_is_ignored(core, clock):
    feed(core, clock, {"cabin_co2": 7.0})
    with core.Session() as s:
        items = [{"item_id": i.item_id} for i in s.scalars(select(SyncQueueItem))]
    core.sync._deliver(items)
    core.sync._deliver(items)
    assert core.sync.duplicates_ignored == len(items)


def test_ground_url_failure_backs_off(core, clock, monkeypatch):
    core.settings.ground_sync_url = "http://ground.invalid/sync"
    core.sync.target = "GROUND_URL"

    def fail(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", fail)
    feed(core, clock, {"cabin_co2": 7.0})
    r = core.sync.run_once()
    assert r["reason"] == "ERROR" and core.sync.status()["last_error"]
    assert core.sync.run_once()["reason"] == "NOTHING_DUE", "backoff must delay the retry"
    clock.advance(3)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200, request=httpx.Request("POST", "http://x")))
    assert core.sync.run_once()["sent"] > 0
