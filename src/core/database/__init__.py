"""
Database management package for the PET Application.
Handles SQLite connection lifecycle, PRAGMA settings, and schema/view initialization.
"""

from src.core.database.connection import get_connection, get_user_db_path

__all__ = ["get_connection", "get_user_db_path"]
