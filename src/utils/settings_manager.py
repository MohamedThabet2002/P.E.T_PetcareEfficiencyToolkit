import json
import logging

from src.config import SETTINGS_FILE, DEFAULT_CLINIC_NAME, DEFAULT_CLINIC_OWNER

logger = logging.getLogger(__name__)

class SettingsManager:
    """Centralized manager for application settings stored in JSON.
    
    Provides methods to load, save, and access application settings with
    automatic defaults for missing keys.
    """
    
    _cache = None
    
    _defaults = {
        "language": "en",
        "theme": "light",
        "clinic_name": DEFAULT_CLINIC_NAME,
        "user_name": DEFAULT_CLINIC_OWNER,
        "custom_logo": "",

        "window_mode": "windowed",
        "dev_mode": False
    }

    @classmethod
    def load(cls):
        """Loads settings from file or returns defaults.
        
        Returns:
            dict: Settings dictionary with all keys present.
        """
        if cls._cache is not None:
            return cls._cache.copy()

        if not SETTINGS_FILE.exists():
            cls._cache = cls._defaults.copy()
        else:
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    cls._cache = {**cls._defaults, **data}
            except Exception as e:
                logger.error(f"Failed to load settings from {SETTINGS_FILE}: {e}")
                cls._cache = cls._defaults.copy()
        
        return cls._cache.copy()

    @classmethod
    def save(cls, settings_dict):
        """Persists settings dictionary to the JSON file.
        
        Args:
            settings_dict (dict): Settings to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings_dict, f, indent=4)
            cls._cache = settings_dict.copy()
            return True
        except Exception as e:
            logger.error(f"Failed to save settings to {SETTINGS_FILE}: {e}")
            return False

    @classmethod
    def get(cls, key, default=None):
        """Retrieves a setting value.
        
        Args:
            key (str): Setting key to retrieve.
            default: Default value if key is not found.
            
        Returns:
            Value of the setting or default.
        """
        return cls.load().get(key, default)

    @classmethod
    def set(cls, key, value):
        """Updates and persists a single setting.
        
        Args:
            key (str): Setting key to update.
            value: Value to set.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        settings = cls.load()
        settings[key] = value
        return cls.save(settings)