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

#=========================== SHARED UI STRINGS ==================================#

# --- Common Labels ---
TR_OK = "OK"
TR_CANCEL = "Cancel"
TR_ADD = "Add"
TR_EDIT = "Edit"
TR_DELETE = "Delete"
TR_YES = "Yes"
TR_NO = "No"
TR_ALL_FILTER_OPTION = "All"
TR_SEARCH = "Search"
TR_ID = "ID"
TR_DATE = "Date"
TR_STATUS = "Status"
TR_NOTES = "Notes"
TR_TYPE_COL = "Type"
TR_SUCCESS = "Success"
TR_ERROR = "Error"
TR_WARNING = "Warning"
TR_INFO_TITLE = "Information"
TR_CONFIRM_DELETE_TITLE = "Confirm Delete"
TR_INPUT_ERROR_HEADING = "Input Error"
TR_DATABASE_ERROR_HEADING = "Database Error"
TR_VALIDATION_ERROR = "Validation Error"
TR_SELECTION_REQUIRED = "Selection Required"

# --- Clinical Labels ---
TR_VISIT_ID = "Visit ID"
TR_CLIENT_ID = "Client ID"
TR_OWNER_NAME = "Owner Name"
TR_PET_NAME = "Pet Name"
TR_PHONE = "Phone Number"
TR_SPECIES = "Species"
TR_BREED = "Breed"
TR_GENDER = "Gender"
TR_AGE = "Age"
TR_WEIGHT = "Weight"
TR_DIAGNOSIS = "Diagnosis"
TR_CONSULT = "Consult"
TR_VISIT_RECORDS = "Visit Records"
TR_ANONYMOUS = "Anonymous"
TR_MALE = "Male"
TR_FEMALE = "Female"
TR_OTHER = "Other"

# dialog labels
TR_OWNER_NAME_LABEL = "Owner Name*:"
TR_PHONE_LABEL = "Phone Number:"
TR_PET_NAME_LABEL = "Pet Name*:"
TR_SPECIES_LABEL = "Species:"
TR_BREED_LABEL = "Breed:"
TR_GENDER_LABEL = "Gender:"
TR_AGE_MONTHS_LABEL = "Age (Months):"
TR_WEIGHT_LABEL = "Weight (kg):"
TR_OWNER_SELECT_LABEL = "Owner*:"

# --- Inventory & Supplies Labels ---
TR_ITEM_NAME = "Item Name"
TR_CATEGORY = "Category"
TR_SUB_CATEGORY = "Sub-Category"
TR_QUANTITY = "Quantity"
TR_BUY_PRICE = "Buy Price"
TR_SELL_PRICE = "Sell Price"
TR_SUPPLIER = "Supplier"
TR_PURCHASE_DATE = "Purchase Date"
TR_EXPIRY_DATE = "Expiry Date"
TR_QUICK_PURCHASE = "Quick Purchase"
TR_BULK_PURCHASE_TITLE = "Bulk Inventory Purchase"
TR_BULK_PURCHASE_BUTTON_LABEL = " Bulk Inventory Purchase "
TR_DELETE_SELECTED = "Delete Selected"
TR_COMMON_SUPPLIER_PLACEHOLDER = "Common Supplier (optional)"
TR_DEFAULT_SUPPLIER_LABEL = "Default Supplier:"
TR_ADD_ROW_LABEL = "+ Add Row"
TR_TOTAL_PURCHASE_LABEL = "<b>Total Purchase: ${total:,.2f}</b>"
TR_DELETE_BUTTON_SYMBOL = "✕"
TR_ITEM_NAME_REQUIRED_MSG = "Item name is required for row {row}."
TR_SUCCESS_PROCESS_MSG = "Successfully processed {count} items."
TR_ADD_SUPPLY_ITEM_TITLE = "Add {category}"
TR_SELECT_SUBCATEGORY_PLACEHOLDER = "Select Sub-Category..."
TR_SUB_CATEGORY_REQUIRED_MSG = "Sub Category is required."
TR_DUPLICATE_FOUND_TITLE = "Duplicate Found"
TR_DUPLICATE_SUPPLY_MSG = "An existing supply was found. The quantity will be added. Do you want to update the price values as well?"
TR_STOCK_UPDATED_WARNING_MSG = "Stock updated, but failed to log expense record."
TR_UPDATE_TITLE = "Update"
TR_SUCCESS_ADDED_TO_STOCK_MSG = "Successfully added {qty} to existing stock."
TR_ADDED_TO_CATEGORY_MSG = "{name} added to {category}"
TR_SELECT_SUPPLY_DELETE_MSG = "Please select a supply to delete."
TR_DELETE_SUPPLY_MSG = "Delete '{item}' from {category}?"
TR_NO_CATEGORIES_MSG = "No inventory categories found. Please add some in Settings > Custom Lists."

# dialog labels
TR_ITEM_NAME_LABEL = "Item Name*:"
TR_SUB_CATEGORY_LABEL = "Sub-Category*:"
TR_PURCHASE_DATE_LABEL = "Purchase Date:"
TR_EXPIRY_DATE_LABEL = "Expiry Date:"
TR_BUY_PRICE_LABEL = "Buy Price:"
TR_SELL_PRICE_LABEL = "Sell Price:"
TR_QUANTITY_LABEL = "Quantity:"
TR_SUPPLIER_LABEL = "Supplier:"
# --- Financial Labels ---
TR_RECEIPT_ID = "Receipt ID"
TR_PRICE = "Price"
TR_UNIT_PRICE = "Unit Price"
TR_TOTAL_ITEM_PRICE = "Total Item Price"
TR_TOTAL_PRICE = "Total Price"
TR_SERVICE = "Service"
TR_FAILED_UPDATE_STOCK_MSG = "Failed to update supply stock."
TR_FAILED_ADD_NEW_SUPPLY_MSG = "Failed to add new supply."
TR_EDIT_SUPPLY_ITEM_TITLE = "Edit {item}"

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

