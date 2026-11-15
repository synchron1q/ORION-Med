# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Spacecraft -> ground synchronization queue.

Events are queued locally (SyncQueueItem) and delivered in sequence order when
the communication link is available. Each item carries a unique item_id used as
an idempotency key, so a retried batch never creates duplicates on the ground.

Target selection:
* ORION_GROUND_SYNC_URL set  -> HTTP POST to that endpoint.
* demo mode without URL      -> in-process SIMULATED loopback ground station
                                (clearly labelled; it stores receipts in SQLite).
* otherwise                  -> LOCAL ONLY (items stay queued).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import func, select

from app.models import GroundReceipt, SyncQueueItem

if TYPE_CHECKING:
    from app.services.core import HevCore


class SyncManager:
    def __init__(self, core: "HevCore"):
        self.core = core
        cfg = core.reg.sync
        self.batch_size = int(cfg.get("batch_size", 50))
        self.max_backoff_s = float(cfg.get("max_backoff_s", 60))
        self.link_up = bool(core.get_runtime("comm.link_up", True))
        self.last_success_at: str | None = core.get_runtime("sync.last_success_at")
        self.last_error: str | None = None
        self.duplicates_ignored = 0
        url = core.settings.ground_sync_url
        self.target = "GROUND_URL" if url else ("SIMULATED_GROUND_STATION" if core.settings.demo_mode else "LOCAL_ONLY")

    def set_link(self, up: bool) -> dict[str, Any]:
        self.link_up = up
        self.core.set_runtime("comm.link_up", up)
        self.core.log("COMM", "Earth link restored (AOS)" if up else "Earth link lost (LOS) - events queued locally", "SIMULATOR")
        return self.status()

    def _deliver(self, items: list[dict[str, Any]]) -> None:
        if self.target == "GROUND_URL":
            r = httpx.post(self.core.settings.ground_sync_url, json={"mission_id": self.core.mission_id, "items": items}, timeout=5.0)
            r.raise_for_status()
            return
        with self.core.lock, self.core.Session() as s:  # SIMULATED loopback ground station
            for it in items:
                if s.get(GroundReceipt, it["item_id"]) is not None:
                    self.duplicates_ignored += 1
                    continue
                s.add(GroundReceipt(item_id=it["item_id"], received_at=self.core.now()))
            s.commit()

    def run_once(self) -> dict[str, Any]:
        if not self.link_up:
            return {"sent": 0, "reason": "LOS"}
        if self.target == "LOCAL_ONLY":
            return {"sent": 0, "reason": "LOCAL_ONLY"}
        now = self.core.now()
        with self.core.lock, self.core.Session() as s:
            batch = s.scalars(select(SyncQueueItem).where(SyncQueueItem.status == "PENDING").order_by(SyncQueueItem.seq).limit(self.batch_size)).all()
            if not batch or (batch[0].next_attempt_at is not None and batch[0].next_attempt_at > now):
                return {"sent": 0, "reason": "NOTHING_DUE"}
            payload = [{"item_id": i.item_id, "seq": i.seq, "event_type": i.event_type, "payload": i.payload,
                        "created_at": i.created_at.isoformat()} for i in batch]
            seqs = [i.seq for i in batch]
        try:
            self._deliver(payload)
        except Exception as exc:  # network / HTTP error -> retry with backoff, keep order
            self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            with self.core.lock, self.core.Session() as s:
                for item in s.scalars(select(SyncQueueItem).where(SyncQueueItem.seq.in_(seqs))):
                    item.attempts += 1
                    item.last_error = self.last_error
                    item.next_attempt_at = now + timedelta(seconds=min(self.max_backoff_s, 2 ** item.attempts))
                s.commit()
            return {"sent": 0, "reason": "ERROR", "error": self.last_error}
        with self.core.lock, self.core.Session() as s:
            for item in s.scalars(select(SyncQueueItem).where(SyncQueueItem.seq.in_(seqs))):
                item.status = "SENT"
                item.sent_at = now
                item.attempts += 1
            s.commit()
        self.last_error = None
        self.last_success_at = now.isoformat()
        self.core.set_runtime("sync.last_success_at", self.last_success_at)
        return {"sent": len(seqs)}

    def status(self) -> dict[str, Any]:
        with self.core.Session() as s:
            pending = s.scalar(select(func.count()).select_from(SyncQueueItem).where(SyncQueueItem.status == "PENDING")) or 0
            sent = s.scalar(select(func.count()).select_from(SyncQueueItem).where(SyncQueueItem.status == "SENT")) or 0
            oldest = s.scalar(select(func.min(SyncQueueItem.created_at)).where(SyncQueueItem.status == "PENDING"))
        return {
            "link_up": self.link_up,
            "target": self.target,
            "pending": pending,
            "sent": sent,
            "oldest_pending_at": oldest.isoformat() if isinstance(oldest, datetime) else None,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "duplicates_ignored": self.duplicates_ignored,
        }
