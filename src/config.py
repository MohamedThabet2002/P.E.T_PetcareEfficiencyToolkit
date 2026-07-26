import os
import sys
from pathlib import Path

#================================= METADATA =====================================#

APP_NAME = "PET"
VERSION = "1.0.0"
ORG_NAME = "Mohamed Thabet"
SETTINGS_ORG = "Petcare Efficiency Toolkit (P.E.T)"
SETTINGS_APP = "PET"

WINDOW_CONFIG = {
    "DEFAULT_SIZE": (800, 600),
    "DEFAULT_MODE": "windowed"
}

#================================ PATH SETUP ====================================#

if getattr(sys, 'frozen', False):
    # PyInstaller stores bundled data in _MEIPASS (temp folder or exe folder)
    BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    
    # Use environment variables for AppData to avoid QStandardPaths initialization race conditions
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        APP_DATA_ROOT = Path(local_app_data) / SETTINGS_ORG
    else:
        APP_DATA_ROOT = Path.home() / "AppData" / "Local" / SETTINGS_ORG
    APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR = APP_DATA_ROOT / "backups" # For frozen apps, backups go into user-writable AppData
else:
    # If running from source
    BASE_DIR = Path(__file__).resolve().parent.parent
    APP_DATA_ROOT = BASE_DIR # When running from source, use BASE_DIR for settings/logs
    BACKUPS_DIR = BASE_DIR / "backups" # For development, this is fine and convenient

ASSETS_DIR = BASE_DIR / "assets"
USER_DB_PATH = None # Will be set dynamically in database.py to a user-writable location
ICONS_DIR = ASSETS_DIR / "icons"
STYLES_DIR = ASSETS_DIR
SETTINGS_FILE = APP_DATA_ROOT / "settings.json"
LOG_FILE = APP_DATA_ROOT / "app.log"

# Ensure essential directories exist
for path in [APP_DATA_ROOT, BACKUPS_DIR]:
    path.mkdir(parents=True, exist_ok=True)

#=========================== ICONS ==============================================#

ICONS = {
    "WINDOW": "logo-ico.png",
    "MENU": "menu-ico.png",
    "DARK_MODE": "dark-mode-ico.png",
    "PROFILE": "profile-ico.png",
    "BULK_PURCHASE": "buy-ico.png"
}



#=========================== CLINIC CONFIGURATION ===============================#

DATE_FORMAT_SQL = "yyyy-MM-dd"
DATE_TIME_FORMAT_UI = "yyyy-MM-dd HH:mm"

SUPPLY_CATEGORIES = ["Meds", "Food", "Litter", "Tools"]
SUPPLY_SUB_CATEGORIES = {
    "Meds": ["Antibiotics", "Vaccines", "Painkillers", "Supplements", "Other"],
    "Food": ["Dry Food", "Wet Food", "Treats", "Prescription", "Other"],
    "Litter": ["Clumping", "Non-Clumping", "Silica", "Paper-based", "Other"],
    "Tools": ["Surgical", "Grooming", "Diagnostic", "Office", "Other"]
}
DEFAULT_LANGUAGE = "en"
DEFAULT_CLINIC_NAME = "My PET Clinic"
DEFAULT_CLINIC_OWNER = "Doctor"

# New constant for supplies.py
DEFAULT_EXPIRY_YEARS = 2

# Stock Colors for Supplies Page
STOCK_COLORS = {
    "out_of_stock": "#E74C3C",  # Red
    "low_stock": "#E67E22",     # Orange
    "text_on_highlight": "white"
}




#=========================== BUSINESS SETTINGS ==================================#

SETTING_CONSULT_FEE_LABEL = "fees/consultation_amount"
DEFAULT_CONSULT_FEE = 50.0

#=========================== BACKUP POLICIES ====================================#

# Keep all backups newer than 24 hours.
BACKUP_KEEP_24HOURS = True
# For backups older than 24 hours, keep newest backup per calendar day
# for the last N days.
BACKUP_KEEP_DAILY_DAYS = 7

# Manual backups (created via UI) are tagged via a sidecar file and
# are never deleted.
BACKUP_KEEP_MANUAL_FOREVER = True

