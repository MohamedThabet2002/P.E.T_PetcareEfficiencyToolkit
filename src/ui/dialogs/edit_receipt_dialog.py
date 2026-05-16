"""
Edit Receipt Dialog for the PET Application.

Opened when a receipt row is double-clicked in the Receipts ledger. Lets the
user edit the receipt's line items (quantity / unit price), add or remove
items, and apply a discount. Stock is reconciled for supply items on save.
"""

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QAbstractSpinBox,
    QDialogButtonBox,
    QMessageBox,
    QAbstractItemView,
    QListView,
)
from PyQt5.QtCore import Qt

import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.supply_repo as supply_repo
from src.core.repositories.receipt_adjustment_repo import add_adjustment
from src.core.repositories.audit_repo import record_action
from src.utils.formatters import format_currency
from src.utils.i18n import tr

LINE_TYPES = ["Supply", "Service", "Other"]


class EditReceiptDialog(QDialog):
    """Dialog to edit the line items and discount of a single receipt."""

    def __init__(self, receipt_id, parent=None, current_user=None):
        super().__init__(parent)
        self.receipt_id = receipt_id
        self._current_user = current_user or {}
        self._editors = []  # parallel list: (line_type, item_id, link_id, qty_spin, price_spin)
        self._deleted = []  # list of {op:"delete", item_type, item_id, link_id} removed on save

        header = sales_repo.get_receipt(receipt_id)
        if header is None:
            header = {"receipt_date": "", "discount": 0, "owner_name": ""}
        self._header = header

        self.setWindowTitle(tr("Edit Receipt #{id}").format(id=receipt_id))
        self.setMinimumSize(840, 560)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            tr("Date: {date}   Owner: {owner}").format(
                date=self._header.get("receipt_date") or "",
                owner=self._header.get("owner_name") or "",
            )
        )
        layout.addWidget(info)

        layout.addWidget(QLabel(tr("Items")))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [tr("Type"), tr("Item"), tr("Quantity"), tr("Unit Price"), tr("Line Total")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)

        # Add-item row
        add_row = QHBoxLayout()
        self.new_type = QComboBox()
        self.new_type.addItems([tr(t) for t in LINE_TYPES])
        self.new_type.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self.new_type.setView(QListView())
        self.new_type.currentIndexChanged.connect(self._reload_new_items)
        self.new_item = QComboBox()
        self.new_item.setMinimumWidth(200)
        self.new_qty = QSpinBox()
        self.new_qty.setRange(1, 99999)
        self.new_qty.setValue(1)
        self.new_price = QDoubleSpinBox()
        self.new_price.setRange(0, 999999)
        self.new_price.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.new_price.setEnabled(False)  # price managed from the supplies page only
        add_btn = QPushButton(tr("Add"))
        add_btn.clicked.connect(self._add_new_line)
        add_row.addWidget(self.new_type)
        add_row.addWidget(self.new_item, 1)
        add_row.addWidget(self.new_qty)
        add_row.addWidget(self.new_price)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        del_btn = QPushButton(tr("Remove Selected"))
        del_btn.clicked.connect(self._remove_selected)
        layout.addWidget(del_btn)

        # Discount (percentage) + total
        total_form = QFormLayout()
        self.discount_spin = QDoubleSpinBox()
        self.discount_spin.setRange(0, 100)
        self.discount_spin.setDecimals(2)
        self.discount_spin.setSuffix(" %")
        self.discount_spin.valueChanged.connect(self._recompute_total)
        total_form.addRow(tr("Discount:"), self.discount_spin)
        self.total_label = QLabel(format_currency(0))
        total_form.addRow(tr("Total:"), self.total_label)
        layout.addLayout(total_form)

        buttons = QDialogButtonBox()
        buttons.addButton(tr("Save"), QDialogButtonBox.AcceptRole)
        buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._handle_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_table()
        self._reload_new_items()
        # Express the stored cash discount as a percentage of the subtotal.
        subtotal = self._compute_subtotal()
        if subtotal > 0:
            pct = (float(self._header.get("discount") or 0) / subtotal) * 100.0
            self.discount_spin.setValue(round(pct, 2))
        self._recompute_total()

    # ------------------------- population -------------------------

    def _populate_table(self):
        items = sales_repo.get_receipt_line_items(self.receipt_id)
        if getattr(self, "_skip_consultation", False):
            items = [
                it for it in items
                if not (it["line_type"] == "Service"
                        and (it["name"] or "").strip().lower() == "consultation")
            ]
        self._editors.clear()
        self.table.setRowCount(0)
        for it in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(tr(it["line_type"])))
            self.table.setItem(row, 1, QTableWidgetItem(str(it["name"])))

            editable = it["line_type"] in ("Supply", "Service", "Other")
            qty = QSpinBox()
            qty.setRange(0 if editable else 1, 99999)
            qty.setValue(int(it["quantity"] or 0))
            qty.valueChanged.connect(self._recompute_total)
            price = QDoubleSpinBox()
            price.setRange(0, 999999)
            price.setDecimals(2)
            price.setButtonSymbols(QAbstractSpinBox.NoButtons)
            price.setValue(float(it["unit_price"] or 0))
            price.setEnabled(False)  # price managed from the supplies page only
            price.setToolTip(tr("Price is set in Supplies; edit it there."))
            if not editable:
                qty.setEnabled(False)
                price.setEnabled(False)

            self.table.setCellWidget(row, 2, qty)
            self.table.setCellWidget(row, 3, price)
            self.table.setItem(row, 4, QTableWidgetItem(format_currency(qty.value() * price.value())))
            self._editors.append(
                (it["line_type"], it["item_id"], it["link_id"], qty, price)
            )

    def _reload_new_items(self):
        self.new_item.clear()
        kind = LINE_TYPES[self.new_type.currentIndex()] if LINE_TYPES else "Supply"
        if kind == "Supply":
            for s in supply_repo.search_supplies():
                self.new_item.addItem(str(s["item_name"]), s["supply_id"])
                self.new_price.setValue(float(s.get("sell_price") or 0))
        elif kind == "Service":
            for name in supply_repo.get_all_services():
                self.new_item.addItem(str(name), name)
            self.new_price.setValue(0.0)
        else:
            self.new_item.setEditable(True)
            self.new_item.setInsertPolicy(QComboBox.NoInsert)
            self.new_item.addItem("")
            self.new_price.setValue(0.0)

    def _add_new_line(self):
        kind = LINE_TYPES[self.new_type.currentIndex()] if LINE_TYPES else "Supply"
        item_id = self.new_item.currentData()
        name = self.new_item.currentText().strip()
        if not item_id and kind != "Other" or (kind == "Other" and not name):
            QMessageBox.warning(self, tr("Input Error"), tr("Please select an item to add."))
            return

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(tr(kind)))
        self.table.setItem(row, 1, QTableWidgetItem(name))
        qty = QSpinBox()
        qty.setRange(1, 99999)
        qty.setValue(self.new_qty.value())
        qty.valueChanged.connect(self._recompute_total)
        price = QDoubleSpinBox()
        price.setRange(0, 999999)
        price.setDecimals(2)
        price.setButtonSymbols(QAbstractSpinBox.NoButtons)
        price.setValue(self.new_price.value())
        price.setEnabled(False)  # price managed from the supplies page only
        self.table.setCellWidget(row, 2, qty)
        self.table.setCellWidget(row, 3, price)
        self.table.setItem(row, 4, QTableWidgetItem(format_currency(qty.value() * price.value())))
        self._editors.append(
            ("__add__", {"kind": kind, "item_id": item_id}, name, qty, price)
        )
        self._recompute_total()

    def _remove_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a row to remove."))
            return
        line_type, item_id, link_id, qty, price = self._editors[row]
        # Newly-added rows have no DB record yet, so no deletion needed.
        if line_type != "__add__":
            self._deleted.append({
                "op": "delete",
                "item_type": line_type,
                "item_id": item_id,
                "link_id": link_id,
                "quantity": qty.value(),
                "unit_price": price.value(),
            })
        self.table.removeRow(row)
        del self._editors[row]
        self._recompute_total()

    # ------------------------- totals -------------------------

    def _compute_subtotal(self):
        subtotal = 0.0
        for line_type, item_id, link_id, qty, price in self._editors:
            subtotal += qty.value() * price.value()
        return subtotal

    def _discount_cash(self, subtotal):
        """Converts the percentage discount into a cash amount (cent-rounded).

        Rounding here keeps the saved discount identical to what the preview
        label shows - otherwise 33.33% of 30.00 stores 9.999 and the total
        drifts a fraction of a cent away from the rendered value.
        """
        return round(subtotal * (self.discount_spin.value() / 100.0), 2)

    def _recompute_total(self):
        subtotal = 0.0
        for i, (line_type, item_id, link_id, qty, price) in enumerate(self._editors):
            line_total = qty.value() * price.value()
            subtotal += line_total
            cell = self.table.item(i, 4)
            if cell is None:
                cell = QTableWidgetItem()
                self.table.setItem(i, 4, cell)
            cell.setText(f"$ {line_total:,.2f}")
        self.discount_spin.setEnabled(subtotal > 0)
        discount = self._discount_cash(subtotal)
        total = max(0.0, subtotal - discount)
        self.total_label.setText(f"$ {total:,.2f}")

    # ------------------------- save -------------------------

    def _record_adjustment_trail(self, old_total, details=None, changes=None):
        """Write the revision row + ADJUST audit when the total actually moved.

        Shared by EditReceiptDialog and VisitAdjustDialog so every receipt edit
        lands in ReceiptInfoDialog's Adjustments list with the same wording,
        whoever made it. Returns the receipt's new total.
        """
        header = sales_repo.get_receipt(self.receipt_id)
        new_total = float(header["total_price"] or 0.0) if header else old_total
        if abs(new_total - old_total) <= 0.004:
            return new_total
        user_id = (self._current_user or {}).get("user_id")
        add_adjustment(
            self.receipt_id,
            visit_id=(header or {}).get("visit_id") or self._header.get("visit_id"),
            adjusted_by=user_id,
            description=tr("Receipt adjusted: total {old} -> {new}").format(
                old=format_currency(old_total), new=format_currency(new_total)
            ),
            old_total=old_total,
            new_total=new_total,
            details=details or [],
        )
        record_action(
            "ADJUST", "receipts", self.receipt_id,
            changes=changes or [], user_id=user_id,
        )
        return new_total

    def _handle_save(self):
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
                # Packages left unchanged.
                continue
            elif int(qty.value()) <= 0:
                # Zeroing an editable line means "remove it" — never persist a
                # ghost 0-quantity line on the receipt.
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

        old_total = float(self._header.get("total_price") or 0.0)
        if sales_repo.update_receipt(
            self.receipt_id, self._discount_cash(self._compute_subtotal()), items,
            audit_user_id=(self._current_user or {}).get("user_id"),
        ):
            self._record_adjustment_trail(old_total)
            self.accept()
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to update receipt."))
