# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Deterministic threshold evaluation with hysteresis."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Severity(IntEnum):
    NOMINAL = 0
    ADVISORY = 1
    CAUTION = 2
    WARNING = 3


@dataclass(frozen=True)
class ThresholdSet:
    advisory_high: float | None = None
    caution_high: float | None = None
    warning_high: float | None = None
    advisory_low: float | None = None
    caution_low: float | None = None
    warning_low: float | None = None
    hysteresis: float = 0.0

    def as_dict(self) -> dict[str, float]:
        keys = ("advisory_high", "caution_high", "warning_high", "advisory_low", "caution_low", "warning_low")
        return {k: getattr(self, k) for k in keys if getattr(self, k) is not None}

    def is_empty(self) -> bool:
        return not self.as_dict()

    def validate(self, name: str = "") -> None:
        highs = [v for v in (self.advisory_high, self.caution_high, self.warning_high) if v is not None]
        lows = [v for v in (self.advisory_low, self.caution_low, self.warning_low) if v is not None]
        if highs != sorted(highs):
            raise ValueError(f"{name}: high limits must increase advisory < caution < warning")
        if lows != sorted(lows, reverse=True):
            raise ValueError(f"{name}: low limits must decrease advisory > caution > warning")
        if highs and lows and min(highs) <= max(lows):
            raise ValueError(f"{name}: high and low limits overlap")
        if self.hysteresis < 0:
            raise ValueError(f"{name}: hysteresis must be >= 0")


def classify(value: float, th: ThresholdSet, margin: float = 0.0) -> Severity:
    """Return the severity band for value.

    margin > 0 shrinks the nominal band (used for recovery with hysteresis):
    a value must be inside every limit by at least `margin` to be NOMINAL.
    """
    sev = Severity.NOMINAL
    bands = (
        (th.warning_high, th.warning_low, Severity.WARNING),
        (th.caution_high, th.caution_low, Severity.CAUTION),
        (th.advisory_high, th.advisory_low, Severity.ADVISORY),
    )
    for high, low, level in bands:
        if high is not None and value >= high - margin:
            return level
        if low is not None and value <= low + margin:
            return level
    return sev


def evaluate(value: float, th: ThresholdSet, alert_open: bool) -> Severity | None:
    """Severity fed to the alert machine.

    Returns None when an alert is open and the value is back inside the limits
    but not yet past the hysteresis margin: the alert must hold its state and
    must not be reported as recovered yet.
    """
    raw = classify(value, th)
    if raw != Severity.NOMINAL or not alert_open or th.hysteresis <= 0:
        return raw
    if classify(value, th, margin=th.hysteresis) == Severity.NOMINAL:
        return Severity.NOMINAL
    return None
