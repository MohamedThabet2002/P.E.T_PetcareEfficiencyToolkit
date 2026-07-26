"""The printable receipt card - one source of truth.

Both the Receipt Details dialog (Receipts page / visit billing) and the Add
Visit wizard's step-4 preview build the card through this module, so the
wizard preview can never drift from the receipt the clinic later opens or
prints. The wizard renders the client copy (no payment details) because it
has no receipt number yet; everything else is the very same card.
"""

import os
from typing import NamedTuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QFormLayout, QFrame, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from src.config.constants import DEFAULT_CLINIC_NAME
from src.config.paths import ICONS_DIR
from src.ui.themes.color_palettes import get_active_palette
from src.utils.formatters import format_currency
from src.utils.i18n import tr
from src.utils.settings_manager import SettingsManager

# The Receipt Details card's width. The wizard preview used to roll its own
# 360px card; it now shares this builder, so both sides are this wide.
RECEIPT_CARD_WIDTH = 480

# The clinic logo sits above the clinic name; width/height cap with the aspect
# ratio preserved, so a portrait logo is not squashed and a wide banner does
# not swallow the card.
RECEIPT_LOGO_SIZE = (140, 56)


def is_expense_code(code):
    """True when a receipt_code belongs to an expense.

    Expense codes are unique per row (``EXPENSE-001``, ``EXPENSE-002``, ...), so
    they must be matched by prefix rather than against one exact value. Legacy
    rows created before the codes became unique use a bare ``Expense``.
    """
    return str(code or "").upper().startswith("EXPENSE")


def receipt_kind_label(kind, code=None):
    """Localized display label for a receipt's ``receipt_kind``.

    Falls back to the code prefix when the kind is empty (rows written before
    the kind column existed), so the ledger never shows a blank type.
    """
    normalized = str(kind or "").strip().lower()
    if normalized not in ("visit", "retail", "expense"):
        upper_code = str(code or "").upper()
        if is_expense_code(upper_code):
            normalized = "expense"
        elif upper_code.startswith("VISIT"):
            normalized = "visit"
        elif upper_code.startswith("RETAIL"):
            normalized = "retail"
    return {
        "visit": tr("Visit"),
        "retail": tr("Retail"),
        "expense": tr("Expense"),
    }.get(normalized, str(kind or code or ""))


def fit_content_table(table, extra=26):
    """Sizes a table to its real content so rows are never clipped.

    Requires the vertical header to auto-size rows (ResizeToContents).
    Uses per-row content heights (accounts for wrapped text) and only sets
    a minimum height - inside a scroll area the table can still grow.
    """
    header_h = table.horizontalHeader().sizeHint().height()
    rows = table.rowCount()
    if rows <= 0:
        table.setMinimumHeight(header_h + 24)
        return
    content_h = sum(max(table.sizeHintForRow(r), table.rowHeight(r)) for r in range(rows))
    table.setMinimumHeight(header_h + content_h + extra)


def fit_receipt_items_table(table, extra=8):
    """Pins the receipt's item table to its rows so it can never scroll.

    Unlike :func:`fit_content_table` (a floor that lets a payments/reports
    table grow inside a scroll area), the receipt must always render every
    line: a scrollbar here would clip the card on screen *and* the pixmap that
    Print sends to the printer. The table is therefore fixed to the rows'
    height and its scrollbars are switched off, so the card grows and the
    surrounding dialog scrolls instead.
    """
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    header_h = table.horizontalHeader().sizeHint().height()
    rows = table.rowCount()
    content_h = sum(max(table.sizeHintForRow(r), table.rowHeight(r)) for r in range(rows))
    table.setFixedHeight(header_h + content_h + extra)


def refit_receipt_items_table(table, extra=8):
    """Re-pins a receipt items table to its rows once the real sizes are known.

    :func:`fit_receipt_items_table` must estimate before the table sits in the
    final layout (its geometry is still the widget default), so a card laid out
    at its real, narrower width can wrap item names to taller lines than the
    estimate assumed. The fixed height then stays too short: the last rows are
    clipped inside the table with no scrollbar to fetch them - only the mouse
    wheel could (their own hidden scrollbar answers it, which read as "clipped
    with no way to scroll"). This forces the header to recompute the section
    heights at the table's CURRENT column widths and re-pins the height to the
    true content. Call again after the table has been laid out - the wizard's
    step switch/rebuild and every print grab.
    """
    table.verticalHeader().resizeSections(QHeaderView.ResizeToContents)
    header_h = table.horizontalHeader().sizeHint().height()
    rows = table.rowCount()
    content_h = sum(table.verticalHeader().sectionSize(r) for r in range(rows))
    table.setFixedHeight(header_h + content_h + extra)


def _caption(text):
    cap = QLabel(text)
    cap.setProperty("class", "receipt-meta-caption")
    return cap


def _clinic_logo_pixmap():
    """The clinic logo shown at the top of every receipt.

    Follows the rest of the app (side menu, login dialog, window icon): the
    Settings -> Identity custom logo when one is set and readable, otherwise
    the bundled default. A null pixmap (missing/unreadable file) signals the
    caller to skip the logo row entirely.
    """
    custom_path = SettingsManager.get("custom_logo", "")
    if custom_path and os.path.exists(custom_path):
        source = custom_path
    else:
        source = os.path.join(ICONS_DIR, "logo.png")
    pixmap = QPixmap(source)
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        RECEIPT_LOGO_SIZE[0], RECEIPT_LOGO_SIZE[1],
        Qt.KeepAspectRatio, Qt.SmoothTransformation,
    )


def _caption_value(text):
    val = QLabel(text)
    val.setProperty("class", "receipt-meta-value")
    return val


def receipt_status_row(flayout, total, paid, balance):
    """The on-screen card's payment strip (status colour + paid/balance)."""
    # A zero-total receipt owes nothing, so it reads as Paid (0 of 0).
    if total <= 0.004 or paid >= total - 0.004:
        status = "Paid"
    elif paid > 0.004:
        status = "Partial"
    else:
        status = "Unpaid"
    # Palette keys, not raw hex: the strip must follow light/dark themes.
    palette = get_active_palette()
    colors = {
        "Paid": palette.qcolor("state_success"),
        "Partial": palette.qcolor("state_warning"),
        "Unpaid": palette.qcolor("state_danger"),
    }
    status_label = QLabel(tr(status))
    status_label.setProperty("class", "receipt-meta-caption")
    status_label.setStyleSheet(
        "color: %s; font-weight: bold;" % colors[status].name()
    )
    status_label.setAlignment(Qt.AlignCenter)
    flayout.addWidget(status_label)

    paid_label = QLabel(
        (tr("Paid: {amount}   |   Credit: {credit}") if balance < -0.004
         else tr("Paid: {amount}   |   Balance: {balance}")).format(
            amount=format_currency(paid),
            credit=format_currency(-balance),
            balance=format_currency(balance),
        )
    )
    paid_label.setProperty("class", "receipt-meta-value")
    paid_label.setAlignment(Qt.AlignCenter)
    flayout.addWidget(paid_label)


class ReceiptCard(NamedTuple):
    """The built card plus the widgets a caller may keep reading."""
    frame: QFrame
    logo: QLabel
    clinic: QLabel
    title: QLabel
    date: QLabel
    owner: QLabel
    pet: QLabel
    phone: QLabel
    table: QTableWidget
    subtotal: QLabel
    discount: QLabel
    total: QLabel
    footer: QLabel


def build_receipt_card(header, items, discount, total, *, receipt_id=None,
                       paid=0.0, balance=0.0, client=False):
    """Builds the receipt card and returns it as a :class:`ReceiptCard`.

    ``header`` carries ``receipt_date`` / ``receipt_kind`` / ``receipt_code`` /
    ``owner_name`` / ``pet_name`` / ``owner_phone`` / ``notes``; ``items`` are
    dicts with name, quantity and unit_price - the shape
    ``sales_repo.get_receipt_line_items`` returns.

    ``client=True`` builds the client copy: payment details left out and a
    thank-you footer, exactly what Print for Client prints. The receipt number
    line only appears when ``receipt_id`` (or a code) is given - a pre-save
    wizard preview has no number yet.
    """
    frame = QFrame()
    frame.setProperty("class", "receipt")
    frame.setFixedWidth(RECEIPT_CARD_WIDTH)
    flayout = QVBoxLayout(frame)
    flayout.setContentsMargins(22, 16, 22, 16)
    flayout.setSpacing(4)

    logo = None
    logo_pixmap = _clinic_logo_pixmap()
    if not logo_pixmap.isNull():
        logo = QLabel()
        logo.setProperty("class", "receipt-logo")
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(logo_pixmap)
        flayout.addWidget(logo)

    clinic = QLabel(str(SettingsManager.get("clinic_name", DEFAULT_CLINIC_NAME)))
    clinic.setProperty("class", "receipt-clinic")
    clinic.setAlignment(Qt.AlignCenter)
    flayout.addWidget(clinic)

    title = QLabel(tr("RECEIPT"))
    title.setProperty("class", "receipt-title")
    title.setAlignment(Qt.AlignCenter)
    flayout.addWidget(title)

    if receipt_id is not None or header.get("receipt_code"):
        code = str(header.get("receipt_code") or "").strip()
        if code and receipt_id is not None:
            no_text = f"{code} #{receipt_id}"
        elif code:
            no_text = code
        else:
            no_text = f"#{receipt_id}"
        no_label = QLabel(no_text)
        no_label.setProperty("class", "receipt-meta-caption")
        no_label.setAlignment(Qt.AlignCenter)
        flayout.addWidget(no_label)

    meta = QFormLayout()
    meta.setContentsMargins(0, 6, 0, 6)
    meta.setSpacing(4)

    date_val = _caption_value(str(header.get("receipt_date") or ""))
    meta.addRow(_caption(tr("Date:")), date_val)
    meta.addRow(_caption(tr("Type:")),
                _caption_value(receipt_kind_label(header.get("receipt_kind"),
                                                  header.get("receipt_code"))))

    owner_val = _caption_value(str(header.get("owner_name") or ""))
    pet_val = _caption_value(str(header.get("pet_name") or ""))
    phone_val = _caption_value(str(header.get("owner_phone") or ""))
    notes_val = _caption_value(str(header.get("notes") or ""))
    if header.get("owner_name"):
        meta.addRow(_caption(tr("Owner:")), owner_val)
    if header.get("pet_name"):
        meta.addRow(_caption(tr("Pet:")), pet_val)
    if header.get("owner_phone"):
        meta.addRow(_caption(tr("Phone:")), phone_val)
    if header.get("notes"):
        meta.addRow(_caption(tr("Notes:")), notes_val)
    flayout.addLayout(meta)

    table = QTableWidget(0, 4)
    table.setObjectName("receiptItems")
    table.setHorizontalHeaderLabels([tr("Item"), tr("Qty"), tr("Price"), tr("Total")])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.setFocusPolicy(Qt.ClickFocus)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    table.setColumnWidth(1, 46)
    table.setColumnWidth(2, 74)
    table.setColumnWidth(3, 84)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    flayout.addWidget(table)

    subtotal = 0.0
    for row, it in enumerate(items):
        line_total = float(it.get("unit_price") or 0) * float(it.get("quantity") or 0)
        subtotal += line_total
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(it.get("name") or "")))
        table.setItem(row, 1, QTableWidgetItem(str(it.get("quantity") or "")))
        table.setItem(row, 2, QTableWidgetItem(format_currency(it.get("unit_price") or 0)))
        table.setItem(row, 3, QTableWidgetItem(format_currency(line_total)))
    fit_receipt_items_table(table)

    subtotal_val = _caption_value(format_currency(subtotal))
    discount_val = _caption_value(format_currency(discount))
    total_val = _caption_value(format_currency(total))
    totals = QFormLayout()
    totals.setSpacing(4)
    totals.addRow(_caption(tr("Subtotal:")), subtotal_val)
    if float(discount) > 0.004:
        # The row (and its minus sign) only exists when there is a discount -
        # the real receipt has never printed a $0.00 discount line.
        discount_val.setText("-" + format_currency(discount))
        totals.addRow(_caption(tr("Discount:")), discount_val)
    totals.addRow(_caption(tr("Total:")), total_val)
    flayout.addLayout(totals)

    footer = None
    if client:
        footer = QLabel(tr("Thank you for visiting us."))
        footer.setProperty("class", "receipt-footer")
        footer.setAlignment(Qt.AlignCenter)
        flayout.addWidget(footer)
    else:
        receipt_status_row(flayout, float(total), float(paid), float(balance))

    # When a caller stretches the card (the wizard's billing step does, so the
    # billing bar lands on the page's bottom edge), the spare height must pool
    # below the receipt content - not stretch the pinned items table and not
    # spread the meta rows apart.
    flayout.addStretch(1)

    return ReceiptCard(
        frame=frame, logo=logo, clinic=clinic, title=title, date=date_val,
        owner=owner_val, pet=pet_val, phone=phone_val, table=table,
        subtotal=subtotal_val, discount=discount_val, total=total_val,
        footer=footer,
    )
