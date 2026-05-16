"""Tests for the card-based VisitInfoDialog edit and settle flows."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QPushButton

from src.ui.dialogs.info_dialogs import VisitInfoDialog


def _admin_user(user_id=1):
    return {"user_id": user_id, "username": "admin", "roles": ["admin"]}


def _seed_consult_visit(repos, client_repo, pet_repo, visit_repo):
    owner_id = client_repo.add_client("Adjust Owner", "0500000000")
    pet_id = pet_repo.add_pet("Rex", "Dog", "Labrador", "M", 24, 25.5, owner_id)
    visit_id = visit_repo.add_visit(
        "2026-09-05 10:30", "Checkup", 1, "Initial notes",
        pet_id=pet_id, client_id=owner_id,
    )
    return visit_id, owner_id, pet_id


def test_visit_dialog_layout_edit_footer_and_billing_buttons(qapp, fresh_db, repos):
    """Visit Info shows doctor/reason/diagnosis (no owner/pet); footer Edit swapped;
    billing Settle/Adjust visible only in edit mode; Pet/Follow-ups cards swapped."""
    client_repo = repos["client"]
    pet_repo = repos["pet"]
    visit_repo = repos["visit"]
    visit_id, _, _ = _seed_consult_visit(repos, client_repo, pet_repo, visit_repo)
    row = visit_repo.get_visits()[0]
    assert row["visit_id"] == visit_id

    dlg = VisitInfoDialog(row, current_user=_admin_user())
    assert dlg._editing is False
    assert dlg._receipt_id, "consult visit should carry a receipt"

    # Read-only mode: footer shows Edit + Close, no Settle/Adjust buttons.
    labels = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Edit" in labels
    assert "Close" in labels
    assert "Settle Payment" not in labels
    assert "Adjust" not in labels

    dlg._toggle_edit(True)
    assert dlg._editing is True
    # Edit mode: footer swaps to Save Visit/Cancel; billing buttons appear.
    assert dlg._btn_edit.isHidden()
    assert dlg._btn_close.isHidden()
    assert not dlg._btn_save.isHidden()
    assert not dlg._btn_cancel.isHidden()
    labels = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Settle Payment" in labels
    assert "Adjust" in labels
    # Full replica: supplies section + discount editor built.
    assert getattr(dlg, "items_layout", None) is not None
    assert hasattr(dlg, "_discount_spin")

    dlg._toggle_edit(False)
    assert dlg._editing is False
    labels = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Settle Payment" not in labels
    assert "Adjust" not in labels
    dlg._btn_close.click()

    # Confirm read-only Visit Info card has doctor/reason/diagnosis but no owner/pet rows.
    dlg2 = VisitInfoDialog(visit_repo.get_visits()[0], current_user=_admin_user())
    info = _collect_labels(dlg2)
    assert any("Diagnosis:" in t for t in info)
    assert any("Doctor:" in t for t in info)
    assert not any("Owner:" in t for t in info)
    assert not any("Pet:" in t for t in info)


def _collect_labels(dlg):
    """Collects label + button text recursively across the dialog."""
    out = []
    stack = [dlg]
    while stack:
        w = stack.pop()
        text = getattr(w, "text", None)
        if text is not None:
            try:
                t = text()
                if t:
                    out.append(t)
            except Exception:
                pass
        for child in w.children():
            stack.append(child)
    return out


def test_visit_dialog_edit_consults_off_records_adjustment(qapp, fresh_db, repos):
    """Turning the consult charge off updates the visit and records an adjustment."""
    from src.core.repositories.audit_repo import get_recent_changes_with_details
    from src.core.repositories.receipt_adjustment_repo import get_adjustments_for_receipt
    from src.core.repositories.sales_repo import get_receipt

    client_repo = repos["client"]
    pet_repo = repos["pet"]
    visit_repo = repos["visit"]
    visit_id, _, _ = _seed_consult_visit(repos, client_repo, pet_repo, visit_repo)
    row = visit_repo.get_visits()[0]
    receipt_id = row["receipt_id"]
    assert float(get_receipt(receipt_id)["total_price"]) == 50.0

    dlg = VisitInfoDialog(row, current_user=_admin_user())
    dlg._toggle_edit(True)
    dlg._diag_edit.setText("Updated Diagnosis")
    dlg._notes_edit.setPlainText("Updated notes")
    dlg._reason_edit.setText("Updated reason")
    dlg._consult_cb.setChecked(False)
    dlg._save_edits()

    updated = visit_repo.get_visits()[0]
    assert updated["visit_id"] == visit_id
    assert updated["diagnosis"] == "Updated Diagnosis"
    assert updated["notes"] == "Updated notes"
    assert updated["reason_for_visit"] == "Updated reason"
    assert updated["consult"] == 0

    new_total = float(get_receipt(receipt_id)["total_price"])
    assert abs(new_total) < 0.004, new_total

    adjustments = get_adjustments_for_receipt(receipt_id)
    assert len(adjustments) == 1
    assert abs(float(adjustments[0]["new_total"])) < 0.004
    assert abs(float(adjustments[0]["old_total"]) - 50.0) < 0.004

    rows = get_recent_changes_with_details(50)
    assert any(
        str(r.get("table_name")) == "receipts"
        and int(r.get("record_id")) == receipt_id
        and any(
            d.get("field_name") == "action"
            and str(d.get("new_value")) == "ADJUST"
            for d in r.get("details", [])
        )
        for r in rows
    )


def test_billing_is_resolved_from_visit_id_when_receipt_id_missing(qapp, fresh_db, repos):
    """Pet/Owner dialogs only carry the visit id; Visit Info still finds billing."""
    visit_id, owner_id, pet_id = _seed_consult_visit(
        repos, repos["client"], repos["pet"], repos["visit"])

    data = {
        "visit_id": visit_id,
        "visit_date": "2026-09-05 10:30",
        "pet_id": pet_id,
        "pet_name": "Rex",
        "owner_id": owner_id,
        "owner_name": "Adjust Owner",
        "consult": 1,
    }
    assert "receipt_id" not in data
    dlg = VisitInfoDialog(data, current_user=_admin_user())
    assert dlg._receipt_id, "billing should resolve from the visit id"
    assert dlg._receipt is not None


def test_clinical_card_renders_the_record_book_exam(qapp, fresh_db, repos):
    """Read-only exam card replaces the old health-stats/meds groups."""
    from src.core.repositories import clinical_exam_repo

    visit_id, _, _ = _seed_consult_visit(
        repos, repos["client"], repos["pet"], repos["visit"])
    clinical_exam_repo.save_clinical_exam_for_visit(visit_id, {
        "generalPhysicalExamination": {
            "weight": {"value": 12.5, "condition": "normal"},
            "temperature": {"value": 38.4, "status": "normal"},
            "neutered": True,
        },
        "clinicalSigns": {"energy": "decreased"},
        "routineTests": [{"testName": "CBC", "result": "pending"}],
        "vaccinations": ["Rabies"],
        "physicalExam": {"heart": {"normal": True}},
        "recommendedTestsTreatments": {"xrays": True},
    })
    row = repos["visit"].get_visits()[0]

    dlg = VisitInfoDialog(row, current_user=_admin_user())
    labels = _collect_labels(dlg)
    assert "Clinical Exam" in labels
    assert any("General Physical Examination" in t for t in labels)
    assert any("12.5" in t for t in labels)
    # The legacy mixin groups are gone from this dialog entirely.
    assert not hasattr(dlg, "_prefill_clinical_sections")
    assert not hasattr(dlg, "_health_stats")
    for legacy in ("Health Stats", "Medications"):
        assert legacy not in labels


def test_clinical_notes_are_editable_but_exam_is_not(qapp, fresh_db, repos):
    from src.core.repositories import clinical_exam_repo

    visit_id, _, _ = _seed_consult_visit(
        repos, repos["client"], repos["pet"], repos["visit"])
    clinical_exam_repo.save_clinical_exam_for_visit(visit_id, {
        "generalPhysicalExamination": {"weight": {"value": 5.0, "condition": "normal"}},
    })
    row = repos["visit"].get_visits()[0]

    dlg = VisitInfoDialog(row, current_user=_admin_user())
    assert not hasattr(dlg, "_notes_edit")
    dlg._toggle_edit(True)
    assert hasattr(dlg, "_notes_edit")
    # Edit mode shows only the notes editor in the clinical card.
    assert not hasattr(dlg, "_rec_weight_value")