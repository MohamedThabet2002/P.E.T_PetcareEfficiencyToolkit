"""Business constants, icon mappings, and configuration for the PET Application."""

#=========================== CLINIC CONFIGURATION ===============================#

DATE_TIME_FORMAT_UI = "yyyy-MM-dd HH:mm"

SUPPLY_CATEGORIES = ["Meds", "Food", "Litter", "Tools"]
DEFAULT_CLINIC_NAME = "My PET Clinic"
DEFAULT_CLINIC_OWNER = "Doctor"

# New constant for supplies.py
DEFAULT_EXPIRY_YEARS = 2

#=========================== BUSINESS SETTINGS ==================================#

DEFAULT_CONSULT_FEE = 50.0

#=========================== SCHEDULING =========================================#

# How long an appointment / follow-up stays "Late" after its scheduled time
# before it is auto-canceled. Configurable from Settings > Clinic Profile.
DEFAULT_AUTO_CANCEL_HOURS = 24
AUTO_CANCEL_HOURS_MIN = 1
AUTO_CANCEL_HOURS_MAX = 720

#=========================== WINDOW CONFIG ======================================#

WINDOW_CONFIG = {
    "DEFAULT_SIZE": (1280, 720),
    "MIN_SIZE": (800, 600),
    "DEFAULT_MODE": "windowed"
}

#=========================== BACKUP POLICIES ====================================#

# Keep all backups newer than 24 hours.
BACKUP_KEEP_24HOURS = True
# For backups older than 24 hours, keep newest backup per calendar day
# for the last N days.
BACKUP_KEEP_DAILY_DAYS = 7

# Manual backups (created via UI) are tagged via a sidecar file and
# are never deleted.
BACKUP_KEEP_MANUAL_FOREVER = True
