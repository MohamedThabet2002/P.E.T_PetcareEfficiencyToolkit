"""Path resolution logic for the PET Application."""
import os
import sys
from pathlib import Path

#================================= METADATA =====================================#
# (only SETTINGS_ORG and SETTINGS_APP are needed for path resolution)
SETTINGS_ORG = "Petcare Efficiency Toolkit (P.E.T)"
SETTINGS_APP = "PET"

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
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
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
