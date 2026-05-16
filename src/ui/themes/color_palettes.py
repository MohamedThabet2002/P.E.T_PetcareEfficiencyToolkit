"""
Color Palette definitions for the PET Application.
Centralizes all colors to make them easy to change globally.
"""

#====================================== IMPORTS =======================================================#

import logging
from pathlib import Path
import re
import platform

from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtCore import QSettings, QObject, pyqtSignal

from src.config import APP_NAME, ORG_NAME, SETTINGS_ORG, SETTINGS_APP

logger = logging.getLogger(__name__)

# Global cache for raw QSS templates to avoid redundant disk I/O
_QSS_TEMPLATE_CACHE = {}

#=========================================== CONSTANTS ===================================================#

PALETTES = {
    "light": {
        # --- Brand & Surface (Semantic) ---
        "brand_500": "#4A90E2",
        "bg_base": "#F5F5F5",
        "bg_surface": "#FFFFFF",
        "text_primary": "#2D3436",
        "text_secondary": "#636E72",
        "border": "#DCDDE1",
        
        # --- States & Status ---
        "state_success": "#2ECC71",
        "state_warning": "#F39C12",
        "state_danger": "#E74C3C",
        "state_info": "#3498DB",

        # --- Chart Specifics ---
        "chart_revenue": "#2ECC71",
        "chart_costs": "#E74C3C",
        "chart_net": "#3498DB",
        "chart_color_1": "#4A90E2", # Blue
        "chart_color_2": "#2ECC71", # Green
        "chart_color_3": "#F39C12", # Orange
        "chart_color_4": "#E74C3C", # Red
        "chart_color_5": "#9B59B6", # Purple
        "chart_color_6": "#1ABC9C", # Turquoise
        "stock_out": "#E74C3C", # Semantic for stock levels
        "stock_low": "#F39C12", # Semantic for stock levels
    },
    "dark": {
        "brand_500": "#4A90E2",
        "bg_base": "#121212",
        "bg_surface": "#1E1E1E",
        "text_primary": "#E0E0E0",
        "text_secondary": "#B0B0B0",
        "border": "#2E2E2E",

        "state_success": "#4CAF50",
        "state_warning": "#FFC107",
        "state_danger": "#F44336",
        "state_info": "#2196F3",

        "chart_revenue": "#66BB6A",
        "chart_costs": "#EF5350",
        "chart_net": "#42A5F5",
        "chart_color_1": "#3498DB", # Blue
        "chart_color_2": "#27AE60", # Green
        "chart_color_3": "#F2C94C", # Yellow
        "chart_color_4": "#C0392B", # Red
        "chart_color_5": "#BB86FC", # Purple
        "chart_color_6": "#26C6DA", # Turquoise
        "stock_out": "#EF5350", # Semantic for stock levels
        "stock_low": "#FFB74D", # Semantic for stock levels
    }
}

#============================================== CODE =====================================================#

class ThemeConfig:
    """Wrapper for palette dictionaries providing convenient Qt-type access."""
    def __init__(self, palette_dict: dict):
        self._palette = palette_dict

    def __getitem__(self, key):
        return self._palette.get(key)

    def get(self, key, default=None):
        return self._palette.get(key, default)

    def qcolor(self, key, default="#000000") -> QColor:
        """Returns the palette value as a QColor."""
        return QColor(self.get(key, default))

    def qbrush(self, key, default="#000000") -> QBrush:
        """Returns the palette value as a QBrush."""
        return QBrush(self.qcolor(key, default))

    def to_dict(self):
        """Returns the raw dictionary for QSS processing."""
        return self._palette.copy()

class ThemeManager(QObject):
    """Singleton manager that orchestrates theme state and notifications."""
    theme_changed = pyqtSignal(ThemeConfig)
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

def adjust_color(hex_color, brightness_factor=1.2):
    """
    Mathematically adjusts a hex color's brightness.
    factor > 1 makes it lighter, factor < 1 makes it darker.
    """
    try:
        color = QColor(hex_color)
        if brightness_factor > 1:
            return color.lighter(int(brightness_factor * 100)).name()
        else:
            # darker takes an int where 100 is original, 200 is double darkness
            return color.darker(int((2 - brightness_factor) * 100)).name()
    except Exception:
        return hex_color

def get_contrast_color(hex_color):
    """
    Calculates the luminance of a color and returns black or white for best contrast.
    Used for accessibility and readability on dynamic backgrounds.
    """
    try:
        color = QColor(hex_color)
        # Standard luminance formula: 0.299*R + 0.587*G + 0.114*B
        luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255
        return "#000000" if luminance > 0.5 else "#FFFFFF"
    except Exception:
        return "#000000"

def hex_to_rgba(hex_color, alpha):
    """Converts a hex color and alpha (0.0-1.0) to an rgba() string compatible with QSS."""
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

def is_system_dark_mode():
    """Detects if the OS is currently in Dark Mode."""
    try:
        if platform.system() == "Windows":
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
        elif platform.system() == "Darwin":  # macOS
            import subprocess
            result = subprocess.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'], 
                                     capture_output=True, text=True)
            return result.stdout.strip() == "Dark"
    except Exception:
        pass
    return False

def get_active_palette():
    """
    Returns the currently active theme palette dictionary based on user settings.
    """
    from src.utils.settings_manager import SettingsManager
    theme = str(SettingsManager.get("theme", "Light")).lower()
    settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
    
    palette = {}

    if theme == "system":
        theme = "dark" if is_system_dark_mode() else "light"
    
    if theme == "custom":
        palette = {}
        settings.beginGroup("CustomPalette")
        # Start with light defaults for any missing keys
        base = PALETTES["light"].copy()
        for key in base.keys():
            palette[key] = settings.value(key, base[key])
        settings.endGroup()
        
        # Ensure hover/pressed states are calculated for custom themes
        if "brand_500" in palette:
            palette.setdefault("brand_500_hover", adjust_color(palette["brand_500"], 0.9))
            palette.setdefault("brand_500_pressed", adjust_color(palette["brand_500"], 0.8))

    if theme != "custom":
        palette = PALETTES.get(theme, PALETTES["light"]).copy()
    
    return ThemeConfig(palette)

def get_styled_qss(file_path, theme="light", custom_palette=None, refresh_cache=False):
    """Reads a QSS file and replaces @variables with palette colors.
    
    Args:
        file_path: Path to the QSS stylesheet file.
        theme (str): Theme name to apply ('light', 'dark', or 'custom').
        custom_palette (dict, optional): Custom color palette for 'custom' theme.
        refresh_cache (bool): If True, re-reads the file from disk instead of using the cache.
        
    Returns:
        str: Processed QSS content with color substitutions, or empty string if error.
    """
    try:
        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.error(f"QSS file not found: {path_obj}")
            return ""

        # Use cached template if available
        if refresh_cache or str(path_obj) not in _QSS_TEMPLATE_CACHE:
            with open(path_obj, 'r', encoding='utf-8') as f:
                _QSS_TEMPLATE_CACHE[str(path_obj)] = f.read()
        
        content = _QSS_TEMPLATE_CACHE[str(path_obj)]

        # Prioritize the passed palette object (ThemeConfig or dict)
        palette = custom_palette if custom_palette is not None else PALETTES.get(theme, PALETTES["light"])

        # --- Automatic State Generation ---
        # Handle both dict and ThemeConfig input
        full_palette = palette.to_dict() if hasattr(palette, "to_dict") else palette.copy()
        
        # Automatically generate hover/pressed variations for brand and states if not provided
        for base_key in ["brand_500", "state_success", "state_danger", "state_warning", "state_info"]:
            if base_key in full_palette:
                full_palette.setdefault(f"{base_key}_hover", adjust_color(full_palette[base_key], 0.9))
                full_palette.setdefault(f"{base_key}_pressed", adjust_color(full_palette[base_key], 0.8))

        # --- Variable Injection (CSS Variable Simulation) ---
        # Injects the palette into the QSS variable block for visibility/reference
        var_lines = [f"/* @{k}: {v}; */" for k, v in full_palette.items()]
        var_block = "/* --- Injected Palette Variables --- */\n" + "\n".join(var_lines)
        content = re.sub(r"/\* @variables_start \*/.*?/\* @variables_end \*/", 
                        f"/* @variables_start */\n{var_block}\n/* @variables_end */", 
                        content, flags=re.DOTALL)

        # --- Advanced Regex Replacement with Modifiers ---
        # Matches @key, @key_contrast, or @key_aXX (alpha)
        sorted_keys = sorted(full_palette.keys(), key=len, reverse=True)
        key_pattern = "|".join(re.escape(k) for k in sorted_keys)
        
        def _var_replacer(match):
            var_name = match.group(1)
            modifier = match.group(2)
            
            if var_name not in full_palette:
                return match.group(0)
                
            base_color = full_palette[var_name]
            
            if modifier == "_contrast":
                return get_contrast_color(base_color)
            elif modifier and modifier.startswith("_a"):
                try:
                    alpha_val = int(modifier[2:]) / 100.0
                    return hex_to_rgba(base_color, alpha_val)
                except (ValueError, IndexError):
                    return base_color
            return base_color

        master_pattern = re.compile(rf"@({key_pattern})(_contrast|_a\d+)?\b")
        content = master_pattern.sub(_var_replacer, content)

        return content
    except Exception as e:
        logger.error(f"Failed to process QSS file: {e}")
        return ""