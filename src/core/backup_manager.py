"""src.core.backup_manager

Database backup / restore utilities for the PET application (QtSql + SQLite).

Backup policy implemented:
- Keep all backups newer than last 24 hours
- For backups older than 24 hours: keep only newest backup per calendar day
  for the last N days (default: 7)
- Manual backups are never deleted (tagged via sidecar file "<backup>.manual")

Filenames:
- Backups are timestamped: Database_YYYYmmdd_HHMMSS.db
- Manual backups are tagged by presence of sidecar file: Database_...db.manual

Restore:
- Creates a safety backup before replacing the DB.
"""

from __future__ import annotations
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from PyQt5.QtSql import QSqlDatabase



@dataclass(frozen=True)
class BackupEntry:
    backup_path: Path
    timestamp: datetime
    is_manual: bool

    @property
    def sidecar_manual_path(self) -> Path:
        return Path(str(self.backup_path) + ".manual")


# Example: Database_20260101_235959.db
_FILENAME_PREFIX = "Database_"
_EXTENSION = ".db"


def _parse_backup_timestamp(filename: str) -> Optional[datetime]:
    """Parse timestamp from backup filename.

    Returns None if filename doesn't match expected pattern.
    """
    if not filename.startswith(_FILENAME_PREFIX) or not filename.endswith(_EXTENSION):
        return None

    ts_part = filename[len(_FILENAME_PREFIX) : -len(_EXTENSION)]
    # Expected: YYYYmmdd_HHMMSS
    try:
        return datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _iter_backup_files(backups_dir: Path) -> Iterable[Path]:
    if not backups_dir.exists():
        return []

    # only consider .db files
    return (p for p in backups_dir.iterdir() if p.is_file() and p.name.endswith(_EXTENSION))


def list_backups(backups_dir: Path) -> List[BackupEntry]:
    """List backups sorted by newest first."""
    entries: List[BackupEntry] = []

    for p in _iter_backup_files(backups_dir):
        ts = _parse_backup_timestamp(p.name)
        if ts is None:
            continue
        is_manual = Path(str(p) + ".manual").exists()
        entries.append(BackupEntry(backup_path=p, timestamp=ts, is_manual=is_manual))

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries


def create_backup(
    db_path: Path,
    backups_dir: Path,
    backup_kind: str = "auto",  # "auto" | "manual"
    now: Optional[datetime] = None,
    auto_max_per_24h: int = 10,
) -> Path:
    """Create a database backup.

    Args:
        db_path: path to current SQLite db (Database.db)
        backups_dir: directory where backups are stored
        backup_kind: "auto" or "manual".
        now: timestamp override (useful for testing)

    Returns:
        Path to the created backup file.

    Raises:
        FileNotFoundError: if db_path doesn't exist
        IOError: if copying fails
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # Enforce auto-backup quota (manual backups are always allowed)
    backups_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()

    if backup_kind != "manual":
        # Count existing auto backups in last 24h (based on filename timestamp)
        cutoff = now - timedelta(hours=24)
        auto_recent = [
            e for e in list_backups(backups_dir)
            if (not e.is_manual and e.timestamp >= cutoff)
        ]

        if len(auto_recent) >= auto_max_per_24h:
            # Make room: delete oldest AUTO backups within the last 24h window.
            # We want to be able to create *one more* auto backup.
            auto_recent_sorted_oldest_first = sorted(auto_recent, key=lambda e: e.timestamp)
            to_delete_count = len(auto_recent_sorted_oldest_first) - (auto_max_per_24h - 1)
            to_delete = auto_recent_sorted_oldest_first[: max(0, to_delete_count)]

            for e in to_delete:
                try:
                    # Python 3.8+: Path.unlink(missing_ok=...)
                    e.backup_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                except TypeError:
                    # Python 3.7 compatibility: no missing_ok kwarg
                    if e.backup_path.exists():
                        e.backup_path.unlink()
                except Exception:
                    # If we can't delete, abort and let UI warn.
                    raise RuntimeError(f"Auto backup limit reached and could not delete old backup: {e.backup_path}")

            # Recount after deletion; if still at/above quota, abort.
            auto_recent_after = [
                e for e in list_backups(backups_dir)
                if (not e.is_manual and e.timestamp >= cutoff)
            ]
            if len(auto_recent_after) >= auto_max_per_24h:
                raise RuntimeError(
                    f"Auto backup quota reached ({auto_max_per_24h} backups per 24 hours) and pruning could not free space."
                )


    backup_name = f"Database_{now.strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = backups_dir / backup_name

    # Close/open handling is managed by app; we just copy the file.
    #
    # WAL hardening:
    # - In WAL mode, latest changes may exist in separate db-wal/db-shm files.
    # - We first checkpoint to reduce the chance the -wal contains unmerged pages.
    # - Then we copy db, and if they exist also copy db-wal and db-shm
    #   so the backup can be restored more accurately.
    try:
        import sqlite3
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        cur.execute('PRAGMA foreign_keys = ON;')
        cur.execute('PRAGMA wal_checkpoint(FULL)')
        con.close()
    except Exception:
        # Best-effort only; backup should still proceed even if checkpoint fails.
        pass

    shutil.copy2(str(db_path), str(backup_path))

    # Copy WAL side files if present.
    # These names are derived from the sqlite db filename.
    try:
        wal_path = Path(str(db_path) + "-wal")
        shm_path = Path(str(db_path) + "-shm")

        if wal_path.exists():
            shutil.copy2(str(wal_path), str(backup_path) + "-wal")
        if shm_path.exists():
            shutil.copy2(str(shm_path), str(backup_path) + "-shm")
    except Exception:
        # Sidecar WAL copies are best-effort.
        pass

    if backup_kind == "manual":
        # sidecar tag file
        manual_tag = Path(str(backup_path) + ".manual")
        manual_tag.write_text("manual", encoding="utf-8")

    return backup_path


def _close_qt_sqlite_connection(connection_name: str = "clinic_connection") -> None:
    """Best-effort: close and remove an existing Qt SQL connection.

    This releases SQLite file locks on Windows so `replace()` can succeed.
    """
    try:
        if QSqlDatabase.contains(connection_name):
            conn = QSqlDatabase.database(connection_name)
            try:
                conn.close()
            except Exception:
                pass
            try:
                QSqlDatabase.removeDatabase(connection_name)
            except Exception:
                pass
    except Exception:
        # Never fail restore due to inability to close.
        pass


def restore_backup(db_path: Path, backup_file: Path, backups_dir: Path) -> None:
    """Restore a backup into the working DB.

    Safety: before restoring, create a safety backup of the current db.
    """
    _close_qt_sqlite_connection("clinic_connection")

    if not backup_file.exists():
        raise FileNotFoundError(f"Backup not found: {backup_file}")
    if not db_path.exists():
        # If DB missing, still restore.
        db_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure backups dir exists
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Safety backup (auto)
    # Use now-based backup; if copy fails, we still might want restore to fail.
    create_backup(db_path=db_path, backups_dir=backups_dir, backup_kind="auto")

    # Replace db
    tmp_restore_path = backups_dir / ("__restoring__" + db_path.name)

    shutil.copy2(str(backup_file), str(tmp_restore_path))

    # Atomically replace where possible. On Windows, SQLite/Qt may keep a transient lock.
    last_err: Exception | None = None
    for _ in range(10):
        try:
            tmp_restore_path.replace(db_path)
            last_err = None
            break
        except PermissionError as e:
            last_err = e
            time.sleep(0.2)

    if last_err is not None:
        raise last_err


def prune_backups(
    backups_dir: Path,
    now: Optional[datetime] = None,
    keep_24h: bool = True,
    keep_daily_days: int = 7,
    keep_manual_forever: bool = True,
) -> Tuple[int, List[Path]]:
    """Prune old backups according to the policy.

    Returns:
        (deleted_count, deleted_paths)
    """
    now = now or datetime.now()

    entries = list_backups(backups_dir)
    if not entries:
        return 0, []

    # Always keep manual
    manual_entries = [e for e in entries if e.is_manual] if keep_manual_forever else []
    keep_set = {e.backup_path for e in manual_entries}

    if keep_24h:
        cutoff_24h = now - timedelta(hours=24)
        for e in entries:
            if e.timestamp >= cutoff_24h:
                keep_set.add(e.backup_path)

    # For older-than-24h backups: keep newest per day for last keep_daily_days days.
    # Define the day window as the local dates ending today-1? The request says:
    # "last 7 days" and keep one backup of each day which is the last backup on that day.
    # We'll interpret as: for each calendar date in [today-(keep_daily_days-1) .. today],
    # keep newest backup for that date (if backup exists), but only considering backups older than 24h.

    # Create list of candidate entries older than 24h (if keep_24h), else all.
    if keep_24h:
        older_than_24h = [e for e in entries if e.timestamp < (now - timedelta(hours=24))]
    else:
        older_than_24h = entries

    start_day = (now.date() - timedelta(days=keep_daily_days - 1))
    end_day = now.date()

    # Newest per day among older_than_24h
    newest_per_day: dict[datetime.date, BackupEntry] = {}
    for e in older_than_24h:
        d = e.timestamp.date()
        if d < start_day or d > end_day:
            continue
        # entries are sorted newest first, but we shouldn't rely on that
        # keep the max timestamp
        existing = newest_per_day.get(d)
        if existing is None or e.timestamp > existing.timestamp:
            newest_per_day[d] = e

    for e in newest_per_day.values():
        keep_set.add(e.backup_path)

    # Delete everything not in keep_set
    deleted: List[Path] = []
    for e in entries:
        if e.backup_path in keep_set:
            continue
        # delete backup file
        try:
            e.backup_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except TypeError:
            # Python<3.8 compatibility fallback
            if e.backup_path.exists():
                e.backup_path.unlink()

        # delete sidecar if exists (but keep_set manual would have prevented)
        tag = e.sidecar_manual_path
        if tag.exists():
            try:
                tag.unlink()
            except Exception:
                pass

        deleted.append(e.backup_path)

    return len(deleted), deleted
