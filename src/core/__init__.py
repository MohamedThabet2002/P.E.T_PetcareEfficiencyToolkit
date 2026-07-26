"""
Core package for the PET Application.
Re-exports key functions from submodules for convenient importing.
"""

from src.core.database.connection import get_connection, get_user_db_path
from src.core.backup_manager import create_backup, list_backups, restore_backup

__all__ = [
    "get_connection",
    "get_user_db_path",
    "create_backup",
    "list_backups",
    "restore_backup",
]
