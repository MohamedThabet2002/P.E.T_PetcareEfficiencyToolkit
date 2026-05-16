from __future__ import annotations

import logging
from pathlib import Path

from PyQt5.QtGui import QFontDatabase

logger = logging.getLogger(__name__)


def load_bundled_fonts(fonts_dir: Path) -> list[str]:
    """Load all .ttf/.otf fonts from `fonts_dir` into the app font database.

    Returns the list of loaded font family names (best-effort).
    """
    try:
        fonts_dir = Path(fonts_dir)
    except Exception:
        return []

    if not fonts_dir.exists() or not fonts_dir.is_dir():
        return []

    loaded_families: list[str] = []
    for p in sorted(fonts_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".ttf", ".otf"}:
            continue

        try:
            font_id = QFontDatabase.addApplicationFont(str(p))
            if font_id == -1:
                logger.warning("Failed to load font: %s", p)
                continue

            families = QFontDatabase.applicationFontFamilies(font_id) or []
            loaded_families.extend([f for f in families if f])
        except Exception:
            logger.exception("Error while loading font: %s", p)

    # De-dupe but keep stable-ish order
    seen: set[str] = set()
    unique = []
    for f in loaded_families:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    if unique:
        logger.info("Loaded bundled fonts: %s", ", ".join(unique))
    return unique

