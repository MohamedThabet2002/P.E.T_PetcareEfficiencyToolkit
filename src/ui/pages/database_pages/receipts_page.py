"""
Financial Ledger module for the PET Application.
Provides a specialized view for managing sales receipts and logging general clinic expenses.
"""

from PyQt5.QtWidgets import (
    QTableWidgetItem, QMessageBox, QDialog, QFormLayout, QListView,
    QDateTimeEdit, QComboBox, QLineEdit, QDoubleSpinBox,
    QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QHeaderView,
    QAbstractItemView, QPushButton, QFrame, QScrollArea, QWidget,
)
from PyQt5.QtCore import Qt, QDateTime, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QPainter
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter

from src.ui.themes.color_palettes import get_active_palette, ThemeManager
from src.utils.formatters import format_currency, format_signed_currency
from src.utils.i18n import tr
import src.core.repositories.sales_repo as sales_repo
from src.modules.base_page import BaseEntityPage
from src.modules.receipt_card import (
    build_receipt_card, fit_content_table, refit_receipt_items_table,
    is_expense_code, receipt_kind_label,
)
from src.core.permissions import can
from src.ui.dialogs.edit_receipt_dialog import EditReceiptDialog

#=========================================== CONSTANTS ===================================================#

# Expense Categories
EXPENSE_CATEGORIES = [
    "Utilities",
    "Rent",
    "Salary",
    "Maintenance",
    "Tax",
    "Other",
]

# RECEIPT_COLUMN_MAP uses English strings for headers
RECEIPT_COLUMN_MAP = [
    ("ID", "id", 100),
    ("Date", "receipt_date", 150),
    ("Item Name", "item_name", 180),
    ("Category", "item_type", 100),
    ("Total Price", "total_price", 150),
    ("Type", "receipt_kind", 100),
    ("Notes", "notes", 200),
]


# is_expense_code / receipt_kind_label are re-exported from the shared
# receipt_card module (the card needs the Type label too).
def receipt_type_label(code):
    """Legacy fallback: localized label derived from a receipt_code prefix."""
    return tr("Expense") if is_expense_code(code) else str(code or "")

#============================================== CODE =====================================================#


class ReceiptInfoDialog(QDialog):
    """Professional receipt view for a single receipt.

    Renders the receipt as a printable-style card (clinic header, meta grid,
    itemized lines, subtotal/discount/total), folds the cumulative revision
    trail from ``receipt_adjustments`` in as signed delta lines, and provides a
    payment tracker (view / add / edit / delete) plus an Edit Receipt action â€”
    write actions are gated on ``edit_records``.
    """

    # Raised after any payment or receipt edit, so the ledger and every page
    # watching money (dashboard KPIs, owner finances) refresh their totals.
    data_changed = pyqtSignal()

    # Money formatting helpers -------------------------------------------------
    @staticmethod
    def _money(value):
        return format_currency(value)

    @staticmethod
    def _delta(value):
        return format_signed_currency(value)

    def __init__(self, receipt_id, parent=None, current_user=None):
        super().__init__(parent)
        self.receipt_id = receipt_id
        self._current_user = current_user
        self._can_write = bool(current_user) and can(current_user, "edit_records") or False
        self.setWindowTitle(tr("Receipt Details"))
        self.setMinimumSize(700, 680)

        outer = QVBoxLayout(self)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self._scroll)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(10)
        self._scroll.setWidget(self._content)

        self._rebuild()

    # ------------------------------------------------------------------ data
    def _collect(self):
        header = sales_repo.get_receipt(self.receipt_id) or {}
        header.setdefault("receipt_date", "")
        header.setdefault("total_price", 0)
        header.setdefault("discount", 0)
        header.setdefault("receipt_code", "")
        header.setdefault("receipt_kind", "")
        header.setdefault("owner_name", "")
        header.setdefault("owner_phone", "")
        header.setdefault("pet_name", "")
        items = sales_repo.get_receipt_line_items(self.receipt_id)

        from src.core.repositories.payment_repo import get_payments_for_receipt, get_total_paid
        from src.core.repositories.receipt_adjustment_repo import (
            get_adjustments_for_receipt, get_adj_writer_name,
        )
        payments = get_payments_for_receipt(self.receipt_id)
        paid = get_total_paid(self.receipt_id)
        adjustments = get_adjustments_for_receipt(self.receipt_id)
        return header, items, payments, paid, adjustments, get_adj_writer_name

    def _clear(self):
        self._receipt_frame = None

        def drop(item):
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                return
            sub = item.layout()
            if sub is not None:
                # A sub-layout (e.g. the payments toolbar) keeps its widgets
                # parented to the content widget, so they must be dropped one
                # by one or every rebuild would leave stale buttons behind.
                while sub.count():
                    drop(sub.takeAt(0))
                return
            if item.spacerItem():
                del item

        while self._content_layout.count():
            drop(self._content_layout.takeAt(0))

    def _rebuild(self, *args):
        self._clear()
        self.header, self.items, self.payments, self.paid, self.adjustments, self._adj_writer = self._collect()
        self.total = float(self.header.get("total_price") or 0)
        self.discount = float(self.header.get("discount") or 0)
        self.balance = round(self.total - self.paid, 2)
        self._build_receipt()
        self._build_payments()
        self._build_adjustments()
        # The stretch belongs BEFORE the footer, otherwise the buttons drift up
        # every time the dialog (or its scroll content) grows.
        self._content_layout.addStretch(1)
        self._build_footer()
        self._auto_fit_once()

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_auto_fitted", False):
            self._auto_fitted = True
            QTimer.singleShot(0, self._auto_fit_once)

    def _auto_fit_once(self):
        """Sizes the dialog to its content so the scrollbar hides on open.

        Re-fits each table with real (post-layout) column widths, sizes the
        dialog to the content, then keeps growing it until the scroll area's
        vertical scrollbar disappears. The trailing stretch in the content
        layout absorbs any extra space so the whole receipt is visible.
        """
        for table in self._content.findChildren(QTableWidget):
            if table.objectName() == "receiptItems":
                # The receipt's items table is pinned to its rows and never
                # scrolls; re-pin it here with the header's REAL section sizes
                # (post-layout, real column widths), or wrapped rows clipped
                # inside the table would be reachable only by its hidden
                # scrollbar / missing from the pixmap Print grabs.
                refit_receipt_items_table(table)
            else:
                fit_content_table(table, extra=26)
        # Force the scroll content to re-measure before we size the dialog:
        # otherwise a stale height hint makes the dialog stop growing and the
        # long receipt is painted clipped instead of scrolling.
        self._content_layout.activate()
        self._content.adjustSize()
        self.adjustSize()
        sbar = self._scroll.verticalScrollBar()
        guard = 0
        while sbar.isVisible() and guard < 10:
            self.resize(self.width(), self.height() + sbar.maximum())
            guard += 1

    # -------------------------------------------------------- receipt card
    def _build_receipt(self):
        frame = self._build_receipt_card()
        card_row = QHBoxLayout()
        card_row.addStretch()
        card_row.addWidget(frame)
        card_row.addStretch()
        self._content_layout.addLayout(card_row)

    def _build_receipt_card(self, client=False):
        """Builds the receipt card through the shared builder and returns it.

        ``client=True`` builds the client copy: the same card with the
        payment details (status strip + Paid/Balance line) left out and a
        thank-you footer, exactly like the receipt printed from the
        Add Visit wizard. That throwaway card is never added to the dialog.
        """
        card = build_receipt_card(
            self.header, self.items, self.discount, self.total,
            receipt_id=self.receipt_id, paid=self.paid, balance=self.balance,
            client=client,
        )
        # Grab target for Print (see _print_receipt). The client copy stays
        # off-layout, so it must not replace the on-screen card.
        if not client:
            self._receipt_frame = card.frame
        return card.frame

    # ------------------------------------------------------------ payments
    def _build_payments(self):
        section = QLabel(tr("Payments"))
        section.setProperty("class", "section-heading")
        self._content_layout.addWidget(section)

        if self._can_write:
            toolbar = QHBoxLayout()
            toolbar.addStretch()
            if self.balance > 0.004:
                add_btn = QPushButton(tr("Add Payment"))
                add_btn.clicked.connect(self._add_payment)
                toolbar.addWidget(add_btn)
            if self.balance < -0.004:
                # Overpaid (usually after a batch correction shrank the bill):
                # the credit has to be handed back to settle the receipt.
                refund_btn = QPushButton(tr("Record Refund"))
                refund_btn.clicked.connect(self._record_refund)
                toolbar.addWidget(refund_btn)
            edit_btn = QPushButton(tr("Edit Payment"))
            edit_btn.clicked.connect(self._edit_payment)
            toolbar.addWidget(edit_btn)
            delete_btn = QPushButton(tr("Delete Payment"))
            delete_btn.clicked.connect(self._delete_payment)
            toolbar.addWidget(delete_btn)
            self._content_layout.addLayout(toolbar)

        if not self.payments:
            empty = QLabel(tr("No payments recorded yet."))
            empty.setProperty("class", "muted-label")
            self._content_layout.addWidget(empty)
            return

        table = QTableWidget(len(self.payments), 4)
        table.setHorizontalHeaderLabels([tr("Date"), tr("Method"), tr("Amount"), tr("Notes")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.setWordWrap(True)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for pi, p in enumerate(self.payments):
            table.setItem(pi, 0, QTableWidgetItem(str(p.get("payment_date") or "")))
            table.setItem(pi, 1, QTableWidgetItem(tr(str(p.get("payment_method") or ""))))
            amt_item = QTableWidgetItem(self._money(p.get("amount") or 0))
            amt_item.setData(Qt.UserRole, p.get("payment_id"))
            table.setItem(pi, 2, amt_item)
            table.setItem(pi, 3, QTableWidgetItem(str(p.get("notes") or "")))
        fit_content_table(table)
        self._pay_table = table
        self._content_layout.addWidget(table)

    def _add_payment(self):
        if self.balance <= 0.004:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add Payment"))
        dialog.setMinimumWidth(360)
        dlayout = QFormLayout()
        root = QVBoxLayout(dialog)
        root.addLayout(dlayout)
        root.addStretch(1)

        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0.01, max(self.balance, 0.01))
        amount_spin.setDecimals(2)
        amount_spin.setPrefix("$ ")
        amount_spin.setValue(self.balance)
        amount_spin.selectAll()
        dlayout.addRow(tr("Amount:"), amount_spin)

        method_combo = QComboBox()
        method_combo.addItems([tr("Cash"), tr("Card"), tr("Bank Transfer"), tr("Other")])
        dlayout.addRow(tr("Method:"), method_combo)

        notes_edit = QLineEdit()
        notes_edit.setPlaceholderText(tr("Optional notes"))
        dlayout.addRow(tr("Notes:"), notes_edit)

        dbtns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dbtns.accepted.connect(dialog.accept)
        dbtns.rejected.connect(dialog.reject)
        root.addWidget(dbtns)

        if dialog.exec() == QDialog.Accepted:
            from src.core.repositories.payment_repo import add_payment
            method_map = {0: "Cash", 1: "Card", 2: "Bank Transfer", 3: "Other"}
            result = add_payment(
                self.receipt_id,
                amount_spin.value(),
                method_map.get(method_combo.currentIndex(), "Cash"),
                notes_edit.text().strip(),
                audit_user_id=(self._current_user or {}).get("user_id"),
            )
            if result:
                QMessageBox.information(self, tr("Success"), tr("Payment recorded."))
                self._rebuild()
                self.data_changed.emit()
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to record payment."))

    def _record_refund(self):
        """Gives back the credit sitting on an overpaid receipt."""
        credit = -self.balance
        if credit <= 0.004:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Record Refund"))
        dialog.setMinimumWidth(360)
        dlayout = QFormLayout()
        root = QVBoxLayout(dialog)
        root.addLayout(dlayout)
        root.addStretch(1)

        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0.01, max(credit, 0.01))
        amount_spin.setDecimals(2)
        amount_spin.setPrefix("$ ")
        amount_spin.setValue(credit)
        amount_spin.selectAll()
        dlayout.addRow(tr("Amount:"), amount_spin)

        method_combo = QComboBox()
        method_combo.addItems([tr("Cash"), tr("Card"), tr("Bank Transfer"), tr("Other")])
        dlayout.addRow(tr("Method:"), method_combo)

        notes_edit = QLineEdit()
        notes_edit.setPlaceholderText(tr("Optional notes"))
        dlayout.addRow(tr("Notes:"), notes_edit)

        dbtns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dbtns.accepted.connect(dialog.accept)
        dbtns.rejected.connect(dialog.reject)
        root.addWidget(dbtns)

        if dialog.exec() == QDialog.Accepted:
            from src.core.repositories.payment_repo import add_refund
            method_map = {0: "Cash", 1: "Card", 2: "Bank Transfer", 3: "Other"}
            result = add_refund(
                self.receipt_id,
                amount_spin.value(),
                method_map.get(method_combo.currentIndex(), "Cash"),
                notes_edit.text().strip() or tr("Refund of an overpayment"),
                audit_user_id=(self._current_user or {}).get("user_id"),
            )
            if result:
                QMessageBox.information(self, tr("Success"), tr("Refund recorded."))
                self._rebuild()
                self.data_changed.emit()
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to record refund."))

    def _edit_payment(self):
        if not self.payments:
            return
        row = self._pay_table_row()
        if row is None:
            QMessageBox.information(self, tr("Payments"), tr("Select a payment to edit."))
            return
        payment = self.payments[row]
        payment_id = payment.get("payment_id")
        old_amount = float(payment.get("amount") or 0)
        if old_amount < 0:
            # A refund row is not an editable payment: the amount spinner only
            # accepts positive values, so "editing" it would silently turn the
            # credit back into money the clinic paid out.
            QMessageBox.information(
                self, tr("Edit Payment"),
                tr("This row is a refund. Delete it and record a new one instead."))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Edit Payment"))
        dialog.setMinimumWidth(360)
        dlayout = QFormLayout()
        root = QVBoxLayout(dialog)
        root.addLayout(dlayout)
        root.addStretch(1)

        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0.01, max(self.total, 0.01))
        amount_spin.setDecimals(2)
        amount_spin.setPrefix("$ ")
        amount_spin.setValue(old_amount)
        dlayout.addRow(tr("Amount:"), amount_spin)

        method_combo = QComboBox()
        method_combo.addItems([tr("Cash"), tr("Card"), tr("Bank Transfer"), tr("Other")])
        method_map = {0: "Cash", 1: "Card", 2: "Bank Transfer", 3: "Other"}
        current_method = str(payment.get("payment_method") or "Cash")
        current_index = next((i for i, m in method_map.items() if m == current_method), 0)
        method_combo.setCurrentIndex(current_index)
        dlayout.addRow(tr("Method:"), method_combo)

        notes_edit = QLineEdit(str(payment.get("notes") or ""))
        notes_edit.setPlaceholderText(tr("Optional notes"))
        dlayout.addRow(tr("Notes:"), notes_edit)

        dbtns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dbtns.accepted.connect(dialog.accept)
        dbtns.rejected.connect(dialog.reject)
        root.addWidget(dbtns)

        if dialog.exec() == QDialog.Accepted:
            from src.core.repositories.payment_repo import update_payment
            ok = update_payment(
                payment_id,
                amount=amount_spin.value(),
                payment_method=method_map.get(method_combo.currentIndex(), "Cash"),
                notes=notes_edit.text().strip(),
                audit_user_id=(self._current_user or {}).get("user_id"),
            )
            if ok:
                QMessageBox.information(self, tr("Success"), tr("Payment updated."))
                self._rebuild()
                self.data_changed.emit()
            else:
                QMessageBox.warning(self, tr("Error"), tr("Failed to update payment."))

    def _delete_payment(self):
        if not self.payments:
            return
        row = self._pay_table_row()
        if row is None:
            QMessageBox.information(self, tr("Payments"), tr("Select a payment to delete."))
            return
        payment = self.payments[row]
        confirm = QMessageBox.question(
            self,
            tr("Delete Payment"),
            tr("Delete this payment of {amount}?").format(amount=self._money(payment.get("amount") or 0)),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        from src.core.repositories.payment_repo import delete_payment
        if delete_payment(payment.get("payment_id"),
                          audit_user_id=(self._current_user or {}).get("user_id")):
            self._rebuild()
            self.data_changed.emit()
        else:
            QMessageBox.warning(self, tr("Error"), tr("Failed to delete payment."))

    def _pay_table_row(self):
        table = getattr(self, "_pay_table", None)
        if table is None:
            return None
        row = table.currentRow()
        return row if row >= 0 and row < table.rowCount() else None

    # --------------------------------------------------------- adjustments
    def _build_adjustments(self):
        if not self.adjustments:
            return
        section = QLabel(tr("Adjustments"))
        section.setProperty("class", "section-heading")
        self._content_layout.addWidget(section)

        table = QTableWidget(len(self.adjustments), 3)
        table.setHorizontalHeaderLabels([tr("Date"), tr("Description"), tr("Adjustment")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.setWordWrap(True)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        palette = get_active_palette()
        running = None
        for ri, adj in enumerate(self.adjustments):
            fmt = str(adj.get("created_at") or "")
            writer = self._adj_writer(adj.get("adjusted_by"))
            when = "%s  %s" % (fmt, ("â€” " + str(writer)) if writer else "")
            table.setItem(ri, 0, QTableWidgetItem(when))

            desc = str(adj.get("description") or "")
            detail_parts = []
            for d in (adj.get("details") or []):
                item = str(d.get("item") or "")
                old_v = str(d.get("old_value") or "")
                new_v = str(d.get("new_value") or "")
                detail_parts.append("%s: %s â†’ %s" % (item, old_v, new_v))
            if detail_parts:
                desc = (desc + ("  |  " if desc else "") + "; ".join(detail_parts))
            table.setItem(ri, 1, QTableWidgetItem(desc))

            delta = float(adj.get("delta") or (float(adj.get("new_total") or 0) - float(adj.get("old_total") or 0)))
            delta_item = QTableWidgetItem(self._delta(delta))
            # A negative delta lowered the receipt total.
            delta_item.setForeground(QBrush(
                palette.qcolor("state_success") if delta < 0
                else palette.qcolor("state_danger")
            ))
            table.setItem(ri, 2, delta_item)
            running = float(adj.get("new_total") or running or 0)
        fit_content_table(table)
        self._content_layout.addWidget(table)

        if running is not None:
            current = QLabel(tr("Adjusted Total: $ {total:,.2f}").format(total=running))
            current.setStyleSheet(
                "font-weight: bold; color: %s;" % get_active_palette().qcolor("state_success").name()
            )
            self._content_layout.addWidget(current)

    # -------------------------------------------------------------- footer
    def _build_footer(self):
        row = QHBoxLayout()
        row.addStretch()
        print_btn = QPushButton(tr("Print"))
        print_btn.clicked.connect(self._print_receipt)
        row.addWidget(print_btn)
        client_btn = QPushButton(tr("Print for Client"))
        client_btn.clicked.connect(self._print_for_client)
        row.addWidget(client_btn)
        if self._can_write:
            edit_btn = QPushButton(tr("Edit Receipt"))
            edit_btn.setProperty("class", "primary-action")
            edit_btn.clicked.connect(self._edit_receipt)
            row.addWidget(edit_btn)
        ok_btn = QPushButton(tr("OK"))
        ok_btn.clicked.connect(self.accept)
        row.addWidget(ok_btn)
        self._content_layout.addLayout(row)

    # ---------------------------------------------------------------- print
    def _render_receipt_pixmap(self):
        """Grabs the receipt card as an image for print."""
        frame = getattr(self, "_receipt_frame", None)
        if frame is None:
            return None
        # Grow to the full content height first: a stale layout must never hand
        # grab a clipped viewport, or the printed receipt would drop its lower
        # lines.
        if frame.layout() is not None:
            frame.layout().activate()
        table = frame.findChild(QTableWidget, "receiptItems")
        if table is not None:
            # Re-pin from the header's true section sizes (wrapped rows can
            # exceed a pre-layout estimate), or the printed copy would drop
            # the rows that don't fit the too-short fixed height.
            refit_receipt_items_table(table)
            if frame.layout() is not None:
                frame.layout().activate()
        frame.resize(frame.width(),
                     max(frame.height(), frame.minimumSizeHint().height()))
        pix = frame.grab()
        return pix if not pix.isNull() else None

    @staticmethod
    def _paint_pixmap_on_printer(printer, pix):
        """Draws the receipt pixmap centered and scaled to fit a printer page."""
        painter = QPainter(printer)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        page_rect = printer.pageRect(QPrinter.DevicePixel)
        painter.fillRect(page_rect, Qt.white)
        scale = min(page_rect.width() / pix.width(), page_rect.height() / pix.height(), 2.0)
        target_w = int(pix.width() * scale)
        target_h = int(pix.height() * scale)
        x = (page_rect.width() - target_w) // 2
        y = (page_rect.height() - target_h) // 2
        painter.drawPixmap(x, y, target_w, target_h, pix)
        painter.end()

    def _print_receipt(self):
        """Opens the system print dialog to print this receipt."""
        pix = self._render_receipt_pixmap()
        if pix is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._paint_pixmap_on_printer(printer, pix)

    def _render_client_receipt_pixmap(self):
        """Grabs a throwaway client copy of the card (no payment details)."""
        frame = self._build_receipt_card(client=True)
        # Parent it so it picks up the dialog's style/palette. It is never
        # shown (setParent hides it), so nothing paints over the dialog.
        frame.setParent(self)
        layout = frame.layout()
        if layout is not None:
            layout.activate()
        frame.adjustSize()
        # adjustSize sizes the frame to its fixed 480px width; the table's
        # rows may now wrap to taller lines than the pre-layout estimate, and
        # a too-short pin would cut the client copy's last rows.
        table = frame.findChild(QTableWidget, "receiptItems")
        if table is not None:
            refit_receipt_items_table(table)
        if layout is not None:
            layout.activate()
        # Clamp up to the true content minimum so no row is left off.
        frame.resize(frame.width(),
                     max(frame.height(), frame.minimumSizeHint().height()))
        pix = frame.grab()
        frame.setParent(None)
        frame.deleteLater()
        return pix if not pix.isNull() else None

    def print_for_client(self, parent=None):
        """Prints the client copy of a fully paid receipt.

        The client copy carries no payment details, so a receipt with a
        balance outstanding is refused with an explanation. The optional
        ``parent`` hosts the refusal and print dialogs for callers outside
        this dialog (the Add Visit wizard's success box). Returns True once
        the print dialog has been confirmed.
        """
        host = parent or self
        # Only a settled receipt may leave the clinic as a client copy â€”
        # an unpaid one would show a balance the client shouldn't see.
        if self.balance > 0.004:
            QMessageBox.information(
                host,
                tr("Not Fully Paid"),
                tr("Only fully paid receipts are printed to clients. "
                   "Settle the remaining balance first."),
            )
            return False
        pix = self._render_client_receipt_pixmap()
        if pix is None:
            return False
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, host)
        if dialog.exec_() != QDialog.Accepted:
            return False
        self._paint_pixmap_on_printer(printer, pix)
        return True

    def _print_for_client(self):
        """Prints the client copy of a fully paid receipt."""
        self.print_for_client()

    def _edit_receipt(self):
        dialog = EditReceiptDialog(self.receipt_id, self, current_user=self._current_user)
        if dialog.exec():
            self._rebuild()
            self.data_changed.emit()


class ReceiptsPage(BaseEntityPage):
    """A page to display receipt records from the database."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Dynamically creates the receipts tab using BaseEntityPage logic."""
        header_keys = [tr(col[0]) for col in RECEIPT_COLUMN_MAP]
        widths = [col[2] for col in RECEIPT_COLUMN_MAP]

        self.create_tab(
            name="Expenses",
            headers=header_keys,
            filter_items=[tr("All")] + header_keys,
            add_callback=self.add_expense_dialog,
            delete_callback=self.delete_selected_receipt,
            refresh_callback=self.refresh_receipts_table,
            col_widths=widths,
            link_cells=[0],  # ID (clickable -> receipt details)
        )

        # Double-click opens the edit dialog (see on_row_double_clicked).
        self.refresh_receipts_table()

        # Refresh row colors when theme changes
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)

        # Set default sort: ID column from highest to lowest
        self.tables["Expenses"].sortByColumn(0, Qt.DescendingOrder)

    def retranslate_ui(self):
        """Updates the tab title, headers, and table data when language changes."""
        super().retranslate_ui()

        self.tabs.setTabText(0, tr("Expenses"))

        header_keys = [tr(col[0]) for col in RECEIPT_COLUMN_MAP]
        self.tables["Expenses"].setHorizontalHeaderLabels(header_keys)
        self.refresh_receipts_table()

    def _filter_field(self):
        """Stable column key for the chosen filter, never a translated label.

        The combo shows ``tr(header)`` but the repo matches on the column key,
        so in Arabic (or any language) the filter must not be derived from the
        visible text - index 0 is "All", the rest follow RECEIPT_COLUMN_MAP.
        """
        combo = self.filters["Expenses"]
        idx = combo.currentIndex()
        if idx <= 0:
            return "All"
        if 0 < idx <= len(RECEIPT_COLUMN_MAP):
            return RECEIPT_COLUMN_MAP[idx - 1][1]
        return combo.currentText() or "All"

    def refresh_receipts_table(self, text: str = ""):
        """Fetches data from the database and populates the table."""
        data = sales_repo.get_receipt_items(text, self._filter_field())

        table = self.tables["Expenses"]
        palette = get_active_palette()

        table.setSortingEnabled(False)
        table.setRowCount(0)

        for row_data in data:
            row = table.rowCount()
            table.insertRow(row)

            for col, (_, key, _) in enumerate(RECEIPT_COLUMN_MAP):
                val = row_data[key]

                item = QTableWidgetItem()

                if key == "receipt_kind":
                    label = receipt_kind_label(val, row_data.get("receipt_code"))
                    is_expense = label == tr("Expense")
                    item.setText(label)
                    color = (
                        palette.qcolor("state_danger")
                        if is_expense
                        else palette.qcolor("state_success")
                    )
                    item.setForeground(color)
                elif isinstance(val, (int, float)):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")

                table.setItem(row, col, item)

        table.setSortingEnabled(True)

    def _open_receipt_info(self, row, col=None):
        """Opens the receipt details dialog for the clicked row."""
        table = self.tables["Expenses"]
        if not (0 <= row < table.rowCount()):
            return

        id_item = table.item(row, 0)
        if not id_item:
            return
        receipt_id = id_item.data(Qt.DisplayRole)
        if receipt_id is None:
            receipt_id = id_item.text()
        try:
            receipt_id = int(receipt_id)
        except (TypeError, ValueError):
            return
        if sales_repo.get_receipt(receipt_id) is not None:
            dialog = ReceiptInfoDialog(receipt_id, self, current_user=self._current_user)
            # Payments edited inside the dialog move money the whole app shows.
            dialog.data_changed.connect(self._on_receipt_changed)
            if dialog.exec():
                self.refresh_receipts_table()
                self.data_changed.emit()

    def _on_receipt_changed(self):
        """A receipt/payment changed inside the details dialog: refresh + fan out."""
        self.refresh_receipts_table()
        self.data_changed.emit()

    def on_link_clicked(self, category, row, col, value):
        """Opens the receipt details dialog when a cell is clicked."""
        self._open_receipt_info(row, col)

    def on_row_double_clicked(self, category, row):
        """Opens the edit receipt dialog when a row is double-clicked."""
        table = self.tables["Expenses"]
        if row is None or not (0 <= (row or 0) < table.rowCount()):
            return
        if not can(self._current_user, "edit_records"):
            return
        id_item = table.item(row, 0)
        if not id_item:
            return
        receipt_id = id_item.data(Qt.DisplayRole)
        if receipt_id is None:
            receipt_id = id_item.text()
        self._open_edit_receipt_dialog(int(receipt_id))

    def _open_edit_receipt_dialog(self, receipt_id):
        """Opens the receipt editor dialog and refreshes after saving."""
        dialog = EditReceiptDialog(receipt_id, self, current_user=self._current_user)
        if dialog.exec():
            self.refresh_receipts_table()
            self.data_changed.emit()

    def add_expense_dialog(self):
        """Opens a dialog to record a general business expense."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add General Expense"))
        dialog.setFixedWidth(400)

        form = QFormLayout()

        date_edit = QDateTimeEdit(QDateTime.currentDateTime())
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")

        category = QComboBox()
        category.addItems([tr(cat) for cat in EXPENSE_CATEGORIES])
        category.setView(QListView())
        category.view().window().setAttribute(Qt.WA_TranslucentBackground)
        category.view().window().setWindowFlags(
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        category.setEditable(True)

        description = QLineEdit()
        description.setPlaceholderText(tr("e.g., Electricity Bill Jan"))

        amount = QDoubleSpinBox()
        amount.setRange(0, 999999)
        amount.setSuffix(" $")

        notes = QLineEdit()

        form.addRow(tr("Date:"), date_edit)
        form.addRow(tr("Category*:"), category)
        form.addRow(tr("Description*:"), description)
        form.addRow(tr("Amount*:"), amount)
        form.addRow(tr("Notes:"), notes)

        buttons = QDialogButtonBox()
        buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)

        def handle_accept():
            cat_text = category.currentText().strip()
            desc_text = description.text().strip().title()

            if not cat_text or not desc_text:
                QMessageBox.warning(
                    dialog,
                    tr("Input Error"),
                    tr("Category and Description are required."),
                )
                return

            if amount.value() <= 0:
                QMessageBox.warning(
                    dialog,
                    tr("Input Error"),
                    tr("Amount must be greater than zero."),
                )
                return

            if sales_repo.add_general_expense(
                date_edit.dateTime().toString("yyyy-MM-dd HH:mm"),
                cat_text,
                desc_text,
                amount.value(),
                notes.text().strip(),
                audit_user_id=(self._current_user or {}).get("user_id"),
            ):
                self.refresh_receipts_table()
                self.data_changed.emit()
                dialog.accept()
            else:
                QMessageBox.warning(
                    dialog,
                    tr("Error"),
                    tr("Failed to save the expense. Please try again."),
                )

        root = QVBoxLayout(dialog)
        root.addLayout(form)
        root.addStretch(1)
        root.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    def delete_selected_receipt(self):
        """Deletes the selected receipt from the ledger."""
        table = self.tables["Expenses"]
        row = table.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                tr("Selection Required"),
                tr("Please select a row to delete."),
            )
            return

        receipt_id = table.item(row, 0).text()
        item_name = table.item(row, 2).text()

        msg = tr("Are you sure you want to delete receipt #{id} ({name})?\n"
    "This will remove it from financial records.").format(id=receipt_id, name=item_name)
        if QMessageBox.question(
            self,
            tr("Confirm Delete"),
            msg,
        ) == QMessageBox.Yes:
            if sales_repo.delete_receipt(
                receipt_id,
                audit_user_id=(self._current_user or {}).get("user_id"),
            ):
                self.refresh_receipts_table()
                self.data_changed.emit()

