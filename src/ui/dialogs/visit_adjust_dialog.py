"""
Visit receipt adjustment dialog.

Opened from the Visit Details dialog's "Adjust" action (edit mode). Subclasses
:class:`EditReceiptDialog` to edit a visit's sale receipt, with two differences:

* The Consultation service line is hidden from the item table (consult is
  driven by the dedicated checkbox row below instead, so it can never be
  edited twice).
* On save the old vs new total is compared and a cumulative revision-trail
  row is stored in ``receipt_adjustments`` (plus an ADJUST audit entry) so
  the Receipt Details dialog can render the delta table.
"""

from PyQt5.QtWidgets import (
    QLabel,
    QCheckBox,
    QHBoxLayout,
    QMessageBox,
)

import src.core.repositories.sales_repo as sales_repo
from src.config.constants import DEFAULT_CONSULT_FEE
from src.utils.settings_manager import SettingsManager
from src.utils.formatters import format_currency
from src.utils.i18n import tr
from src.ui.dialogs.edit_receipt_dialog import EditReceiptDialog


class VisitAdjustDialog(EditReceiptDialog):
    """Receipt editor for a visit's sale receipt with a consult-charge toggle."""

    def __init__(self, visit_id, receipt_id, parent=None, current_user=None):
        self._visit_id = visit_id
        self._skip_consultation = True  # read by the base _populate_table
        super().__init__(receipt_id, parent=parent, current_user=current_user)

        self.setWindowTitle(tr("Adjust Receipt #{id}").format(id=receipt_id))
        self._consult_fee = float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))

        consult_row = QHBoxLayout()
        consult_row.setContentsMargins(0, 4, 0, 4)
        self.consult_cb = QCheckBox(
            f"{tr('Consult Charge Applied?')} ({format_currency(self._consult_fee)})"
        )
        self.consult_cb.setChecked(sales_repo.has_consultation_service(receipt_id))
        consult_row.addWidget(QLabel(tr("Consultation charge")))
        consult_row.addWidget(self.consult_cb)
        consult_row.addStretch()

        consult_widget = QLabel()
        consult_widget.setLayout(consult_row)
        # Insert below the date/owner info label (index 1 in the base layout).
        self.layout().insertWidget(1, consult_widget)

        self.consult_cb.toggled.connect(self._recompute_total)
        self._recompute_total()

    def _recompute_total(self):
        super()._recompute_total()
        if not getattr(self, "consult_cb", None):
            return
        subtotal = self._compute_subtotal()
        consult = self._consult_fee if self.consult_cb.isChecked() else 0.0
        total = max(0.0, subtotal - self._discount_cash(subtotal) + consult)
        self.total_label.setText(format_currency(total))

    def _handle_save(self):
        consult_on = self.consult_cb.isChecked()
        old_total = float(self._header.get("total_price") or 0.0)
        consult_changed = sales_repo.reconcile_consultation(
            self.receipt_id, consult_on, self._consult_fee
        )

        items = list(self._deleted)
        for line_type, item_id, link_id, qty, price in self._editors:
            if line_type == "__add__":
                items.append({
                    "op": "add",
                    "item_type": item_id["kind"],
                    "item_id": item_id["item_id"],
                    "name": link_id,
                    "quantity": qty.value(),
                    "unit_price": price.value(),
                })
            elif line_type == "Package":
                continue
            elif int(qty.value()) <= 0:
                # Zeroing a line removes it (no ghost 0-quantity line).
                items.append({
                    "op": "delete",
                    "item_type": line_type,
                    "item_id": item_id,
                    "link_id": link_id,
                })
            else:
                items.append({
                    "op": "update",
                    "item_type": line_type,
                    "item_id": item_id,
                    "link_id": link_id,
                    "quantity": qty.value(),
                    "unit_price": price.value(),
                })

        user_id = (self._current_user or {}).get("user_id")
        if not sales_repo.update_receipt(
            self.receipt_id, self._discount_cash(self._compute_subtotal()), items,
            audit_user_id=user_id,
        ):
            QMessageBox.critical(self, tr("Error"), tr("Failed to update receipt."))
            return

        details = []
        changes = []
        if consult_changed:
            details.append({
                "item": tr("Consultation"),
                "old_value": tr("No") if consult_on else tr("Yes"),
                "new_value": tr("Yes") if consult_on else tr("No"),
            })
            changes.append({
                "field_name": tr("Consultation"),
                "old_value": "1" if (not consult_on) else "0",
                "new_value": "1" if consult_on else "0",
            })
        # Shared with EditReceiptDialog: same trail for every receipt edit.
        self._record_adjustment_trail(old_total, details=details, changes=changes)
        self.accept()