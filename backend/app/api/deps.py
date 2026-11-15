# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.services.core import HevCore


def get_core(request: Request) -> HevCore:
    return request.app.state.core


def get_db(request: Request) -> Iterator[Session]:
    core: HevCore = request.app.state.core
    with core.Session() as session:
        yield session
