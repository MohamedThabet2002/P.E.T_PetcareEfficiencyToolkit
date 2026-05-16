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
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from PyQt5.QtSql import QSqlDatabase

logger = logging.getLogger(__name__)



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


def _get_backup_key() -> Optional[str]:
    """Return the configured backup encryption key, if any."""
    raw = os.environ.get("PET_BACKUP_KEY")
    if raw is None:
        return None
    key = raw.strip()
    return key or None


def _key_path_for_backup(backup_path: Path) -> Path:
    """Legacy plaintext-key sidecar path (still honored on restore only)."""
    return Path(str(backup_path) + ".key")


def _encrypt_backup_bytes(data: bytes, key: str) -> bytes:
    """Encrypt backup bytes with Fernet.

    ``cryptography`` is a required dependency (no weak XOR fallback). An invalid
    Fernet key raises here rather than producing trivially-broken ciphertext.
    """
    return Fernet(key.encode("utf-8")).encrypt(data)


def _decrypt_backup_bytes(data: bytes, key: str) -> bytes:
    """Decrypt Fernet-encrypted backup bytes.

    Raises ValueError if the key is wrong or the data is not valid Fernet.
    """
    try:
        return Fernet(key.encode("utf-8")).decrypt(data)
    except InvalidToken as exc:
        raise ValueError(
            "Backup file decryption failed. The backup key is invalid or the file is corrupted."
        ) from exc


def _snapshot_db_bytes(db_path: Path) -> bytes:
    """Return a consistent copy of a SQLite database as raw bytes.

    Uses SQLite's online backup API, which folds in any committed data still in
    the write-ahead log. A plain ``read_bytes`` can silently miss that data, and
    copying the ``-wal``/``-shm`` sidecars separately both risks inconsistency
    and leaks plaintext when the backup is encrypted. Falls back to a raw copy
    only if SQLite cannot open the file at all.
    """
    try:
        import sqlite3
        import tempfile

        fd, tmp_name = tempfile.mkstemp(prefix="pet_backup_", suffix=".db")
        os.close(fd)
        try:
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(tmp_name)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            return Path(tmp_name).read_bytes()
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    except Exception:
        logger.warning(
            "SQLite online-backup snapshot failed; falling back to a raw file copy",
            exc_info=True,
        )
        return db_path.read_bytes() if db_path.exists() else b""


def load_backup_bytes(backup_file: Path) -> bytes:
    """Read a backup file, verify its checksum, and decrypt it if needed.

    Shared by ``restore_backup`` and the startup recovery path so both honor the
    exact same checksum/key rules.

    Raises:
        FileNotFoundError: if the backup file does not exist.
        ValueError: on checksum mismatch, or an encrypted backup without a key.
    """
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup not found: {backup_file}")

    checksum_file = Path(str(backup_file) + ".checksum")
    if checksum_file.exists():
        expected_sha = checksum_file.read_text(encoding="utf-8").strip()
        sha = hashlib.sha256()
        with open(backup_file, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha.update(chunk)
        if sha.hexdigest() != expected_sha:
            raise ValueError("Backup file integrity check failed! Checksum mismatch.")

    data = backup_file.read_bytes()

    # Backward compat: a legacy `.key` sidecar still grants the key.
    backup_key = None
    key_file = _key_path_for_backup(backup_file)
    if key_file.exists():
        backup_key = key_file.read_text(encoding="utf-8").strip() or None
    if backup_key is None:
        backup_key = _get_backup_key()

    if backup_key:
        # Fernet raises InvalidToken -> ValueError if the data isn't valid
        # Fernet (e.g. a plaintext file passed with a key), so we never
        # silently corrupt a plaintext backup when a key is wrongly set.
        return _decrypt_backup_bytes(data, backup_key)

    if data.startswith(b"gAAAA"):  # Fernet token prefix
        # Looks like ciphertext but no key was supplied — fail loudly rather
        # than write garbage back into the live database.
        raise ValueError(
            "This backup is encrypted but no PET_BACKUP_KEY is set. "
            "Provide the key used to create it before restoring."
        )

    return data


def _remove_sqlite_sidecars(db_path: Path) -> None:
    """Delete stale ``-wal``/``-shm`` files next to a database.

    A write-ahead log left over from the *previous* database must never be
    replayed onto a freshly restored file.
    """
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                logger.warning("Could not remove stale SQLite sidecar: %s", sidecar)


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

    backups_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now()

    if backup_kind != "manual":
        cutoff = now - timedelta(hours=24)
        auto_recent = [
            e for e in list_backups(backups_dir)
            if (not e.is_manual and e.timestamp >= cutoff)
        ]

        if len(auto_recent) >= auto_max_per_24h:
            auto_recent_sorted_oldest_first = sorted(auto_recent, key=lambda e: e.timestamp)
            to_delete_count = len(auto_recent_sorted_oldest_first) - (auto_max_per_24h - 1)
            to_delete = auto_recent_sorted_oldest_first[: max(0, to_delete_count)]

            for e in to_delete:
                try:
                    e.backup_path.unlink(missing_ok=True)  # type: ignore[arg-type]
                except TypeError:
                    if e.backup_path.exists():
                        e.backup_path.unlink()
                except Exception:
                    raise RuntimeError(f"Auto backup limit reached and could not delete old backup: {e.backup_path}")

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

    # Take a consistent snapshot through SQLite itself (see _snapshot_db_bytes).
    backup_bytes = _snapshot_db_bytes(db_path)

    backup_key = _get_backup_key()
    if backup_key:
        # Encrypt BEFORE the first write: if encryption fails we must never
        # leave an unencrypted copy on disk. The key is deliberately NOT stored
        # next to the backup (that would defeat the encryption); the user must
        # supply the same PET_BACKUP_KEY to restore.
        backup_bytes = _encrypt_backup_bytes(backup_bytes, backup_key)

    backup_path.write_bytes(backup_bytes)

    sha = hashlib.sha256()
    sha.update(backup_path.read_bytes())
    checksum_path = Path(str(backup_path) + ".checksum")
    checksum_path.write_text(sha.hexdigest(), encoding="utf-8")

    if backup_kind == "manual":
        manual_tag = Path(str(backup_path) + ".manual")
        manual_tag.write_text("manual", encoding="utf-8")

    logger.info("Created %s database backup: %s", backup_kind, backup_path)
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

    Safety: before restoring, verify checksum if available, then create a safety backup.
    """
    _close_qt_sqlite_connection("clinic_connection")

    # Integrity-check + decrypt up front (shared with the recovery path).
    restore_bytes = load_backup_bytes(backup_file)

    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    backups_dir.mkdir(parents=True, exist_ok=True)

    safety_backup: Optional[Path] = None
    if db_path.exists():
        safety_backup = create_backup(
            db_path=db_path,
            backups_dir=backups_dir,
            backup_kind="auto",
            now=datetime.now(),
        )
    else:
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # A write-ahead log from the previous database must not survive the swap.
    _remove_sqlite_sidecars(db_path)

    try:
        tmp_restore_path = backups_dir / ("__restoring__" + db_path.name)
        tmp_restore_path.write_bytes(restore_bytes)
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
    except Exception:
        if safety_backup and safety_backup.exists():
            try:
                safety_backup.replace(db_path)
            except Exception:
                pass
        raise
    finally:
        tmp_restore_path = backups_dir / ("__restoring__" + db_path.name)
        if tmp_restore_path.exists():
            try:
                tmp_restore_path.unlink()
            except Exception:
                pass

    logger.info("Restored database from backup: %s", backup_file)


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
