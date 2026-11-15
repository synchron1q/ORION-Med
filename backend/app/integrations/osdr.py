# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""NASA Open Science Data Repository (OSDR) references.

OSDR is used as a research reference, never as a real-time telemetry feed.
Configured datasets (config/references.yaml) were inspected manually; the
service can re-check their metadata titles online and records provenance in
ExternalDataSnapshot. Failures never affect the onboard engine.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import desc, select

from app.models import ExternalDataSnapshot

if TYPE_CHECKING:
    from app.services.core import HevCore

META_URL = "https://osdr.nasa.gov/osdr/data/osd/meta/{num}"


class OsdrService:
    def __init__(self, core: "HevCore"):
        self.core = core

    def datasets(self) -> list[dict[str, Any]]:
        return list(self.core.reg.references.get("osdr_datasets") or [])

    def refresh(self, transport: httpx.BaseTransport | None = None) -> dict[str, str]:
        results: dict[str, str] = {}
        timeout = float(self.core.reg.osdr.get("request_timeout_s", 10))
        with httpx.Client(timeout=timeout, transport=transport) as client:
            for ds in self.datasets():
                acc = ds["accession"]
                num = re.sub(r"\D", "", acc)
                url = META_URL.format(num=num)
                try:
                    r = client.get(url)
                    r.raise_for_status()
                    study = r.json()["study"][acc]["studies"][0]
                    title = study.get("title", "")
                    status, err, http_status = "OK", None, r.status_code
                    payload = {"title": title, "matches_config": title.strip() == ds["title"].strip()}
                except Exception as exc:
                    status, err, payload = "ERROR", f"{type(exc).__name__}: {exc}"[:300], None
                    http_status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                with self.core.Session() as s:
                    s.add(ExternalDataSnapshot(source="NASA_OSDR", feed=acc, request_url=url, fetched_at=self.core.now(),
                                               status=status, http_status=http_status, error=err, payload=payload,
                                               record_count=1 if status == "OK" else 0))
                    s.commit()
                results[acc] = status
        return results

    def references(self) -> dict[str, Any]:
        refs = self.core.reg.references
        out = []
        with self.core.Session() as s:
            for ds in self.datasets():
                snap = s.scalars(select(ExternalDataSnapshot).where(ExternalDataSnapshot.source == "NASA_OSDR",
                                                                   ExternalDataSnapshot.feed == ds["accession"])
                                 .order_by(desc(ExternalDataSnapshot.id)).limit(1)).first()
                out.append({**ds, "online_check": None if snap is None else {
                    "status": snap.status, "checked_at": snap.fetched_at.isoformat(), "http_status": snap.http_status,
                    "matches_config": (snap.payload or {}).get("matches_config"), "error": snap.error}})
        return {"standards": refs.get("standards", []), "apis": refs.get("apis", []), "osdr_datasets": out,
                "note": "OSDR datasets are research references, not real-time spacecraft telemetry."}
