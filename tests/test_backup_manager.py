"""Tests for src/core/backup_manager.py

These tests operate purely on the filesystem (no Qt database connection),
using sqlite3 to create a realistic SQLite file for backup/restore tests.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.backup_manager import (
    _parse_backup_timestamp,
    create_backup,
    list_backups,
    prune_backups,
    restore_backup,
)

# A valid Fernet key (32 url-safe base64 bytes), used as the PET_BACKUP_KEY.
TEST_BACKUP_KEY = "_ihQThorj6ULKowZUTOh3N_Rh16MHsG3nyDBmFUDAZs="


@pytest.fixture
def backups_dir(tmp_path):
    """Creates an empty backup directory."""
    d = tmp_path / "backups"
    d.mkdir()
    return d


@pytest.fixture
def db_file(tmp_path):
    """Creates a real SQLite database file."""
    db = tmp_path / "Database.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO test (value) VALUES ('hello')")
    conn.commit()
    conn.close()
    return db


def _make_backup(backups_dir: Path, when: datetime, is_manual: bool = False) -> Path:
    """Helper: creates a fake backup file with the standard name pattern."""
    name = f"Database_{when.strftime('%Y%m%d_%H%M%S')}.db"
    p = backups_dir / name
    p.write_bytes(b"fake-db-content")
    if is_manual:
        Path(str(p) + ".manual").write_text("manual", encoding="utf-8")
    return p


class TestParseBackupTimestamp:
    def test_valid_name(self):
        dt = _parse_backup_timestamp("Database_20260101_235959.db")
        assert dt == datetime(2026, 1, 1, 23, 59, 59)

    def test_invalid_name_returns_none(self):
        assert _parse_backup_timestamp("foo.db") is None
        assert _parse_backup_timestamp("Database_20260101.db") is None
        assert _parse_backup_timestamp("Database_20260101_999999.db") is None  # bad time
        assert _parse_backup_timestamp("Database_abcdef_ghijkl.db") is None

    def test_prefix_required(self):
        assert _parse_backup_timestamp("database_20260101_235959.db") is None

    def test_extension_required(self):
        assert _parse_backup_timestamp("Database_20260101_235959") is None


class TestListBackups:
    def test_empty_dir(self, backups_dir):
        assert list_backups(backups_dir) == []

    def test_missing_dir(self, tmp_path):
        assert list_backups(tmp_path / "does_not_exist") == []

    def test_sorts_newest_first(self, backups_dir):
        older = _make_backup(backups_dir, datetime(2026, 1, 1, 12, 0, 0))
        newer = _make_backup(backups_dir, datetime(2026, 1, 2, 12, 0, 0))
        entries = list_backups(backups_dir)
        assert [e.backup_path for e in entries] == [newer, older]

    def test_ignores_non_matching_files(self, backups_dir):
        _make_backup(backups_dir, datetime(2026, 1, 1, 12, 0, 0))
        (backups_dir / "readme.txt").write_text("x", encoding="utf-8")
        (backups_dir / "Database_.db").write_text("y", encoding="utf-8")
        assert len(list_backups(backups_dir)) == 1

    def test_manual_flag(self, backups_dir):
        auto = _make_backup(backups_dir, datetime(2026, 1, 1, 12, 0, 0), is_manual=False)
        manual = _make_backup(backups_dir, datetime(2026, 1, 2, 12, 0, 0), is_manual=True)
        by_path = {e.backup_path: e for e in list_backups(backups_dir)}
        assert by_path[auto].is_manual is False
        assert by_path[manual].is_manual is True


class TestCreateBackup:
    def test_creates_auto_backup(self, db_file, backups_dir):
        result = create_backup(db_file, backups_dir, backup_kind="auto")
        assert result.exists()
        assert result.name.startswith("Database_")
        assert list_backups(backups_dir)  # at least one entry

    def test_creates_manual_backup_with_sidecar(self, db_file, backups_dir):
        result = create_backup(db_file, backups_dir, backup_kind="manual")
        assert Path(str(result) + ".manual").exists()
        entries = list_backups(backups_dir)
        assert len(entries) == 1
        assert entries[0].is_manual is True

    def test_missing_db_raises(self, backups_dir, tmp_path):
        with pytest.raises(FileNotFoundError):
            create_backup(tmp_path / "nope.db", backups_dir)

    def test_respects_now_override(self, db_file, backups_dir):
        fixed = datetime(2026, 5, 5, 5, 5, 5)
        result = create_backup(db_file, backups_dir, now=fixed)
        assert result.name == "Database_20260505_050505.db"

    def test_auto_quota_enforced(self, db_file, backups_dir):
        # Pre-fill 10 auto backups within the last 24h window.
        base = datetime.now() - timedelta(hours=1)
        for i in range(10):
            _make_backup(backups_dir, base - timedelta(minutes=i), is_manual=False)

        # Should create one more (total 11), deleting oldest to stay at cap 10.
        result = create_backup(db_file, backups_dir, auto_max_per_24h=10)
        assert result.exists()
        assert len(list_backups(backups_dir)) == 10


class TestPruneBackups:
    def test_empty_dir(self, backups_dir):
        assert prune_backups(backups_dir) == (0, [])

    def test_keeps_recent_24h(self, backups_dir):
        now = datetime.now()
        recent1 = _make_backup(backups_dir, now - timedelta(hours=1))
        recent2 = _make_backup(backups_dir, now - timedelta(hours=6))
        old = _make_backup(backups_dir, now - timedelta(days=10))
        deleted, paths = prune_backups(backups_dir, now=now)
        assert deleted == 1
        assert paths == [old]
        assert recent1.exists()
        assert recent2.exists()

    def test_keeps_manual_forever(self, backups_dir):
        now = datetime.now()
        manual_old = _make_backup(backups_dir, now - timedelta(days=30, seconds=10), is_manual=True)
        auto_old = _make_backup(backups_dir, now - timedelta(days=30), is_manual=False)
        deleted, _ = prune_backups(backups_dir, now=now, keep_manual_forever=True)
        assert manual_old.exists()
        assert not auto_old.exists()
        assert deleted == 1
        assert deleted == 1

    def test_daily_keep_one_per_day(self, backups_dir):
        now = datetime(2026, 3, 10, 12, 0, 0)
        # Two backups on the same old day
        same_day_a = _make_backup(backups_dir, datetime(2026, 3, 5, 8, 0, 0))
        same_day_b = _make_backup(backups_dir, datetime(2026, 3, 5, 10, 0, 0))
        # One backup on another old day
        other_day = _make_backup(backups_dir, datetime(2026, 3, 6, 9, 0, 0))
        deleted, _ = prune_backups(backups_dir, now=now, keep_24h=True, keep_daily_days=7)
        assert deleted == 1  # only the earlier backup of the same day
        assert same_day_b.exists()  # newest per day kept
        assert other_day.exists()

    def test_keep_24h_false(self, backups_dir):
        now = datetime(2026, 3, 10, 12, 0, 0)
        old = _make_backup(backups_dir, now - timedelta(hours=2))
        deleted, _ = prune_backups(backups_dir, now=now, keep_24h=False, keep_daily_days=1)
        # Not within 24h protection; day window of 1 day includes today, so it's kept.
        assert deleted == 0
        assert old.exists()


class TestRestoreBackup:
    def test_restore_replaces_db(self, db_file, backups_dir):
        # Create a backup of the DB, then modify the original.
        backup = create_backup(db_file, backups_dir, backup_kind="manual", now=datetime.now() - timedelta(seconds=5))
        conn = sqlite3.connect(str(db_file))
        conn.execute("INSERT INTO test (value) VALUES ('changed')")
        conn.commit()
        conn.close()

        # Restore backup.
        restore_backup(db_file, backup, backups_dir)

        conn = sqlite3.connect(str(db_file))
        values = [r[0] for r in conn.execute("SELECT value FROM test ORDER BY id")]
        conn.close()
        assert values == ["hello"]  # original backup content restored

    def test_backup_is_encrypted_when_key_is_configured(self, db_file, backups_dir, monkeypatch):
        monkeypatch.setenv("PET_BACKUP_KEY", TEST_BACKUP_KEY)
        backup = create_backup(db_file, backups_dir, backup_kind="manual")

        assert backup.exists()
        assert backup.read_bytes() != db_file.read_bytes()
        # Key is NOT written next to the ciphertext (it must be supplied on restore).
        assert not Path(str(backup) + ".key").exists()
        assert Path(str(backup) + ".checksum").exists()

        # Confirms the stored bytes are Fernet ciphertext, not plaintext.
        assert not backup.read_bytes().startswith(b"SQLite format 3\x00")

    def test_encrypted_backup_restore_roundtrip(self, db_file, backups_dir, monkeypatch):
        """An encrypted backup restores correctly when the same key is provided."""
        key = TEST_BACKUP_KEY
        monkeypatch.setenv("PET_BACKUP_KEY", key)
        backup = create_backup(db_file, backups_dir, backup_kind="manual")
        assert not backup.read_bytes().startswith(b"SQLite format 3\x00")

        # Modify the DB, then restore.
        conn = sqlite3.connect(str(db_file))
        conn.execute("INSERT INTO test (value) VALUES ('changed')")
        conn.commit()
        conn.close()

        restore_backup(db_file, backup, backups_dir)

        conn = sqlite3.connect(str(db_file))
        values = [r[0] for r in conn.execute("SELECT value FROM test ORDER BY id")]
        conn.close()
        assert values == ["hello"]

    def test_encrypted_backup_restore_requires_key(self, db_file, backups_dir, monkeypatch):
        """Restoring an encrypted backup without the key fails loudly."""
        monkeypatch.setenv("PET_BACKUP_KEY", TEST_BACKUP_KEY)
        backup = create_backup(db_file, backups_dir, backup_kind="manual")

        monkeypatch.delenv("PET_BACKUP_KEY")
        # No sidecar key file exists anymore.
        assert not Path(str(backup) + ".key").exists()

        with pytest.raises(ValueError, match="PET_BACKUP_KEY"):
            restore_backup(db_file, backup, backups_dir)

    def test_restore_rejects_tampered_backup(self, db_file, backups_dir, monkeypatch):
        monkeypatch.setenv("PET_BACKUP_KEY", TEST_BACKUP_KEY)
        backup = create_backup(db_file, backups_dir, backup_kind="manual")
        original_bytes = backup.read_bytes()
        backup.write_bytes(original_bytes + b"tamper")

        with pytest.raises(ValueError, match="checksum|integrity|decrypt"):
            restore_backup(db_file, backup, backups_dir)

    def test_missing_backup_raises(self, db_file, backups_dir, tmp_path):
        with pytest.raises(FileNotFoundError):
            restore_backup(db_file, tmp_path / "missing.db", backups_dir)

    def test_missing_db_raises_during_safety_backup(self, backups_dir, tmp_path):
        """restore_backup requires an existing target DB because it creates a
        safety backup first (create_backup raises FileNotFoundError if missing)."""
        backup = _make_backup(backups_dir, datetime.now())
        target_db = tmp_path / "newdir" / "Database.db"
        with pytest.raises(FileNotFoundError):
            restore_backup(target_db, backup, backups_dir)

    def test_restore_into_empty_existing_db(self, backups_dir, tmp_path):
        """Restoring into a pre-existing (even empty) DB file succeeds."""
        target_db = tmp_path / "Database.db"
        target_db.write_bytes(b"")  # empty placeholder DB

        backup = _make_backup(backups_dir, datetime.now() - timedelta(seconds=5))
        restore_backup(target_db, backup, backups_dir)
        # Safety backup + restored copy written.
        assert target_db.exists()
        assert len(list_backups(backups_dir)) == 2  # safety + manual-style restore


class TestBackupConsistency:
    """A backup must capture WAL data and must never spill plaintext sidecars."""

    def test_backup_captures_committed_wal_data(self, tmp_path, backups_dir):
        db = tmp_path / "Database.db"
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.commit()
        conn.execute("INSERT INTO t (v) VALUES ('in-wal')")
        conn.commit()
        try:
            # Connection stays open, so the row lives in the WAL, not the main
            # file — a plain read_bytes snapshot would miss it.
            backup = create_backup(db, backups_dir, backup_kind="manual")
            restored = sqlite3.connect(str(backup))
            rows = list(restored.execute("SELECT v FROM t"))
            restored.close()
            assert rows == [("in-wal",)]
        finally:
            conn.close()

    def test_encrypted_backup_leaves_no_plaintext_sidecars(
        self, db_file, backups_dir, monkeypatch
    ):
        # Put a WAL next to the source so the old code would have copied it in
        # plaintext next to the ciphertext.
        conn = sqlite3.connect(str(db_file))
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("INSERT INTO test (value) VALUES ('secret')")
        conn.commit()
        conn.close()

        monkeypatch.setenv("PET_BACKUP_KEY", TEST_BACKUP_KEY)
        backup = create_backup(db_file, backups_dir, backup_kind="manual")

        assert not Path(str(backup) + "-wal").exists()
        assert not Path(str(backup) + "-shm").exists()
        assert not backup.read_bytes().startswith(b"SQLite format 3\x00")

    def test_restore_removes_stale_wal_and_shm(self, db_file, backups_dir):
        backup = create_backup(
            db_file, backups_dir, backup_kind="manual",
            now=datetime.now() - timedelta(seconds=5),
        )
        stale_wal = Path(str(db_file) + "-wal")
        stale_shm = Path(str(db_file) + "-shm")
        stale_wal.write_bytes(b"stale")
        stale_shm.write_bytes(b"stale")

        restore_backup(db_file, backup, backups_dir)

        assert not stale_wal.exists()
        assert not stale_shm.exists()

