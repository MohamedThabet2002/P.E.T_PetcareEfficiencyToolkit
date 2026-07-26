"""Dashboard action buttons: permission gating + the wide-only third button.

When a user may use ALL THREE dashboard actions, the role's two main buttons
stay visible and the third (Quick Purchase for admins, Add Supplies for
everyone else) only appears once the window is wider than
``WIDE_WINDOW_WIDTH`` — the same threshold as the next-client countdown.
A partial grant is never width-gated.
"""

import pytest

from src.ui.pages.dashboard_page import DashboardPage, WIDE_WINDOW_WIDTH


ADMIN = {"user_id": 1, "username": "admin", "roles": ["admin"]}
DOCTOR = {"user_id": 2, "username": "doctor", "roles": ["doctor"]}
STAFF = {"user_id": 3, "username": "staff", "roles": ["staff"]}
ALL_THREE = {"add_visit", "add_supplies", "quick_purchase"}

NARROW = WIDE_WINDOW_WIDTH          # 1200 is NOT wider than the threshold
WIDE = WIDE_WINDOW_WIDTH + 400


def _user(base, actions):
    """A user whose role template grants exactly *actions*."""
    user = dict(base)
    user["_role_permissions"] = set(actions)
    return user


@pytest.fixture
def page(qapp, fresh_db):
    widget = DashboardPage()
    # Resize events are only delivered to a visible widget (and are pending
    # until the first show), so the page has to be shown for the width rule
    # to be observable.
    widget.show()
    qapp.processEvents()
    yield widget
    widget.deleteLater()


def _buttons(page):
    return {
        "add_visit": not page.add_visit_btn.isHidden(),
        "add_supplies": not page.bulk_purchase_btn.isHidden(),
        "quick_purchase": not page.quick_purchase_btn.isHidden(),
    }


def _assert_at(page, qapp, width, expected):
    page.resize(width, 800)
    qapp.processEvents()
    assert _buttons(page) == expected


def test_quick_purchase_button_exists_and_is_labelled(page):
    assert page.quick_purchase_btn.text() == "Quick Purchase"


class TestAdminMainButtons:
    """Admins: Add Visit + Add Supplies are main, Quick Purchase is wide-only."""

    def test_narrow_window_hides_quick_purchase(self, page, qapp):
        page.set_current_user(ADMIN)  # an admin is granted all three
        _assert_at(page, qapp, NARROW, {
            "add_visit": True, "add_supplies": True, "quick_purchase": False,
        })

    def test_wide_window_reveals_quick_purchase(self, page, qapp):
        page.set_current_user(ADMIN)
        _assert_at(page, qapp, WIDE, {
            "add_visit": True, "add_supplies": True, "quick_purchase": True,
        })

    def test_narrowing_again_hides_quick_purchase(self, page, qapp):
        page.set_current_user(ADMIN)
        _assert_at(page, qapp, WIDE, {
            "add_visit": True, "add_supplies": True, "quick_purchase": True,
        })
        _assert_at(page, qapp, NARROW, {
            "add_visit": True, "add_supplies": True, "quick_purchase": False,
        })


class TestDoctorMainButtons:
    """Doctors: Add Visit + Quick Purchase are main, Add Supplies is wide-only."""

    def test_default_doctor_is_never_width_gated(self, page, qapp):
        # The doctor role is only granted two of the three actions (no Add
        # Supplies), so nothing is gated — Quick Purchase shows at any width.
        page.set_current_user(DOCTOR)
        for width in (NARROW, WIDE):
            _assert_at(page, qapp, width, {
                "add_visit": True, "add_supplies": False, "quick_purchase": True,
            })

    def test_doctor_granted_all_three_gates_supplies(self, page, qapp):
        page.set_current_user(_user(DOCTOR, ALL_THREE))
        _assert_at(page, qapp, NARROW, {
            "add_visit": True, "add_supplies": False, "quick_purchase": True,
        })
        _assert_at(page, qapp, WIDE, {
            "add_visit": True, "add_supplies": True, "quick_purchase": True,
        })


class TestOtherUsers:
    def test_staff_granted_all_three_gates_supplies(self, page, qapp):
        # Non-admins follow the doctor rule: supplies is the wide-only one.
        page.set_current_user(_user(STAFF, ALL_THREE))
        _assert_at(page, qapp, NARROW, {
            "add_visit": True, "add_supplies": False, "quick_purchase": True,
        })
        _assert_at(page, qapp, WIDE, {
            "add_visit": True, "add_supplies": True, "quick_purchase": True,
        })

    def test_partial_grant_is_never_width_gated(self, page, qapp):
        page.set_current_user(_user(STAFF, {"add_visit", "add_supplies"}))
        for width in (NARROW, WIDE):
            _assert_at(page, qapp, width, {
                "add_visit": True, "add_supplies": True, "quick_purchase": False,
            })

    def test_no_user_hides_every_button(self, page, qapp):
        page.set_current_user(ADMIN)
        page.set_current_user(None)
        _assert_at(page, qapp, WIDE, {
            "add_visit": False, "add_supplies": False, "quick_purchase": False,
        })
