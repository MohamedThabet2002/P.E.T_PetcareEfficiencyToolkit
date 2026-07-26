"""Footer pinning: every dialog's OK/Cancel row must stay glued to the bottom.

Measured geometry rule (with the real stylesheet applied): the gap between the
lowest button and the dialog's bottom edge must stay small AND must not grow
when the dialog is resized taller. A form-root dialog (`QFormLayout(dialog)`)
leaves that gap open wider and lets the buttons drift up on every resize — that
is the regression this test guards against.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication, QDialog, QDialogButtonBox, QPushButton

from src.ui.themes.color_palettes import get_active_palette, get_styled_qss

ADMIN = {"user_id": 1, "username": "admin", "roles": ["admin"]}

MAX_GAP = 40       # px from the bottom button to the dialog's bottom edge
MAX_DRIFT = 6      # px the gap may change when the dialog grows by 150 px


def _qss():
    from src.config.paths import STYLES_DIR
    return get_styled_qss(STYLES_DIR / "style.qss", "light", get_active_palette())


def _bottom_gap(dialog, box):
    tl = box.mapTo(dialog, box.rect().topLeft())
    return dialog.rect().bottom() - (tl.y() + box.height())


def _lowest_box(dialog):
    best, best_y = None, -1
    for box in list(dialog.findChildren(QDialogButtonBox)) + \
            list(dialog.findChildren(QPushButton)):
        if box.isHidden() or not box.isVisible():
            continue
        tl = box.mapTo(dialog, box.rect().topLeft())
        y = tl.y() + box.height()
        if y > best_y:
            best, best_y = box, y
    return best


def measure(name, dialog, qss):
    dialog.setStyleSheet(qss)
    dialog.show()
    QApplication.processEvents()
    box = _lowest_box(dialog)
    assert box is not None, "%s: no visible footer buttons" % name
    gap0 = _bottom_gap(dialog, box)
    dialog.resize(dialog.width(), dialog.height() + 150)
    QApplication.processEvents()
    gap1 = _bottom_gap(dialog, box)
    dialog.close()
    assert gap0 <= MAX_GAP, (
        "%s: footer floats %.0f px above the bottom edge (max %d)"
        % (name, gap0, MAX_GAP))
    assert abs(gap1 - gap0) <= MAX_DRIFT, (
        "%s: footer drifts %.0f px when the dialog grows (max %d)"
        % (name, gap1 - gap0, MAX_DRIFT))


def _capture(monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self: opened.append(self) or 0,
                        raising=False)
    monkeypatch.setattr(QDialog, "exec_", lambda self: opened.append(self) or 0,
                        raising=False)
    return opened


@pytest.mark.parametrize("target", ["pages", "classes", "extras"])
def test_footer_stays_pinned(target, fresh_db, repos, qapp, monkeypatch,
                             entity_factory):
    opened = _capture(monkeypatch)
    qss = _qss()

    def M(name, dlg):
        measure(name, dlg, qss)

    if target == "pages":
        from src.ui.pages.database_pages.clients_page import ClientsPage
        from src.ui.pages.database_pages.supplies_page import SuppliesPage
        from src.ui.pages.database_pages.visits_page import VisitsPage
        from src.ui.pages.database_pages.receipts_page import ReceiptsPage

        clients = ClientsPage()
        clients.set_current_user(dict(ADMIN))
        clients.add_client_dialog()
        M("clients/add_client_dialog", opened.pop())
        clients.add_pet_dialog()
        M("clients/add_pet_dialog", opened.pop())

        repos["supply"].add_category("Medicine")
        sid, _ = entity_factory["make_supply"](category="Medicine",
                                               sub="Antibiotics",
                                               name="Audit Item")
        supplies = SuppliesPage()
        supplies.set_current_user(dict(ADMIN))
        supplies.add_supply_dialog("Medicine")
        M("supplies/add_supply_dialog", opened.pop())
        supplies.refresh_all_tabs()
        table = supplies.tables["Medicine"]
        row = next(r for r in range(table.rowCount())
                   if table.item(r, 0).text() == str(sid))
        supplies.edit_supply_dialog("Medicine", row)
        M("supplies/edit_supply_dialog", opened.pop())

        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid)
        repos["appointment"].add_appointment("2030-06-01 10:00", "Check-up",
                                             "Pending", "Routine", cid, pid)
        visits = VisitsPage()
        visits.set_current_user(dict(ADMIN))
        visits.refresh_appointments()
        visits.add_appointment_dialog()
        M("visits/add_appointment_dialog", opened.pop())
        table = visits.tables["Appointments"]
        arow = next(r for r in range(table.rowCount())
                    if table.item(r, 0).text() == "1")
        visits.edit_appointment_dialog(arow)
        M("visits/edit_appointment_dialog", opened.pop())

        receipts = ReceiptsPage()
        receipts.set_current_user(dict(ADMIN))
        receipts.add_expense_dialog()
        M("receipts/add_expense_dialog", opened.pop())

    elif target == "classes":
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog
        from src.ui.dialogs.custom_permissions_dialog import CustomPermissionsDialog
        from src.ui.dialogs.first_run_dialog import FirstRunDialog
        from src.ui.dialogs.followup_dialog import FollowupDialog, FollowupEditDialog
        from src.ui.dialogs.import_data_dialog import ImportDataDialog
        from src.ui.dialogs.login_dialog import LoginDialog
        from src.ui.dialogs.package_dialog import (
            PackageDialog, _PackageEditDialog, _PackageItemDialog,
        )
        from src.ui.dialogs.pending_changes_dialog import PendingChangesDialog
        from src.ui.dialogs.pet_health_timeline_dialog import PetHealthTimelineDialog
        from src.ui.dialogs.pet_medications_dialog import PetMedicationsDialog
        from src.ui.dialogs.quick_purchase_dialog import QuickPurchaseDialog
        from src.ui.dialogs.reminders_dialog import RemindersDialog
        from src.ui.dialogs.role_editor_dialog import RoleEditorDialog
        from src.ui.dialogs.stock_batch_dialog import StockBatchDialog, _BatchEditDialog
        from src.ui.dialogs.suppliers_dialog import SuppliersDialog
        from src.ui.dialogs.supply_reorder_dialog import SupplyReorderDialog
        from src.ui.dialogs.vaccine_schedule_dialog import (
            VaccineScheduleDialog, _ScheduleEditDialog,
        )
        from src.ui.dialogs.visit_dialogs import ReceiptDetailsDialog

        sid, _ = repos["supply"].add_supply(
            "Audit Item", "Medicine", "Antibiotics", purchase_date="2026-01-10",
            expiry_date="2027-01-10", buy_price=5.0, sell_price=10.0,
            quantity=10, supplier=None)

        ctors = [
            ("AppointmentsDialog", lambda: AppointmentsDialog(current_user=dict(ADMIN))),
            ("FirstRunDialog", FirstRunDialog),
            ("LoginDialog", LoginDialog),
            ("PackageDialog", PackageDialog),
            ("_PackageEditDialog", lambda: _PackageEditDialog(
                None, 0, "pkg", "desc", 10.0)),
            ("_PackageItemDialog", lambda: _PackageItemDialog(None, None)),
            ("StockBatchDialog", lambda: StockBatchDialog(sid, "Audit Item",
                                                          current_user=dict(ADMIN))),
            ("_BatchEditDialog", lambda: _BatchEditDialog(
                None, "t", 1, None, "2026-01-10", "2027-01-10", 5.0, 1, "")),
            ("SupplyReorderDialog", SupplyReorderDialog),
            ("SuppliersDialog", SuppliersDialog),
            ("VaccineScheduleDialog", VaccineScheduleDialog),
            ("_ScheduleEditDialog", lambda: _ScheduleEditDialog(None, 30, "")),
            ("RoleEditorDialog", RoleEditorDialog),
            ("CustomPermissionsDialog", lambda: CustomPermissionsDialog(
                1, "admin")),
            ("PetMedicationsDialog", lambda: PetMedicationsDialog(1, "Buddy")),
            ("PetHealthTimelineDialog", lambda: PetHealthTimelineDialog(
                1, "Buddy")),
            ("ReceiptDetailsDialog", lambda: ReceiptDetailsDialog(
                1, "2026-01-01", "Owner")),
            ("PendingChangesDialog", lambda: PendingChangesDialog(
                current_user=dict(ADMIN))),
            ("RemindersDialog", lambda: RemindersDialog(current_user=dict(ADMIN))),
            ("ImportDataDialog", lambda: ImportDataDialog(
                current_user=dict(ADMIN))),
            ("QuickPurchaseDialog", lambda: QuickPurchaseDialog(
                current_user=dict(ADMIN))),
            ("FollowupEditDialog", lambda: FollowupEditDialog(visit_id=1)),
            ("FollowupDialog", lambda: FollowupDialog(
                None, "Buddy", "Owner", current_user=dict(ADMIN))),
        ]
        for name, ctor in ctors:
            M(name, ctor())

    else:
        from src.core.repositories import payment_repo
        from src.ui.dialogs.edit_receipt_dialog import EditReceiptDialog
        from src.ui.dialogs.info_dialogs import (
            OwnerInfoDialog, PetInfoDialog, SupplyInfoDialog,
        )
        from src.ui.dialogs.supply_reorder_dialog import SupplyReorderDialog
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog

        cid = entity_factory["make_client"]()
        entity_factory["make_pet"](cid, name="Buddy")
        entity_factory["make_supply"](name="Audit Item", reorder_level=50)

        owner = repos["client"].get_clients()[0]
        M("OwnerInfoDialog", OwnerInfoDialog(dict(owner),
                                             current_user=dict(ADMIN)))
        pet = repos["pet"].get_pets_for_client(cid)[0]
        M("PetInfoDialog", PetInfoDialog(dict(pet),
                                         current_user=dict(ADMIN)))
        item = repos["supply"].search_supplies(category="Medicine")[0]
        M("SupplyInfoDialog", SupplyInfoDialog(dict(item)))

        rid = int(repos["sales"].create_sale_receipt_for_quick_purchase(
            cid, "2026-09-06",
            [{"item_name": "Audit Item", "quantity": 2, "price": 25.0}],
            paid=False))
        M("ReceiptInfoDialog", ReceiptInfoDialog(rid, current_user=dict(ADMIN)))
        M("EditReceiptDialog", EditReceiptDialog(
            rid, current_user=dict(ADMIN)))

        dlg = ReceiptInfoDialog(rid, current_user=dict(ADMIN))
        dlg._add_payment()
        M("receipts/_add_payment", opened.pop())

        payment_repo.add_payment(rid, 999.0, "Cash")
        dlg = ReceiptInfoDialog(rid, current_user=dict(ADMIN))
        dlg._record_refund()
        M("receipts/_record_refund", opened.pop())

        payment_repo.add_payment(rid, 1.0, "Cash")
        dlg = ReceiptInfoDialog(rid, current_user=dict(ADMIN))
        dlg._pay_table.selectRow(0)
        dlg._edit_payment()
        M("receipts/_edit_payment", opened.pop())

        repo_dlg = SupplyReorderDialog()
        repo_dlg.low_stock_table.selectRow(0)
        repo_dlg._set_reorder_level()
        M("reorder/_set_reorder_level", opened.pop())
        repo_dlg.close()
