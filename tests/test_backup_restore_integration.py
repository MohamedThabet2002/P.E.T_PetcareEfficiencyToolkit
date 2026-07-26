"""Integration tests for backup/restore flow with the application's DB path logic."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.backup_manager import create_backup, list_backups, prune_backups, restore_backup


@pytest.fixture
def sqlite_db(tmp_path):
    """Creates a real SQLite database (independent of the Qt fresh_db fixture)."""
    db = tmp_path / "Database.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE clinic (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE pets (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO clinic (name) VALUES ('My PET Clinic')")
    conn.execute("INSERT INTO pets (name) VALUES ('Rex')")
    conn.commit()
    conn.close()
    return db


class TestFullBackupRestoreLifecycle:
    def test_create_modify_restore_roundtrip(self, sqlite_db, tmp_path):
        backups_dir = tmp_path / "backups"

        # Create manual backup of "clean" state.
        backup = create_backup(sqlite_db, backups_dir, backup_kind="manual", now=datetime.now() - timedelta(seconds=5))
        assert list_backups(backups_dir)[0].is_manual is True

        # Mutate the live DB.
        conn = sqlite3.connect(str(sqlite_db))
        conn.execute("INSERT INTO pets (name) VALUES ('NEW_PET_THAT_MUST_DISAPPEAR')")
        conn.commit()
        conn.close()

        # Restore from backup.
        restore_backup(sqlite_db, backup, backups_dir)

        conn = sqlite3.connect(str(sqlite_db))
        names = [r[0] for r in conn.execute("SELECT name FROM pets ORDER BY id")]
        conn.close()
        assert names == ["Rex"]  # mutated row gone

    def test_safety_backup_created_before_restore(self, sqlite_db, tmp_path):
        backups_dir = tmp_path / "backups"
        backup = create_backup(sqlite_db, backups_dir, backup_kind="manual", now=datetime.now() - timedelta(seconds=5))
        initial_count = len(list_backups(backups_dir))

        restore_backup(sqlite_db, backup, backups_dir)
        after = list_backups(backups_dir)

        # Manual backup + one new safety auto backup (pre-restore).
        assert len(after) == initial_count + 1
        assert after[0].backup_path != backup  # safety backup is newest

    def test_manual_backup_survives_prune(self, sqlite_db, tmp_path):
        backups_dir = tmp_path / "backups"
        create_backup(sqlite_db, backups_dir, backup_kind="manual")
        # Old auto backup too.
        old = backups_dir / f"Database_{(datetime.now() - timedelta(days=10)).strftime('%Y%m%d_%H%M%S')}.db"
        old.write_bytes(b"old")
        deleted, _ = prune_backups(backups_dir, now=datetime.now(), keep_daily_days=7)
        assert deleted == 1
        entries = list_backups(backups_dir)
        assert len(entries) == 1
        assert entries[0].is_manual is True


class TestUserDbPathRecovery:
    """Tests src.core.database.connection.get_user_db_path recovery logic."""

    def test_restores_from_latest_backup_when_db_missing(
        self, monkeypatch, tmp_path
    ):
        import src.core.database.connection as db_connection
        import src.config.paths as paths

        app_data = tmp_path / "appdata"
        backups_dir = tmp_path / "backups"
        app_data.mkdir(parents=True)
        # get_user_db_path() places the DB directly in APP_DATA_ROOT.
        db_target = app_data / "Database.db"

        # Create a source DB and a backup of it.
        src_db = tmp_path / "source.db"
        conn = sqlite3.connect(str(src_db))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()

        backups_dir.mkdir()
        backup = create_backup(src_db, backups_dir, backup_kind="manual")

        # Point app config at our temp paths, reset USER_DB_PATH to None.
        monkeypatch.setattr(paths, "APP_DATA_ROOT", app_data)
        monkeypatch.setattr(paths, "BACKUPS_DIR", backups_dir)
        monkeypatch.setattr(paths, "USER_DB_PATH", None)
        # get_user_db_path reads module-level references imported in db_connection.
        monkeypatch.setattr(db_connection, "APP_DATA_ROOT", app_data)
        monkeypatch.setattr(db_connection, "BACKUPS_DIR", backups_dir)
        monkeypatch.setattr(db_connection, "USER_DB_PATH_CFG", None)

        recovered = db_connection.get_user_db_path()

        assert recovered == db_target
        assert db_target.exists()

        conn = sqlite3.connect(str(db_target))
        rows = list(conn.execute("SELECT id FROM t"))
        conn.close()
        assert rows == [(1,)]

        # Not strictly needed, but verify the backup itself was kept (manual).
        assert any(e.is_manual for e in list_backups(backups_dir))

    def test_no_backups_creates_none_path(self, monkeypatch, tmp_path):
        """When DB is missing and no backups exist, returns path without creating file."""
        import src.core.database.connection as db_connection
        import src.config.paths as paths

        app_data = tmp_path / "appdata"
        backups_dir = tmp_path / "backups"  # does not exist
        db_target = app_data / "Database.db"

        monkeypatch.setattr(paths, "APP_DATA_ROOT", app_data)
        monkeypatch.setattr(paths, "BACKUPS_DIR", backups_dir)
        monkeypatch.setattr(paths, "USER_DB_PATH", None)
        monkeypatch.setattr(db_connection, "APP_DATA_ROOT", app_data)
        monkeypatch.setattr(db_connection, "BACKUPS_DIR", backups_dir)
        monkeypatch.setattr(db_connection, "USER_DB_PATH_CFG", None)

        result = db_connection.get_user_db_path()

        assert result == paths.APP_DATA_ROOT / "Database.db"
        assert result == db_target

    def test_recovers_and_decrypts_an_encrypted_backup(self, monkeypatch, tmp_path):
        """A missing DB must be recovered from an encrypted backup (decrypted)."""
        import src.core.database.connection as db_connection
        import src.config.paths as paths

        key = "_ihQThorj6ULKowZUTOh3N_Rh16MHsG3nyDBmFUDAZs="
        app_data = tmp_path / "appdata"
        backups_dir = tmp_path / "backups"
        app_data.mkdir(parents=True)
        backups_dir.mkdir()
        db_target = app_data / "Database.db"

        src_db = tmp_path / "source.db"
        conn = sqlite3.connect(str(src_db))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (7)")
        conn.commit()
        conn.close()

        monkeypatch.setenv("PET_BACKUP_KEY", key)
        create_backup(src_db, backups_dir, backup_kind="manual")

        monkeypatch.setattr(paths, "APP_DATA_ROOT", app_data)
        monkeypatch.setattr(paths, "BACKUPS_DIR", backups_dir)
        monkeypatch.setattr(paths, "USER_DB_PATH", None)
        monkeypatch.setattr(db_connection, "APP_DATA_ROOT", app_data)
        monkeypatch.setattr(db_connection, "BACKUPS_DIR", backups_dir)
        monkeypatch.setattr(db_connection, "USER_DB_PATH_CFG", None)

        recovered = db_connection.get_user_db_path()

        assert recovered == db_target
        # The recovered file must be a real, decrypted SQLite database.
        conn = sqlite3.connect(str(db_target))
        rows = list(conn.execute("SELECT id FROM t"))
        conn.close()
        assert rows == [(7,)]

