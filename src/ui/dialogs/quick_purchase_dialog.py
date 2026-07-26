"""Quick retail purchase dialog for the PET Application.

Records a walk-in (visit-less) retail sale receipt through the dedicated sales
flow, creating the owner on demand when needed. Extracted from visits_page.py.
"""

from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QDateTimeEdit, QLabel, QVBoxLayout, QHBoxLayout,
    QMessageBox, QLineEdit, QSizePolicy, QDoubleSpinBox, QComboBox,
)

from src.core.repositories import client_repo
import src.core.repositories.sales_repo as sales_repo
from src.config.constants import DATE_TIME_FORMAT_UI
from src.ui.dialogs.base_clinical_dialog import SupplyReceiptMixin
from src.utils.i18n import tr

QUICK_PURCHASE_DIALOG_WINDOW_MIN_SIZE = (860, 620)


class QuickPurchaseDialog(QDialog, SupplyReceiptMixin):
    def _update_total(self):
        """Calculates and updates the estimated total cost for the quick purchase."""
        subtotal = 0.0

        if hasattr(self, "_supply_rows"):
            for _cat_cb, item_cb, qty_sb, price_sb in self._supply_rows:
                if item_cb.currentText():
                    subtotal += float(qty_sb.value()) * float(price_sb.value())

        if hasattr(self, "_package_rows"):
            for _pkg_cb, qty_sb, price_sb in self._package_rows:
                subtotal += float(qty_sb.value()) * float(price_sb.value())

        discount = self._discount_cash(subtotal)
        self._purchase_subtotal = subtotal
        self._purchase_discount = discount

        if hasattr(self, "amount_paid_spin"):
            total = round(subtotal - discount, 2)
            if not self._paid_touched:
                # Default: whatever the total is, that is what was paid.
                self.amount_paid_spin.blockSignals(True)
                self.amount_paid_spin.setMaximum(total)
                self.amount_paid_spin.setValue(total)
                self.amount_paid_spin.blockSignals(False)
            else:
                self.amount_paid_spin.setMaximum(total)

        if hasattr(self, "total_label"):
            self.total_label.setText(
                tr("<b>Estimated Total: ${total:,.2f}</b>").format(
                    total=round(subtotal - discount, 2))
            )

    def _on_paid_changed(self, _value):
        """Remembers a custom paid amount so the basket total stops overriding it."""
        self._paid_touched = True

    def payment_method(self):
        """The stored method for the combo (display index -> English value)."""
        return {0: "Cash", 1: "Card", 2: "Bank Transfer", 3: "Other"}.get(
            self.pay_method_combo.currentIndex(), "Cash")

    def _discount_cash(self, subtotal):
        """Converts the percentage discount spin into cash for the given subtotal."""
        pct = self.discount_percent_spin.value() if hasattr(self, "discount_percent_spin") else 0
        return round(subtotal * pct / 100.0, 2)

    def __init__(self, parent=None, current_user=None):

        super().__init__(parent)
        self.setWindowTitle(tr("Quick Purchase"))
        self.setMinimumSize(*QUICK_PURCHASE_DIALOG_WINDOW_MIN_SIZE)
        self._current_user = current_user or {}

        root = QVBoxLayout(self)

        # Date + owner name share a single row.
        top = QHBoxLayout()
        self.date_edit = QDateTimeEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat(DATE_TIME_FORMAT_UI)
        self.date_edit.setDateTime(QDateTime.currentDateTime())
        top.addWidget(QLabel(tr("Date:")))
        top.addWidget(self.date_edit)

        self.client_name_edit = QLineEdit()  # This is intentionally left empty by default
        self.client_name_edit.setPlaceholderText(tr("Owner Name"))

        # 250px minimum, left-aligned, and allowed to expand with the dialog/window.
        self.client_name_edit.setMinimumWidth(250)
        self.client_name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.client_name_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        top.addWidget(QLabel(tr("Owner Name") + ":"))
        top.addWidget(self.client_name_edit, 1)
        root.addLayout(top)


        # Supplies receipt (reuse mixin UI)
        form_layout = QVBoxLayout()
        root.addLayout(form_layout)
        self._setup_supplies_section(form_layout)

        # Service packages (reuse mixin UI, same as the add visit dialog).
        # Stretched like the supplies list so both lists grow with the dialog.
        self._setup_packages_section(form_layout, stretch=3)

        # Total label (for estimated purchase total)
        self.total_label = QLabel(tr("<b>Estimated Total: $0.00</b>"))
        self.total_label.setProperty("name", "total-price")

        self.buttons = QDialogButtonBox()
        self.ok_button = self.buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        self.cancel_button = self.buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.handle_accept)
        self.buttons.rejected.connect(self.reject)

        self._paid_touched = False
        footer_layout = QHBoxLayout()
        footer_layout.addWidget(QLabel(tr("Discount:") + " "))
        self.discount_percent_spin = QDoubleSpinBox()
        self.discount_percent_spin.setRange(0, 100)
        self.discount_percent_spin.setSuffix(" %")
        self.discount_percent_spin.setValue(0)
        self.discount_percent_spin.setFixedWidth(90)
        self.discount_percent_spin.valueChanged.connect(self._update_total)
        footer_layout.addWidget(self.discount_percent_spin)
        footer_layout.addSpacing(16)
        footer_layout.addWidget(QLabel(tr("Amount Paid:") + " "))
        self.amount_paid_spin = QDoubleSpinBox()
        self.amount_paid_spin.setPrefix("$ ")
        self.amount_paid_spin.setRange(0.0, 999999.99)
        self.amount_paid_spin.setDecimals(2)
        self.amount_paid_spin.setFixedWidth(120)
        self.amount_paid_spin.valueChanged.connect(self._on_paid_changed)
        footer_layout.addWidget(self.amount_paid_spin)
        footer_layout.addSpacing(16)
        footer_layout.addWidget(QLabel(tr("Method:") + " "))
        self.pay_method_combo = QComboBox()
        self.pay_method_combo.addItems([tr("Cash"), tr("Card"), tr("Bank Transfer"), tr("Other")])
        self.pay_method_combo.setFixedWidth(110)
        footer_layout.addWidget(self.pay_method_combo)
        footer_layout.addSpacing(16)
        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.buttons)

        root.addLayout(footer_layout)

        # Initial total
        self._update_total()


    def handle_accept(self):
        # Validate the basket before touching the database so an empty purchase
        # never leaves a stray owner row behind.
        items = self.get_final_items()
        packages = self.get_final_packages()
        if not items and not packages:
            QMessageBox.warning(self, tr("Validation Error"), tr("Please add at least one receipt item."))
            return

        name_input = self.client_name_edit.text().strip()
        if not name_input:
            name_input = tr("Anonymous")

        formatted_name = name_input.title()
        client = client_repo.get_clients_by_name_exact(formatted_name)
        if client:
            client_id = client[0]["client_id"]
        else:
            client_id = client_repo.add_client(
                formatted_name, "",
                audit_user_id=(self._current_user or {}).get("user_id"),
            )
            if not client_id:
                QMessageBox.critical(self, tr("Error"), tr("Failed to create client"))
                return
            client_id = int(client_id)

        # The amount paid defaults to the final total (discount included) unless
        # the user typed a custom figure; the basket here is the source of truth
        # so a monkeypatched/get_final_items basket is settled correctly too.
        subtotal = sum(float(it["quantity"]) * float(it["price"]) for it in items) + sum(
            float(pkg.get("total_price") or 0.0) * int(pkg.get("quantity") or 1)
            for pkg in packages
        )
        discount = self._discount_cash(subtotal)
        total = round(subtotal - discount, 2)
        if self._paid_touched:
            paid_amount = min(self.amount_paid_spin.value(), total)
        else:
            paid_amount = total

        result = sales_repo.create_sale_receipt_for_quick_purchase(
            owner_id=client_id,
            receipt_date_sql=self.date_edit.dateTime().toString(DATE_TIME_FORMAT_UI),
            items=items,
            packages=packages,
            user_id=(self._current_user or {}).get("user_id"),
            # Walk-in retail is paid at the counter, so the receipt is settled
            # in full as soon as it is recorded.
            payment_notes=tr("Paid at quick purchase"),
            discount=discount,
            paid_amount=paid_amount,
            payment_method=self.payment_method(),
        )

        if isinstance(result, str) and result.startswith("STOCK_ERROR"):
            _, name, _qty = result.split("|")
            QMessageBox.warning(self, tr("Stock Error"), tr("Not enough stock for {item}.").format(item=name))
            return

        if not result:
            QMessageBox.critical(self, tr("Error"), tr("Failed to record purchase."))
            return

        self._show_success(
            tr("Purchase recorded. Receipt ID: #{id}").format(id=result),
            receipt_id=result,
        )
        self.accept()

    def _show_success(self, msg, receipt_id):
        """Confirmation after a successful sale.

        Offers OK to close and Print to hand the receipt to the client -
        the same shape as the Add Visit wizard's success box.
        """
        box = QMessageBox(QMessageBox.Information, tr("Success"), str(msg),
                          QMessageBox.Ok, self)
        print_btn = box.addButton(tr("Print"), QMessageBox.ActionRole)
        box.setDefaultButton(QMessageBox.Ok)
        box.exec_()
        if box.clickedButton() is print_btn:
            self._print_receipt(receipt_id)

    def _print_receipt(self, receipt_id):
        """Prints the receipt exactly like Print for Client does.

        Delegates to ``ReceiptInfoDialog.print_for_client``: the client copy
        of the card, refused with the Receipts page's message when the
        receipt is not fully paid.
        """
        # Local import: the receipt page pulls in the whole pages package,
        # and this dialog must not drag that in at import time.
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
        info = ReceiptInfoDialog(receipt_id, parent=self,
                                 current_user=self._current_user)
        try:
            info.print_for_client(parent=self)
        finally:
            info.setParent(None)
            info.deleteLater()