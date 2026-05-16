"""Tests for src/core/repositories/report_archive_repo.py"""

from src.core.repositories import report_archive_repo


def _snapshot(**overrides):
    payload = {
        "report_kind": "Financial Report",
        "period_type": "Month",
        "data": {"kpis": {"visits": 4, "revenue": 200.0}},
        "period_start": "2026-09-01",
        "period_end": "2026-09-05",
        "generated_by": "admin",
    }
    payload.update(overrides)
    return report_archive_repo.save_snapshot(
        payload["report_kind"],
        payload["period_type"],
        payload["data"],
        payload["period_start"],
        payload["period_end"],
        payload["generated_by"],
    )


class TestSaveAndRetrieve:
    def test_save_returns_id_and_get_restores_data(self, fresh_db):
        archive_id = _snapshot()
        assert archive_id is not None

        row = report_archive_repo.get_archive(archive_id)
        assert row["report_kind"] == "Financial Report"
        assert row["period_type"] == "Month"
        assert row["period_start"] == "2026-09-01"
        assert row["data"]["kpis"]["visits"] == 4
        assert row["data"]["kpis"]["revenue"] == 200.0

    def test_get_missing_archive_returns_none(self, fresh_db):
        assert report_archive_repo.get_archive(999999) is None

    def test_corrupt_json_falls_back_to_empty(self, fresh_db):
        db = fresh_db
        q = __import__("PyQt5.QtSql", fromlist=["QSqlQuery"]).QSqlQuery(db)
        assert q.exec(
            "INSERT INTO report_archives (report_kind, period_type, data_json) "
            "VALUES ('Overview Analytics', 'Month', 'not-json{{{')"
        )
        archive_id = q.lastInsertId()
        row = report_archive_repo.get_archive(int(archive_id))
        assert row is not None
        assert row["data"] == {}


class TestSaveCreatesHistoryEntries:
    def test_every_save_inserts_a_new_row(self, fresh_db):
        first_id = _snapshot()
        second_id = _snapshot(data={"kpis": {"visits": 9}})
        assert first_id != second_id
        assert len(report_archive_repo.list_archives()) == 2
        assert report_archive_repo.get_archive(second_id)["data"]["kpis"]["visits"] == 9

    def test_different_windows_keep_separate_rows(self, fresh_db):
        a = _snapshot()
        b = _snapshot(period_start="2026-09-08", period_end="2026-09-12")
        rows = report_archive_repo.list_archives()
        assert len(rows) == 2
        assert {r["archive_id"] for r in rows} == {a, b}


class TestSearchArchives:
    def test_empty_query_lists_everything(self, fresh_db):
        _snapshot()
        _snapshot(report_kind="Supply Report", period_type="Week")
        assert len(report_archive_repo.search_archives("")) == 2

    def test_matches_report_kind(self, fresh_db):
        _snapshot()
        _snapshot(report_kind="Supply Report", period_type="Week")
        rows = report_archive_repo.search_archives("Supply")
        assert len(rows) == 1
        assert rows[0]["report_kind"] == "Supply Report"

    def test_matches_generated_by(self, fresh_db):
        _snapshot(generated_by="dr_house")
        _snapshot(generated_by="nurse_joy")
        rows = report_archive_repo.search_archives("nurse")
        assert len(rows) == 1
        assert rows[0]["generated_by"] == "nurse_joy"

    def test_no_match_returns_empty(self, fresh_db):
        _snapshot()
        assert report_archive_repo.search_archives("zzz-nope") == []


class TestListDeleteClear:
    def test_list_orders_newest_first(self, fresh_db):
        a = _snapshot(period_type="Year")
        b = _snapshot(report_kind="Supply Report")
        rows = report_archive_repo.list_archives()
        assert [r["archive_id"] for r in rows] == [b, a]

    def test_delete_removes_row(self, fresh_db):
        archive_id = _snapshot()
        assert report_archive_repo.delete_archive(archive_id) is True
        assert report_archive_repo.get_archive(archive_id) is None

    def test_clear_removes_all(self, fresh_db):
        _snapshot()
        _snapshot(report_kind="Supply Report")
        assert report_archive_repo.clear_archives() is True
        assert report_archive_repo.list_archives() == []


class TestArchiveDays:
    def test_list_archive_days_groups_by_day(self, fresh_db):
        _snapshot()
        _snapshot(report_kind="Supply Report")
        days = report_archive_repo.list_archive_days()
        assert len(days) == 1
        day, count = days[0]
        assert day == "2026-09-05"
        assert count == 2

    def test_list_archive_days_groups_by_window_end(self, fresh_db):
        _snapshot()
        _snapshot(period_start="2026-09-10", period_end="2026-09-12")
        days = dict(report_archive_repo.list_archive_days())
        assert days["2026-09-12"] == 1
        assert days["2026-09-05"] == 1

    def test_list_archive_days_empty(self, fresh_db):
        assert report_archive_repo.list_archive_days() == []

    def test_list_archives_for_day_returns_snapshots(self, fresh_db):
        a = _snapshot()
        b = _snapshot(report_kind="Supply Report")
        # Snapshots are anchored on their window end (period_end), not generated_at.
        by_day = report_archive_repo.list_archives_for_day("2026-09-05")
        assert {r["archive_id"] for r in by_day} == {a, b}

    def test_list_archives_for_day_unknown_day_empty(self, fresh_db):
        _snapshot()
        assert report_archive_repo.list_archives_for_day("2001-01-01") == []
