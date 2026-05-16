"""Tests for the pet health-indicator derivation and override rules."""

from src.core.health_status import (
    HEALTH_STATUS_CHOICES,
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_DIED,
    HEALTH_STATUS_DISEASED,
    HEALTH_STATUS_HEALTHY,
    HEALTH_STATUS_RECOVERING,
    HEALTH_STATUS_UNKNOWN,
    derive_health_status,
    resolve_health_status,
)


def _exam(general=None, signs=None, tests=None, physical=None):
    return {
        "generalPhysicalExamination": general or {},
        "clinicalSigns": signs or {},
        "routineTests": tests or [],
        "physicalExam": physical or {},
    }


def test_no_exam_is_unknown():
    assert derive_health_status(None) == HEALTH_STATUS_UNKNOWN
    assert derive_health_status({}) == HEALTH_STATUS_UNKNOWN


def test_plain_exam_is_healthy():
    exam = _exam(general={"temperature": {"status": "normal"}, "weight": {"condition": "normal"}})
    assert derive_health_status(exam) == HEALTH_STATUS_HEALTHY


def test_minor_abnormality_is_recovering():
    exam = _exam(general={"weight": {"condition": "overweight"}})
    assert derive_health_status(exam) == HEALTH_STATUS_RECOVERING


def test_serious_finding_is_critical():
    exam = _exam(general={"temperature": {"status": "high"}})
    assert derive_health_status(exam) == HEALTH_STATUS_CRITICAL


def test_positive_test_is_critical():
    exam = _exam(tests=[{"testName": "Parvo", "result": "positive"}])
    assert derive_health_status(exam) == HEALTH_STATUS_CRITICAL


def test_override_wins_over_derivation():
    exam = _exam(general={"temperature": {"status": "high"}})
    assert resolve_health_status(HEALTH_STATUS_HEALTHY, exam) == HEALTH_STATUS_HEALTHY


def test_manual_only_overrides_are_accepted():
    assert HEALTH_STATUS_DISEASED in HEALTH_STATUS_CHOICES
    assert HEALTH_STATUS_DIED in HEALTH_STATUS_CHOICES
    healthy_exam = _exam(general={"temperature": {"status": "normal"}})
    assert resolve_health_status(HEALTH_STATUS_DISEASED, healthy_exam) == HEALTH_STATUS_DISEASED
    assert resolve_health_status(HEALTH_STATUS_DIED, healthy_exam) == HEALTH_STATUS_DIED


def test_unknown_or_blank_override_falls_back_to_derivation():
    exam = _exam(general={"temperature": {"status": "normal"}})
    assert resolve_health_status("", exam) == HEALTH_STATUS_HEALTHY
    assert resolve_health_status(None, exam) == HEALTH_STATUS_HEALTHY
    assert resolve_health_status("Not A Status", exam) == HEALTH_STATUS_HEALTHY
    assert resolve_health_status("", None) == HEALTH_STATUS_UNKNOWN
