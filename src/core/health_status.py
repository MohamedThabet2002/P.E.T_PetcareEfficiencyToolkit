"""Derives a pet's current health indicator from its latest record-book exam.

The indicator is intentionally coarse - it answers "how is this pet right now?"
(Healthy / Recovering / Critical) rather than restating the exam. Staff may
override the derived value per pet (``pets.health_status``); an empty override
means "use the derivation".

Tokens are stored/compared in English; the UI translates them for display.
"""

#============================================== CODE =====================================================#

HEALTH_STATUS_HEALTHY = "Healthy"
HEALTH_STATUS_RECOVERING = "Recovering"
HEALTH_STATUS_CRITICAL = "Critical"
HEALTH_STATUS_UNKNOWN = "Unknown"

# Derivable values (what ``derive_health_status`` can ever return).
HEALTH_STATUS_VALUES = (
    HEALTH_STATUS_HEALTHY,
    HEALTH_STATUS_RECOVERING,
    HEALTH_STATUS_CRITICAL,
)

# Manual-only overrides (never derived from an exam).
HEALTH_STATUS_DISEASED = "Diseased"
HEALTH_STATUS_DIED = "Died"
HEALTH_STATUS_MANUAL_VALUES = (
    HEALTH_STATUS_DISEASED,
    HEALTH_STATUS_DIED,
)

# The values a manual override may hold ("" = automatic derivation).
HEALTH_STATUS_CHOICES = HEALTH_STATUS_VALUES + HEALTH_STATUS_MANUAL_VALUES

# Tokens that mark a serious finding on their own.
_CRITICAL_TEMPERATURE = ("low", "high")
_CRITICAL_APPETITE_STATES = ("none",)

# Tokens that mark a non-serious abnormality.
_ABNORMAL_SIGN_STATES = ("increased", "decreased", "none")
_ABNORMAL_WEIGHT = ("underweight", "overweight")
_ABNORMAL_GINGIVITIS = ("mild", "moderate", "severe")


def derive_health_status(exam):
    """Maps a ``clinical_exam_repo.get_clinical_exam`` dict to a status token.

    Returns ``Unknown`` when there is no exam, ``Critical`` when a serious
    finding is present, ``Recovering`` when only minor abnormalities are
    present, otherwise ``Healthy``.
    """
    if not exam:
        return HEALTH_STATUS_UNKNOWN
    if _has_critical_finding(exam):
        return HEALTH_STATUS_CRITICAL
    if _has_abnormality(exam):
        return HEALTH_STATUS_RECOVERING
    return HEALTH_STATUS_HEALTHY


def resolve_health_status(override, exam):
    """The effective status: a non-empty manual override wins over derivation."""
    override = (override or "").strip()
    if override in HEALTH_STATUS_CHOICES:
        return override
    return derive_health_status(exam)


def _has_critical_finding(exam):
    signs = exam.get("clinicalSigns") or {}
    general = exam.get("generalPhysicalExamination") or {}

    temperature = (general.get("temperature") or {}).get("status")
    if temperature in _CRITICAL_TEMPERATURE:
        return True

    if (signs.get("vomiting") or {}).get("present"):
        return True

    for key in ("appetite", "waterIntake", "urination"):
        if signs.get(key) in _CRITICAL_APPETITE_STATES:
            return True

    if any(t.get("result") == "positive" for t in (exam.get("routineTests") or [])):
        return True

    physical = exam.get("physicalExam") or {}
    mouth = physical.get("mouthTeethGums") or {}
    if mouth.get("gingivitisSeverity") == "severe":
        return True

    return False


def _has_abnormality(exam):
    signs = exam.get("clinicalSigns") or {}
    general = exam.get("generalPhysicalExamination") or {}
    weight = general.get("weight") or {}

    if weight.get("condition") in _ABNORMAL_WEIGHT:
        return True

    for key in ("energy", "appetite", "waterIntake", "urination"):
        if signs.get(key) in _ABNORMAL_SIGN_STATES:
            return True

    if (signs.get("feces") or {}).get("status") == "abnormal":
        return True

    for key in ("coughing", "sneezing"):
        if (signs.get(key) or {}).get("present"):
            return True

    physical = exam.get("physicalExam") or {}
    heart = physical.get("heart") or {}
    if heart.get("normal") is False:
        return True
    murmur = heart.get("murmur") or {}
    if murmur.get("left") or murmur.get("right"):
        return True
    if heart.get("rateCategory") in ("slow", "fast"):
        return True

    for key in ("lungs", "eyes", "ears", "noseAndThroat", "abdomen",
                "musculoskeletal", "skinHairCoat"):
        system = physical.get(key) or {}
        if system.get("normal") is False:
            return True
        if system.get("findings") or system.get("conditions"):
            return True

    mouth = physical.get("mouthTeethGums") or {}
    if mouth.get("normal") is False or mouth.get("conditions"):
        return True
    if mouth.get("gingivitisSeverity") in _ABNORMAL_GINGIVITIS:
        return True

    return False
