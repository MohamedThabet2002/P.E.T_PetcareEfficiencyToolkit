"""Derived status resolution for scheduled records (appointments / follow-ups).

The stored status of a scheduled record is only ever one of the explicit
vocabulary values (``Pending`` / ``Completed`` / ``Canceled``).  The *display*
status is derived from it plus the scheduled time:

    scheduled in the future          -> "Pending"
    past, within the cancel window   -> "Late"
    past, beyond the cancel window   -> "Canceled"

``Completed`` / ``Canceled`` are explicit and always returned as-is, and a
missing/unparseable date falls back to the stored status (or "Pending").

The window is the ``auto_cancel_after_hours`` setting
(Settings > Clinic Profile > Scheduling Rules), so it is read live here rather
than being hardcoded in each repository.
"""

from datetime import datetime, timedelta

from src.config.constants import (
    AUTO_CANCEL_HOURS_MAX,
    AUTO_CANCEL_HOURS_MIN,
    DEFAULT_AUTO_CANCEL_HOURS,
)
from src.utils.settings_manager import SettingsManager

SETTING_KEY = "auto_cancel_after_hours"

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def auto_cancel_hours():
    """Hours a record may stay "Late" before it is auto-canceled.

    Values outside the supported range (or anything unparseable, e.g. a
    hand-edited settings.json) fall back to the default / are clamped, so the
    resolver can never be given a window that disables "Late" entirely.
    """
    try:
        hours = float(SettingsManager.get(SETTING_KEY, DEFAULT_AUTO_CANCEL_HOURS))
    except (TypeError, ValueError):
        return float(DEFAULT_AUTO_CANCEL_HOURS)
    if hours != hours or hours in (float("inf"), float("-inf")):
        return float(DEFAULT_AUTO_CANCEL_HOURS)
    return float(min(max(hours, AUTO_CANCEL_HOURS_MIN), AUTO_CANCEL_HOURS_MAX))


def resolve_status(stored_status, scheduled_date_str):
    """Compute the effective status from the stored status and scheduled time.

    See the module docstring for the rules.
    """
    if stored_status in ("Completed", "Canceled"):
        return stored_status
    if not scheduled_date_str:
        return stored_status or "Pending"
    sched = None
    for fmt in _DATE_FORMATS:
        try:
            sched = datetime.strptime(str(scheduled_date_str).strip(), fmt)
            break
        except (ValueError, TypeError):
            continue
    if sched is None:
        return stored_status or "Pending"
    now = datetime.now()
    if sched > now:
        return "Pending"
    if now - sched <= timedelta(hours=auto_cancel_hours()):
        return "Late"
    return "Canceled"
