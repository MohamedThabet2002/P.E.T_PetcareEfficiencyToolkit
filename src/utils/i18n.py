import json
import os
import logging

logger = logging.getLogger(__name__)

_translations = {}
_current_lang = "en"

def load_translations(file_path, lang="en"):
    """Loads the JSON translation file into memory."""
    global _translations, _current_lang
    _current_lang = lang
    
    if not os.path.exists(file_path):
        logger.error(f"Translation file not found at: {file_path}")
        return False

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            _translations = json.load(f)
        if lang not in _translations:
            logger.warning(f"Language '{lang}' missing in translation file. Falling back to English if available.")
        logger.info(f"Loaded translations for language: {lang}")
        return True
    except json.JSONDecodeError as e:
        logger.error(f"Translation file is not valid JSON: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to load translations: {e}")
        return False

def set_language(lang):
    """Switch the current language globally."""
    global _current_lang
    _current_lang = lang

def tr(key, default=None):
    """
    Looks up a translation key. 
    Returns the translated string, or the default/key if not found.
    """
    lang_data = _translations.get(_current_lang, {})
    return lang_data.get(key, default or key)