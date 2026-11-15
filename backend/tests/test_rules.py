# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import pytest

from app.engine.rules import Severity, ThresholdSet, classify, evaluate

TH = ThresholdSet(caution_high=110, warning_high=130, caution_low=45, warning_low=38, hysteresis=5)


@pytest.mark.parametrize("value,expected", [
    (72, Severity.NOMINAL), (110, Severity.CAUTION), (129.9, Severity.CAUTION), (130, Severity.WARNING),
    (45, Severity.CAUTION), (38, Severity.WARNING), (46, Severity.NOMINAL),
])
def test_classify_bands(value, expected):
    assert classify(value, TH) == expected


def test_advisory_band():
    th = ThresholdSet(advisory_low=25, caution_low=15)
    assert classify(30, th) == Severity.NOMINAL
    assert classify(20, th) == Severity.ADVISORY
    assert classify(10, th) == Severity.CAUTION


def test_hysteresis_holds_open_alert():
    assert evaluate(107, TH, alert_open=False) == Severity.NOMINAL
    assert evaluate(107, TH, alert_open=True) is None  # inside band but not past margin
    assert evaluate(104, TH, alert_open=True) == Severity.NOMINAL
    assert evaluate(112, TH, alert_open=True) == Severity.CAUTION


@pytest.mark.parametrize("kwargs", [
    {"caution_high": 130, "warning_high": 110},
    {"caution_low": 30, "warning_low": 40},
    {"caution_high": 50, "caution_low": 60},
    {"caution_high": 10, "hysteresis": -1},
])
def test_invalid_threshold_config(kwargs):
    with pytest.raises(ValueError):
        ThresholdSet(**kwargs).validate("x")
