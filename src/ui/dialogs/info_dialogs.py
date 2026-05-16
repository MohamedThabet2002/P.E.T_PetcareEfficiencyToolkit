"""
Read-only detail dialogs for owners and pets.

Opened when the user clicks a name link in a data table. The owner dialog is a
card-based summary (Owner Info / Visits / Pets / Next Appointments / Notes /
Finances); the pet dialog is a card-based summary (Pet Info / Visits / Owner
Info / Next Appointments / Notes / Health State / Vaccinations / Medications).
Both offer an in-dialog Edit mode for their own fields (name, phone, notes /
pet fields, notes) and route non-editor edits through the pending-changes
workflow. Visits open the card-based Visit Details dialog, which offers an
in-dialog Edit mode (visit info incl. doctor, clinical sections, follow-ups,
supplies + discount) plus one-click Settle Payment and an Adjust action that
opens the receipt adjustment dialog.
"""

from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QDialogButtonBox,
    QPushButton,
    QScrollArea,
    QWidget,
    QLineEdit,
    QTextEdit,
    QFrame,
    QProgressBar,
    QMessageBox,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCompleter,
    QListView,
    QCheckBox,
    QDateTimeEdit,
)
from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtGui import QIcon, QTextOption

from src.core.permissions import can
from src.utils.formatters import format_age, format_currency
from src.utils.i18n import tr
from src.ui.themes.color_palettes import get_active_palette, get_contrast_color, hex_to_rgba
from src.ui.dialogs.base_clinical_dialog import ClinicalSectionsMixin, SupplyReceiptMixin

GENDER_OPTIONS = ["Female", "Male", "Other"]

DATE_TIME_FORMAT = "yyyy-MM-dd HH:mm"


class InfoDialogMixin:
    """Shared helpers for the card-based info dialogs (Owner / Pet)."""

    def _add_close_button(self, layout):
        buttons = QDialogButtonBox()
        buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Card layout helpers (shared by OwnerInfoDialog and PetInfoDialog)
    # ------------------------------------------------------------------
    def _make_card(self, title_text):
        """Creates an info-card frame with a title and returns (card, body_layout)."""
        card = QFrame()
        card.setProperty("class", "info-card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 8, 12, 12)
        outer.setSpacing(8)
        title = QLabel(title_text)
        title.setProperty("class", "info-card-title")
        outer.addWidget(title)
        body = QVBoxLayout()
        body.setContentsMargins(4, 0, 4, 0)
        body.setSpacing(8)
        outer.addLayout(body)
        return card, body

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            sub_layout = item.layout()
            if sub_layout is not None:
                self._clear_layout(sub_layout)

    def _detail_row(self, label, value):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = QLabel(label)
        lab.setProperty("class", "muted-label")
        val = QLabel(value if value not in (None, "") else tr("N/A"))
        val.setWordWrap(True)
        val.setProperty("class", "muted-label")
        h.addWidget(lab)
        h.addStretch()
        h.addWidget(val)
        return row

    def _kpi_stat(self, title, value):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        t = QLabel(title)
        t.setProperty("class", "caption-label")
        v = QLabel(value)
        v.setProperty("class", "value-strong")
        col.addWidget(t)
        col.addWidget(v)
        return w

    def _history_row(self, text, on_click=None):
        btn = QPushButton(text)
        btn.setProperty("class", "history-item")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(str(text))
        if on_click is not None:
            btn.clicked.connect(on_click)
        return btn

    def _badge(self, text, color):
        lbl = QLabel(str(text))
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 8px;"
            "padding: 2px 8px; font-size: 8pt; font-weight: bold;"
            % (hex_to_rgba(color, 0.18), color)
        )
        return lbl

    def _empty_label(self, text):
        lbl = QLabel(text)
        lbl.setProperty("class", "empty-label")
        lbl.setWordWrap(True)
        return lbl

    def _initials(self, name):
        words = [w for w in str(name or "").split() if w]
        initials = "".join(w[0].upper() for w in words[:2])
        return initials or "?"

    @staticmethod
    def _clip(text, limit=48):
        text = str(text or "")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    # ------------------------------------------------------------------
    # Footer & edit mode
    # ------------------------------------------------------------------
    def _build_footer(self):
        footer = QHBoxLayout()
        self._btn_edit = QPushButton(tr("Edit"))
        self._btn_close = QPushButton(tr("Close"))
        self._btn_save = QPushButton(tr("Save"))
        self._btn_cancel = QPushButton(tr("Cancel"))
        self._btn_edit.clicked.connect(lambda: self._toggle_edit(True))
        self._btn_cancel.clicked.connect(lambda: self._toggle_edit(False))
        self._btn_save.clicked.connect(self._save)
        self._btn_close.clicked.connect(self.accept)
        footer.addStretch()
        for button in (self._btn_edit, self._btn_save, self._btn_cancel, self._btn_close):
            footer.addWidget(button)
        return footer

    def _set_edit_buttons(self, editing):
        self._btn_edit.setVisible(not editing and self._can_edit())
        self._btn_close.setVisible(not editing)
        self._btn_save.setVisible(editing)
        self._btn_cancel.setVisible(editing)

    def _can_edit(self):
        return bool(getattr(self, "_current_user", None)) and (
            can(self._current_user, "edit_records")
            or can(self._current_user, "request_change")
        )

    def _can_write(self):
        return bool(getattr(self, "_current_user", None)) and can(self._current_user, "edit_records")

    def _notify_parent_changed(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "data_changed"):
            try:
                parent.data_changed.emit()
            except Exception:
                pass


class OwnerInfoDialog(InfoDialogMixin, QDialog):
    """Card-based owner summary with optional in-dialog editing.

    Layout (2-column card grid):
        Row 1: Owner Info | Visits
        Row 2: Pets       | Next Appointments
        Row 3: Notes      | Finances (Total Paid + Outstanding, connected)

    Edit mode (when the current user may edit or request changes) turns the
    Owner Info and Notes cards into editable fields; a non-editor submits the
    change for admin approval through the pending-changes workflow.
    """

    def __init__(self, data, parent=None, current_user=None):
        super().__init__(parent)
        self._current_user = current_user
        self._editing = False

        self.client_id = data.get("client_id") or data.get("owner_id")
        self._owner_name = data.get("owner_name") or tr("Owner")
        self._phone = data.get("phone_number") or ""
        self._notes = ""
        self._member_since = ""
        self._pets = data.get("pets") or []
        self._visits = []
        self._appointments = []
        self._finance = {}
        self._loyalty = {}

        palette = get_active_palette()
        self._secondary = palette.get("text_secondary", "#636E72")
        self._border = palette.get("border", "#DCDDE1")
        self._success = palette.get("state_success", "#2ECC71")
        self._danger = palette.get("state_danger", "#E74C3C")
        self._warning = palette.get("state_warning", "#F39C12")
        self._info = palette.get("state_info", "#3498DB")
        self._brand = palette.get("brand_500", "#4A90E2")

        self.setWindowTitle(tr("Owner Details"))
        self.setWindowIcon(QIcon())
        # Plain QWidget containers (detail rows, KPI blocks, etc.) should not
        # paint their default (gray) background over the card/dialog surface.
        self.setStyleSheet(".QWidget { background: transparent; }")
        self.setMinimumSize(880, 620)

        self._load_data()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        self._build_cards()
        root.addLayout(self._build_footer())
        self._toggle_edit(False)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _load_data(self):
        if self.client_id:
            from src.core.repositories import client_repo
            details = client_repo.get_owner_details(self.client_id)
            if details:
                self._owner_name = details.get("owner_name") or self._owner_name
                self._phone = details.get("phone_number") or ""
                self._notes = details.get("notes") or ""
                self._member_since = str(details.get("created_at") or "")[:10]

        if self.client_id:
            from src.core.repositories import appointment_repo, pet_repo, sales_repo, visit_repo
            self._pets = pet_repo.get_pets_for_client(self.client_id)
            self._visits = visit_repo.get_recent_visits_for_client(self.client_id, 4)
            self._finance = sales_repo.get_owner_financial_summary(self.client_id)
            try:
                from src.core.repositories.client_loyalty_repo import get_client_loyalty_stats
                self._loyalty = get_client_loyalty_stats(self.client_id)
            except Exception:
                self._loyalty = {}
            try:
                owner_id = int(self.client_id)
                rows = [
                    r for r in appointment_repo.get_appointments()
                    if r.get("client_id") is not None
                    and int(r.get("client_id")) == owner_id
                    and r.get("status") in ("Pending", "Late")
                ]
                rows.sort(key=lambda r: (
                    0 if r.get("status") == "Pending" else 1,
                    r.get("appointment_date") or "",
                ))
                self._appointments = rows[:5]
            except (TypeError, ValueError):
                self._appointments = []

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------
    def _build_cards(self):
        owner_card, self._owner_body = self._make_card(tr("Owner Info"))
        visits_card, self._visits_body = self._make_card(tr("Visits"))
        pets_card, self._pets_body = self._make_card(tr("Pets"))
        appt_card, self._appointments_body = self._make_card(tr("Next Appointments"))
        notes_card, self._notes_body = self._make_card(tr("Notes"))
        fin_card, self._finances_body = self._make_card(tr("Finances"))

        self._grid.addWidget(owner_card, 0, 0)
        self._grid.addWidget(visits_card, 0, 1)
        self._grid.addWidget(pets_card, 1, 0)
        self._grid.addWidget(appt_card, 1, 1)
        self._grid.addWidget(notes_card, 2, 0)
        self._grid.addWidget(fin_card, 2, 1)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)

        self._render_owner_card()
        self._render_visits_card()
        self._render_pets_card()
        self._render_appointments_card()
        self._render_notes_card()
        self._render_finances_card()

    def _render_owner_card(self):
        self._clear_layout(self._owner_body)

        header = QHBoxLayout()
        header.setSpacing(10)
        avatar = QLabel(self._initials(self._owner_name))
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 23px;"
            "font-size: 11pt; font-weight: bold;"
            % (self._brand, get_contrast_color(self._brand))
        )
        header.addWidget(avatar)

        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        name_label = QLabel(self._owner_name)
        name_label.setProperty("class", "avatar-name")
        name_col.addWidget(name_label)
        member = QLabel(
            "%s: %s" % (tr("Member Since"), self._member_since or tr("N/A"))
        )
        member.setProperty("class", "caption-label")
        name_col.addWidget(member)
        header.addLayout(name_col, 1)
        self._owner_body.addLayout(header)

        if self._editing:
            self._name_edit = QLineEdit(self._owner_name)
            self._phone_edit = QLineEdit(self._phone)
            self._owner_body.addWidget(QLabel("%s:" % tr("Owner Name")))
            self._owner_body.addWidget(self._name_edit)
            self._owner_body.addWidget(QLabel("%s:" % tr("Phone Number")))
            self._owner_body.addWidget(self._phone_edit)
        else:
            self._owner_body.addWidget(self._detail_row(tr("Owner ID:"), str(self.client_id or "")))
            self._owner_body.addWidget(self._detail_row(tr("Phone Number:"), self._phone))

    def _render_visits_card(self):
        self._clear_layout(self._visits_body)
        loyalty = self._loyalty or {}
        avg = "$ {:,.2f}".format(float(loyalty.get("avg_spend", 0.0)))
        last = loyalty.get("last_visit_date")
        kpi = QHBoxLayout()
        kpi.setSpacing(10)
        kpi.addWidget(self._kpi_stat(tr("Total Visits"), str(loyalty.get("visit_count", 0))))
        kpi.addWidget(self._kpi_stat(tr("Avg per Visit"), avg))
        kpi.addWidget(self._kpi_stat(tr("Last Visit"), str(last)[:10] if last else tr("N/A")))
        self._visits_body.addLayout(kpi)

        for visit in self._visits:
            date = str(visit.get("visit_date") or "")[:10]
            line = "{date} · {pet} — {diag}".format(
                date=date,
                pet=visit.get("pet_name") or "?",
                diag=self._clip(visit.get("diagnosis") or "", 30),
            )
            self._visits_body.addWidget(
                self._history_row(line, lambda *_, v=visit: self._open_visit(v))
            )
        if not self._visits:
            self._visits_body.addWidget(self._empty_label(tr("No visits recorded")))

    def _render_pets_card(self):
        self._clear_layout(self._pets_body)
        count_label = QLabel("%s (%d)" % (tr("Pets"), len(self._pets)))
        count_label.setProperty("class", "section-heading")
        self._pets_body.addWidget(count_label)

        for pet in self._pets:
            name = pet.get("pet_name") or "?"
            species = pet.get("species") or ""
            age = format_age(pet.get("age_months"))
            parts = [name]
            if species:
                parts.append(species)
            if age:
                parts.append(age)
            self._pets_body.addWidget(
                self._history_row(self._clip(" · ".join(parts)), lambda *_, p=pet: self._open_pet(p))
            )
        if not self._pets:
            self._pets_body.addWidget(self._empty_label(tr("No pets recorded")))

    def _render_appointments_card(self):
        self._clear_layout(self._appointments_body)
        status_colors = {
            "Pending": self._info,
            "Late": self._warning,
            "Completed": self._success,
            "Canceled": self._secondary,
        }
        for appointment in self._appointments:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            date = str(appointment.get("appointment_date") or "")[:16]
            line = "{date} · {pet} · {service}".format(
                date=date,
                pet=appointment.get("pet_name") or "?",
                service=self._clip(appointment.get("service") or "", 22),
            )
            h.addWidget(
                self._history_row(
                    line,
                    lambda *_, a=appointment: self._open_appointment(a),
                ),
                1,
            )
            status = appointment.get("status") or "Pending"
            h.addWidget(self._badge(status, status_colors.get(status, self._info)))
            self._appointments_body.addWidget(row)
        if not self._appointments:
            self._appointments_body.addWidget(self._empty_label(tr("No upcoming appointments")))

    def _render_notes_card(self):
        self._clear_layout(self._notes_body)
        if self._editing:
            self._notes_edit = QTextEdit()
            self._notes_edit.setPlainText(self._notes)
            self._notes_edit.setPlaceholderText(tr("Add notes..."))
            self._notes_edit.setWordWrapMode(QTextOption.WordWrap)
            self._notes_edit.setFixedHeight(120)
            self._notes_body.addWidget(self._notes_edit)
        else:
            if self._notes and self._notes.strip():
                label = QLabel(self._notes)
                label.setWordWrap(True)
                self._notes_body.addWidget(label)
            else:
                self._notes_body.addWidget(self._empty_label(tr("No notes yet")))

    def _render_finances_card(self):
        self._clear_layout(self._finances_body)
        finance = self._finance or {}
        billed = float(finance.get("total_billed", 0.0))
        paid = float(finance.get("total_paid", 0.0))
        outstanding = float(finance.get("outstanding", 0.0))
        open_receipts = int(finance.get("open_receipts", 0))

        billed_label = QLabel(
            "%s: $ %s" % (tr("Total Billed"), "{:,.2f}".format(billed))
        )
        billed_label.setProperty("class", "muted-label")
        self._finances_body.addWidget(billed_label)

        amounts = QWidget()
        ah = QHBoxLayout(amounts)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(8)
        ah.addWidget(self._money_block(tr("Total Paid"), paid, self._success), 1)
        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setStyleSheet("color: %s;" % self._border)
        ah.addWidget(separator)
        ah.addWidget(self._money_block(tr("Outstanding"), outstanding, self._danger), 1)
        self._finances_body.addWidget(amounts)

        ratio = (paid / billed * 100.0) if billed > 0 else 100.0
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(round(min(ratio, 100.0))))
        bar.setTextVisible(False)
        bar.setFixedHeight(12)
        bar.setStyleSheet(
            "QProgressBar{background-color: %s; border: none; border-radius: 6px;}"
            "QProgressBar::chunk{background-color: %s; border-radius: 6px;}"
            % (hex_to_rgba(self._danger, 0.25), self._success)
        )
        self._finances_body.addWidget(bar)

        if not finance.get("receipt_count"):
            self._finances_body.addWidget(self._empty_label(tr("No receipts yet")))
        elif open_receipts == 0:
            self._finances_body.addWidget(self._empty_label(tr("All receipts settled")))
        else:
            self._finances_body.addWidget(
                self._empty_label("%s: %d" % (tr("Open Receipts"), open_receipts))
            )
            if self._editing and self._can_write():
                self._btn_settle = QPushButton(tr("Settle Outstanding"))
                self._btn_settle.setCursor(Qt.PointingHandCursor)
                self._btn_settle.clicked.connect(self._settle_all)
                self._finances_body.addWidget(self._btn_settle)

    def _money_block(self, title, amount, color):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        t = QLabel(title)
        t.setProperty("class", "caption-label")
        v = QLabel("$ %s" % "{:,.2f}".format(float(amount)))
        v.setAlignment(Qt.AlignHCenter)
        v.setStyleSheet("color: %s; font-size: 15pt; font-weight: bold;" % color)
        col.addWidget(t)
        col.addWidget(v)
        return w

    # ------------------------------------------------------------------
    # Footer & edit mode
    # ------------------------------------------------------------------
    def _toggle_edit(self, editing):
        self._editing = editing
        self._set_edit_buttons(editing)
        self._render_owner_card()
        self._render_notes_card()
        self._render_finances_card()

    def _save(self):
        name = self._name_edit.text().strip().title() if hasattr(self, "_name_edit") else self._owner_name
        phone = self._phone_edit.text().strip() if hasattr(self, "_phone_edit") else self._phone
        notes = self._notes_edit.toPlainText().strip() if hasattr(self, "_notes_edit") else self._notes

        if not name:
            QMessageBox.warning(self, tr("Input Error"), tr("Owner name is required."))
            return

        from src.core.repositories import client_repo, pending_changes_repo

        if can(self._current_user, "edit_records"):
            if client_repo.update_client(
                self.client_id, name, phone, notes=notes,
                audit_user_id=(self._current_user or {}).get("user_id"),
            ):
                self._owner_name, self._phone, self._notes = name, phone, notes
                self._toggle_edit(False)
                self._notify_parent_changed()
            else:
                QMessageBox.critical(self, tr("Database Error"), tr("Could not update client."))
        else:
            user_id = (self._current_user or {}).get("user_id")
            pid = pending_changes_repo.submit_change(
                user_id, "owners", self.client_id, "UPDATE",
                {"owner_name": name, "phone_number": phone, "notes": notes},
            )
            if pid:
                QMessageBox.information(
                    self,
                    tr("Submitted"),
                    tr("Your change has been submitted for admin approval."),
                )
                self.accept()
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to submit change request."))

    def _open_visit(self, visit):
        data = {
            "visit_id": visit.get("visit_id"),
            "visit_date": visit.get("visit_date") or "",
            "owner_name": getattr(self, "_owner_name", "") or "",
            "pet_name": visit.get("pet_name") or "",
            "diagnosis": visit.get("diagnosis") or "",
            "notes": visit.get("notes") or "",
            "consult": visit.get("is_consult", 0),
            "owner_id": getattr(self, "client_id", None),
        }
        self._close_and_open(
            lambda parent: VisitInfoDialog(data, parent, current_user=self._current_user)
        )

    def _open_pet(self, pet):
        self._close_and_open(lambda parent: PetInfoDialog(pet, parent, current_user=self._current_user))

    def _open_appointment(self, appointment):
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog
        self._close_and_open(
            lambda parent: AppointmentsDialog(current_user=self._current_user, parent=parent)
        )

    def _close_and_open(self, factory):
        """Closes this dialog, then opens the target dialog on the parent page."""
        parent = self.parent()
        self.accept()
        dialog = factory(parent if parent is not None else self)
        dialog.exec_()
        self._notify_parent_changed()

    def _settle_all(self):
        from src.core.repositories import payment_repo, sales_repo
        answer = QMessageBox.question(
            self,
            tr("Settle Outstanding"),
            tr("Settle all outstanding receipts?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            for receipt_id, amount in sales_repo.get_open_receipt_balances_for_owner(self.client_id):
                if amount > 0:
                    payment_repo.add_payment(
                        receipt_id, amount, "Cash", tr("Settled from owner details"),
                        audit_user_id=(self._current_user or {}).get("user_id"),
                    )
        except Exception:
            QMessageBox.critical(self, tr("Database Error"), tr("Could not settle receipts."))
            return
        self._finance = sales_repo.get_owner_financial_summary(self.client_id)
        self._render_finances_card()
        self._notify_parent_changed()
        QMessageBox.information(
            self, tr("Settle Outstanding"), tr("All outstanding receipts settled.")
        )


class SupplyInfoDialog(InfoDialogMixin, QDialog):
    """Read-only item details for a single inventory item.

    Opened by clicking a batch number in the Stock Batches dialog. When the data
    carries a `batch_id` the dialog describes *that batch* (its own quantity,
    purchase/expiry dates, buy price, supplier and notes); otherwise it describes
    the item as a whole. Editing lives elsewhere: item name / category /
    sub-category / sell price on the supplies page, and the batch's dates and
    buy price in the Stock Batches dialog.
    """

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data = dict(data or {})
        is_batch = self._data.get("batch_id") is not None

        self.setWindowTitle(tr("Batch Details") if is_batch else tr("Item Details"))
        self.setWindowIcon(QIcon())
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        title = QLabel(self._data.get("item_name") or tr("Item"))
        title.setProperty("class", "dialog-title")
        layout.addWidget(title)

        buy_price = self._data.get("buy_price") or 0
        sell_price = self._data.get("sell_price") or 0
        # A batch view shows the batch quantity next to the item's total stock.
        batch_qty = self._data.get("batch_quantity") if is_batch else None
        qty = batch_qty if batch_qty is not None else (self._data.get("current_stock") or 0)

        form = QFormLayout()
        if is_batch:
            form.addRow(tr("Batch ID:"), QLabel(str(self._data.get("batch_id") or "")))
        form.addRow(tr("Item ID:"), QLabel(str(self._data.get("supply_id") or "")))
        form.addRow(tr("Item Name:"), QLabel(str(self._data.get("item_name") or "")))
        form.addRow(tr("Category:"), QLabel(str(self._data.get("category") or "")))
        form.addRow(tr("Sub-Category:"), QLabel(str(self._data.get("sub_category") or "")))
        if batch_qty is not None:
            form.addRow(tr("Batch Quantity:"), QLabel(str(batch_qty)))
            form.addRow(tr("In Stock:"), QLabel(str(self._data.get("current_stock") or "")))
        else:
            form.addRow(tr("Quantity:"), QLabel(str(self._data.get("current_stock") or "")))
        form.addRow(tr("Purchase Date:"), QLabel(str(self._data.get("purchase_date") or "")))
        form.addRow(tr("Expiry Date:"), QLabel(str(self._data.get("expiry_date") or "")))
        form.addRow(
            tr("Buy Price:"),
            QLabel("$ {price:,.2f}".format(price=float(buy_price))),
        )
        form.addRow(
            tr("Sell Price:"),
            QLabel("$ {price:,.2f}".format(price=float(sell_price))),
        )
        form.addRow(
            tr("Batch Value:") if batch_qty is not None else tr("Stock Value:"),
            QLabel("$ {price:,.2f}".format(price=float(qty) * float(buy_price))),
        )
        form.addRow(tr("Supplier:"), QLabel(str(self._data.get("supplier") or "")))
        if is_batch:
            form.addRow(tr("Notes:"), QLabel(str(self._data.get("notes") or "")))
        layout.addLayout(form)

        self._add_close_button(layout)


class PetInfoDialog(InfoDialogMixin, QDialog):
    """Card-based pet summary with optional in-dialog editing.

    Layout (2-column card grid):
        Row 1: Pet Info | Visits (pet only)
        Row 2: Owner Info | Next Appointments (pet only)
        Row 3: Notes | Health State (latest clinical stats)
        Row 4: Vaccinations | Medications

    Edit mode (when the current user may edit or request changes) turns the
    Pet Info and Notes cards into editable fields; a non-editor submits the
    change for admin approval through the pending-changes workflow.
    """

    def __init__(self, data, parent=None, current_user=None):
        super().__init__(parent)
        self._current_user = current_user
        self._editing = False

        self._pet_id = data.get("pet_id")
        self._pet_name = data.get("pet_name") or tr("Pet")
        self._species = data.get("species") or ""
        self._breed = data.get("breed") or ""
        self._gender = data.get("gender") or ""
        self._age_months = data.get("age_months") or 0
        self._weight = data.get("weight") or 0
        self._client_id = data.get("client_id")
        self._owner_name = data.get("owner_name") or ""
        self._owner_phone = ""
        self._owner_created_at = ""
        self._notes = ""

        self._visits = []
        self._stats = {}
        self._appointments = []
        self._health_status = data.get("health_status") or ""
        self._exam = None
        self._derived_health = "Unknown"

        palette = get_active_palette()
        self._secondary = palette.get("text_secondary", "#636E72")
        self._border = palette.get("border", "#DCDDE1")
        self._success = palette.get("state_success", "#2ECC71")
        self._danger = palette.get("state_danger", "#E74C3C")
        self._warning = palette.get("state_warning", "#F39C12")
        self._info = palette.get("state_info", "#3498DB")
        self._brand = palette.get("brand_500", "#4A90E2")

        self.setWindowTitle(tr("Pet Details"))
        self.setWindowIcon(QIcon())
        self.setStyleSheet(".QWidget { background: transparent; }")
        self.setMinimumSize(880, 620)

        self._load_data()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        self._build_cards()
        root.addLayout(self._build_footer())
        self._toggle_edit(False)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _load_data(self):
        if self._pet_id:
            from src.core.repositories import pet_repo
            details = pet_repo.get_pet_details(self._pet_id)
            if details:
                self._pet_name = details.get("pet_name") or self._pet_name
                self._species = details.get("species") or ""
                self._breed = details.get("breed") or ""
                self._gender = details.get("gender") or ""
                self._age_months = details.get("age_months") or 0
                self._weight = details.get("weight") or 0
                self._client_id = details.get("client_id")
                self._owner_name = details.get("owner_name") or ""
                self._owner_phone = details.get("owner_phone") or ""
                self._owner_created_at = str(details.get("owner_created_at") or "")[:10]
                self._notes = details.get("notes") or ""
                self._health_status = details.get("health_status") or ""

        if self._pet_id:
            from src.core.repositories import appointment_repo, visit_repo
            from src.core.repositories import clinical_exam_repo
            from src.core.health_status import derive_health_status

            self._visits = visit_repo.get_recent_visits_for_pet(self._pet_id, 4)
            self._stats = visit_repo.get_visit_stats_for_pet(self._pet_id)
            try:
                rows = [
                    r for r in appointment_repo.get_appointments()
                    if r.get("pet_id") is not None
                    and int(r.get("pet_id")) == int(self._pet_id)
                    and r.get("status") in ("Pending", "Late")
                ]
                rows.sort(key=lambda r: (
                    0 if r.get("status") == "Pending" else 1,
                    r.get("appointment_date") or "",
                ))
                self._appointments = rows[:5]
            except (TypeError, ValueError):
                self._appointments = []
            try:
                latest_visit_id = self._visits[0].get("visit_id") if self._visits else None
                self._exam = clinical_exam_repo.get_clinical_exam(latest_visit_id)
                self._derived_health = derive_health_status(self._exam)
            except Exception:
                self._exam = None
                self._derived_health = "Unknown"

    # ------------------------------------------------------------------
    # Card builders
    # ------------------------------------------------------------------
    def _build_cards(self):
        pet_card, self._pet_body = self._make_card(tr("Pet Info"))
        visits_card, self._visits_body = self._make_card(tr("Visits"))
        owner_card, self._owner_body = self._make_card(tr("Owner Info"))
        appt_card, self._appointments_body = self._make_card(tr("Next Appointments"))
        notes_card, self._notes_body = self._make_card(tr("Notes"))
        health_card, self._health_body = self._make_card(tr("Health"))

        self._grid.addWidget(pet_card, 0, 0)
        self._grid.addWidget(visits_card, 0, 1)
        self._grid.addWidget(owner_card, 1, 0)
        self._grid.addWidget(appt_card, 1, 1)
        self._grid.addWidget(notes_card, 2, 0)
        self._grid.addWidget(health_card, 2, 1)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)

        self._render_pet_card()
        self._render_visits_card()
        self._render_owner_card()
        self._render_appointments_card()
        self._render_notes_card()
        self._render_health_card()

    def _render_pet_card(self):
        self._clear_layout(self._pet_body)

        header = QHBoxLayout()
        header.setSpacing(10)
        avatar = QLabel(self._initials(self._pet_name))
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 23px;"
            "font-size: 11pt; font-weight: bold;"
            % (self._brand, get_contrast_color(self._brand))
        )
        header.addWidget(avatar)

        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        name_label = QLabel(self._pet_name)
        name_label.setProperty("class", "avatar-name")
        name_col.addWidget(name_label)
        sub = QLabel(
            "%s · %s · %s" % (
                self._species or tr("N/A"),
                self._breed or tr("N/A"),
                format_age(self._age_months),
            )
        )
        sub.setProperty("class", "caption-label")
        name_col.addWidget(sub)
        name_col.addStretch()
        header.addLayout(name_col, 1)
        self._pet_body.addLayout(header)

        if self._editing:
            self._name_edit = QLineEdit(self._pet_name)

            from src.core.repositories import supply_repo
            species_items = supply_repo.get_all_species()
            if self._species and self._species not in species_items:
                species_items.insert(0, self._species)
            self._species_edit = QComboBox()
            self._species_edit.setView(QListView())
            self._species_edit.addItems(species_items)
            self._species_edit.setCurrentText(self._species)

            self._breed_edit = QLineEdit(self._breed)
            from src.core.repositories import pet_repo as _pet_repo
            breed_completer = QCompleter(_pet_repo.get_unique_breeds())
            breed_completer.setCaseSensitivity(Qt.CaseInsensitive)
            self._breed_edit.setCompleter(breed_completer)

            self._gender_edit = QComboBox()
            self._gender_edit.setView(QListView())
            self._gender_edit.addItems(GENDER_OPTIONS)
            self._gender_edit.setCurrentText(self._gender)

            self._age_edit = QSpinBox()
            self._age_edit.setMaximum(600)
            self._age_edit.setValue(int(self._age_months or 0))

            from src.core.repositories import client_repo
            self._owner_edit = QComboBox()
            self._owner_edit.setView(QListView())
            for c in client_repo.get_clients():
                self._owner_edit.addItem(c["owner_name"], c["client_id"])
                if c["client_id"] == self._client_id:
                    self._owner_edit.setCurrentIndex(self._owner_edit.count() - 1)

            self._pet_body.addWidget(QLabel("%s:" % tr("Pet Name*:")))
            self._pet_body.addWidget(self._name_edit)
            self._pet_body.addWidget(QLabel("%s:" % tr("Species:")))
            self._pet_body.addWidget(self._species_edit)
            self._pet_body.addWidget(QLabel("%s:" % tr("Breed:")))
            self._pet_body.addWidget(self._breed_edit)
            self._pet_body.addWidget(QLabel("%s:" % tr("Gender:")))
            self._pet_body.addWidget(self._gender_edit)
            self._pet_body.addWidget(QLabel("%s:" % tr("Age (Months):")))
            self._pet_body.addWidget(self._age_edit)
            self._pet_body.addWidget(QLabel("%s:" % tr("Owner:")))
            self._pet_body.addWidget(self._owner_edit)
        else:
            self._pet_body.addWidget(self._detail_row(tr("Pet ID:"), str(self._pet_id or "")))
            self._pet_body.addWidget(self._detail_row(tr("Species:"), self._species))
            self._pet_body.addWidget(self._detail_row(tr("Breed:"), self._breed))
            self._pet_body.addWidget(self._detail_row(tr("Gender:"), self._gender))
            self._pet_body.addWidget(self._detail_row(tr("Age:"), format_age(self._age_months)))

    def _render_visits_card(self):
        self._clear_layout(self._visits_body)
        stats = self._stats or {}
        avg = "$ {:,.2f}".format(float(stats.get("avg_spend", 0.0)))
        last = stats.get("last_visit_date")
        kpi = QHBoxLayout()
        kpi.setSpacing(10)
        kpi.addWidget(self._kpi_stat(tr("Total Visits"), str(stats.get("visit_count", 0))))
        kpi.addWidget(self._kpi_stat(tr("Avg per Visit"), avg))
        kpi.addWidget(self._kpi_stat(tr("Last Visit"), str(last)[:10] if last else tr("N/A")))
        self._visits_body.addLayout(kpi)

        for visit in self._visits:
            date = str(visit.get("visit_date") or "")[:10]
            diag = self._clip(visit.get("diagnosis") or "", 30) or tr("Visit")
            line = "{date} — {diag}".format(date=date, diag=diag)
            self._visits_body.addWidget(
                self._history_row(line, lambda *_, v=visit: self._open_visit(v))
            )
        if not self._visits:
            self._visits_body.addWidget(self._empty_label(tr("No visits recorded")))

    def _render_owner_card(self):
        self._clear_layout(self._owner_body)

        header = QHBoxLayout()
        header.setSpacing(10)
        avatar = QLabel(self._initials(self._owner_name))
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 19px;"
            "font-size: 9pt; font-weight: bold;"
            % (hex_to_rgba(self._brand, 0.8), get_contrast_color(self._brand))
        )
        header.addWidget(avatar)

        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        if self._owner_name:
            name_col.addWidget(self._history_row(self._owner_name, lambda *_: self._open_owner()))
        else:
            no_owner = QLabel(tr("No owner"))
            no_owner.setProperty("class", "muted-label")
            name_col.addWidget(no_owner)
        member = QLabel(
            "%s: %s" % (tr("Member Since"), self._owner_created_at or tr("N/A"))
        )
        member.setProperty("class", "caption-label")
        name_col.addWidget(member)
        header.addLayout(name_col, 1)
        self._owner_body.addLayout(header)

        self._owner_body.addWidget(self._detail_row(tr("Owner ID:"), str(self._client_id or "")))
        self._owner_body.addWidget(self._detail_row(tr("Phone Number:"), self._owner_phone))

    def _render_appointments_card(self):
        self._clear_layout(self._appointments_body)
        status_colors = {
            "Pending": self._info,
            "Late": self._warning,
            "Completed": self._success,
            "Canceled": self._secondary,
        }
        for appointment in self._appointments:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            date = str(appointment.get("appointment_date") or "")[:16]
            service = self._clip(appointment.get("service") or "", 22) or tr("Appointment")
            h.addWidget(
                self._history_row(
                    "{date} · {service}".format(date=date, service=service),
                    lambda *_, a=appointment: self._open_appointment(a),
                ),
                1,
            )
            status = appointment.get("status") or "Pending"
            h.addWidget(self._badge(status, status_colors.get(status, self._info)))
            self._appointments_body.addWidget(row)
        if not self._appointments:
            self._appointments_body.addWidget(self._empty_label(tr("No upcoming appointments")))

    def _render_notes_card(self):
        self._clear_layout(self._notes_body)
        if self._editing:
            self._notes_edit = QTextEdit()
            self._notes_edit.setPlainText(self._notes)
            self._notes_edit.setPlaceholderText(tr("Add notes..."))
            self._notes_edit.setWordWrapMode(QTextOption.WordWrap)
            self._notes_edit.setFixedHeight(120)
            self._notes_body.addWidget(self._notes_edit)
        else:
            if self._notes and self._notes.strip():
                label = QLabel(self._notes)
                label.setWordWrap(True)
                self._notes_body.addWidget(label)
            else:
                self._notes_body.addWidget(self._empty_label(tr("No notes yet")))

    def _render_health_card(self):
        self._clear_layout(self._health_body)
        from src.core.health_status import (
            HEALTH_STATUS_CHOICES, resolve_health_status,
        )

        if self._editing:
            self._health_edit = QComboBox()
            self._health_edit.addItem(tr("Automatic (from latest exam)"), "")
            for value in HEALTH_STATUS_CHOICES:
                self._health_edit.addItem(tr(value), value)
            idx = self._health_edit.findData(self._health_status or "")
            if idx >= 0:
                self._health_edit.setCurrentIndex(idx)
            self._health_body.addWidget(QLabel("%s:" % tr("Health Status")))
            self._health_body.addWidget(self._health_edit)
        else:
            status = resolve_health_status(self._health_status, self._exam)
            color = {
                "Healthy": self._success,
                "Recovering": self._warning,
                "Critical": self._danger,
                "Diseased": self._danger,
                "Died": self._secondary,
            }.get(status, self._secondary)
            strip = QHBoxLayout()
            strip.setContentsMargins(0, 0, 0, 0)
            strip.setSpacing(8)
            strip.addWidget(QLabel("%s:" % tr("Current Status")))
            strip.addWidget(self._badge(tr(status), color))
            strip.addStretch()
            self._health_body.addLayout(strip)
            source = (
                tr("Manual override")
                if (self._health_status or "").strip()
                else tr("Derived from latest exam")
            )
            note = QLabel(source)
            note.setProperty("class", "caption-label")
            self._health_body.addWidget(note)

        if self._pet_id:
            timeline_btn = QPushButton(tr("View Full Timeline"))
            timeline_btn.setCursor(Qt.PointingHandCursor)
            timeline_btn.clicked.connect(lambda: self._open_timeline(self._pet_id, self._pet_name))
            self._health_body.addWidget(timeline_btn)

    # ------------------------------------------------------------------
    # Footer & edit mode
    # ------------------------------------------------------------------
    def _toggle_edit(self, editing):
        self._editing = editing
        self._set_edit_buttons(editing)
        self._render_pet_card()
        self._render_notes_card()
        self._render_health_card()

    def _save(self):
        name = self._name_edit.text().strip().capitalize() if hasattr(self, "_name_edit") else self._pet_name
        species = self._species_edit.currentText() if hasattr(self, "_species_edit") else self._species
        breed = self._breed_edit.text().strip().capitalize() if hasattr(self, "_breed_edit") else self._breed
        gender = self._gender_edit.currentText() if hasattr(self, "_gender_edit") else self._gender
        age = self._age_edit.value() if hasattr(self, "_age_edit") else self._age_months
        weight = self._weight
        client_id = self._owner_edit.currentData() if hasattr(self, "_owner_edit") else self._client_id
        notes = self._notes_edit.toPlainText().strip() if hasattr(self, "_notes_edit") else self._notes
        health_status = (
            self._health_edit.currentData()
            if hasattr(self, "_health_edit") else self._health_status
        ) or ""

        if not name:
            QMessageBox.warning(self, tr("Input Error"), tr("Pet name is required."))
            return

        from src.core.repositories import pending_changes_repo, pet_repo

        if can(self._current_user, "edit_records"):
            if pet_repo.update_pet(
                self._pet_id, name, species, breed, gender, age, weight, client_id,
                audit_user_id=(self._current_user or {}).get("user_id"),
                notes=notes,
                health_status=health_status,
            ):
                self._pet_name = name
                self._species = species
                self._breed = breed
                self._gender = gender
                self._age_months = age
                self._weight = weight
                self._client_id = client_id
                self._notes = notes
                self._health_status = health_status
                self._toggle_edit(False)
                self._notify_parent_changed()
            else:
                QMessageBox.critical(self, tr("Database Error"), tr("Could not update pet."))
        else:
            user_id = (self._current_user or {}).get("user_id")
            pid = pending_changes_repo.submit_change(
                user_id, "pets", self._pet_id, "UPDATE",
                {
                    "pet_name": name,
                    "species": species,
                    "breed": breed,
                    "gender": gender,
                    "age_months": age,
                    "weight": weight,
                    "client_id": client_id,
                    "notes": notes,
                    "health_status": health_status,
                },
            )
            if pid:
                QMessageBox.information(
                    self,
                    tr("Submitted"),
                    tr("Your change has been submitted for admin approval."),
                )
                self.accept()
            else:
                QMessageBox.critical(self, tr("Error"), tr("Failed to submit change request."))

    # ------------------------------------------------------------------
    # Click-through actions
    # ------------------------------------------------------------------
    def _open_visit(self, visit):
        data = {
            "visit_id": visit.get("visit_id"),
            "visit_date": visit.get("visit_date") or "",
            "owner_name": getattr(self, "_owner_name", "") or "",
            "pet_name": visit.get("pet_name") or "",
            "diagnosis": visit.get("diagnosis") or "",
            "notes": visit.get("notes") or "",
            "consult": visit.get("is_consult", 0),
            "owner_id": getattr(self, "_client_id", None),
            "pet_id": getattr(self, "_pet_id", None),
        }
        self._close_and_open(
            lambda parent: VisitInfoDialog(data, parent, current_user=self._current_user)
        )

    def _open_owner(self):
        owner = {
            "client_id": self._client_id,
            "owner_name": self._owner_name,
            "phone_number": self._owner_phone,
            "pets": [],
        }
        self._close_and_open(
            lambda parent: OwnerInfoDialog(owner, parent, current_user=self._current_user)
        )

    def _open_appointment(self, appointment):
        from src.ui.dialogs.appointments_dialog import AppointmentsDialog
        self._close_and_open(
            lambda parent: AppointmentsDialog(current_user=self._current_user, parent=parent)
        )

    def _close_and_open(self, factory):
        """Closes this dialog, then opens the target dialog on the parent page."""
        parent = self.parent()
        self.accept()
        dialog = factory(parent if parent is not None else self)
        dialog.exec_()
        self._notify_parent_changed()

    def _open_timeline(self, pet_id, pet_name):
        from src.ui.dialogs.pet_health_timeline_dialog import PetHealthTimelineDialog
        dialog = PetHealthTimelineDialog(pet_id, pet_name, self)
        dialog.exec_()


class VisitInfoDialog(InfoDialogMixin, ClinicalSectionsMixin, SupplyReceiptMixin, QDialog):
    """Card-based summary of a single clinical visit with an in-dialog Edit mode.

    Layout (2-column card grid):
        Row 1: Visit Info | Follow-ups
        Row 2: Owner Info  | Pet Info
        Row 3: Clinical    | Billing

    Visit rows are opened by clicking the Visit ID link in the visits pages.
    Edit mode (footer Edit button, for ``edit_records`` users only) edits the
    visit fields, clinical notes, follow-ups and the receipt (supplies +
    discount); the billing card's Adjust action opens ``VisitAdjustDialog``.
    The record-book clinical exam is shown read-only.
    """

    def __init__(self, data, parent=None, current_user=None):
        super().__init__(parent)
        self._current_user = current_user

        self._visit_id = data.get("visit_id")
        self._visit_date = str(data.get("visit_date") or "")[:16]
        self._owner_name = data.get("owner_name") or ""
        self._pet_name = data.get("pet_name") or ""
        self._diagnosis = data.get("diagnosis") or ""
        self._reason = data.get("reason_for_visit") or ""
        self._notes = data.get("notes") or ""
        self._consult = 1 if str(data.get("consult") or "").lower() in ("1", "yes", "true") else 0
        self._doctor_id = data.get("doctor_id")
        self._doctor_name = data.get("doctor_name") or ""
        self._owner_id = data.get("owner_id")
        self._pet_id = data.get("pet_id")
        self._receipt_id = data.get("receipt_id")
        if isinstance(self._receipt_id, str) and self._receipt_id.strip().isdigit():
            self._receipt_id = int(self._receipt_id)

        self._pet = {}
        self._owner_phone = ""
        self._owner_created_at = ""
        self._exam = None
        self._followups = []
        self._receipt = None
        self._editing = False
        self._footer_box = None

        palette = get_active_palette()
        self._secondary = palette.get("text_secondary", "#636E72")
        self._border = palette.get("border", "#DCDDE1")
        self._success = palette.get("state_success", "#2ECC71")
        self._danger = palette.get("state_danger", "#E74C3C")
        self._warning = palette.get("state_warning", "#F39C12")
        self._info = palette.get("state_info", "#3498DB")
        self._brand = palette.get("brand_500", "#4A90E2")

        self.setWindowTitle(tr("Visit Details"))
        self.setWindowIcon(QIcon())
        self.setStyleSheet(".QWidget { background: transparent; }")
        self.setMinimumSize(880, 620)

        self._load_data()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        self._build_cards()
        self._build_footer(root)

    def _build_footer(self, layout):
        footer = QHBoxLayout()
        self._btn_edit = QPushButton(tr("Edit"))
        self._btn_close = QPushButton(tr("Close"))
        self._btn_save = QPushButton(tr("Save Visit"))
        self._btn_cancel = QPushButton(tr("Cancel"))
        self._btn_edit.clicked.connect(lambda: self._toggle_edit(True))
        self._btn_cancel.clicked.connect(lambda: self._toggle_edit(False))
        self._btn_save.clicked.connect(self._save_edits)
        self._btn_close.clicked.connect(self.accept)
        footer.addStretch()
        for button in (self._btn_edit, self._btn_save, self._btn_cancel, self._btn_close):
            footer.addWidget(button)
        layout.addLayout(footer)
        self._set_edit_buttons(False)

    def _can_edit(self):
        # Visits have no pending-changes path, so only direct writers can edit.
        return self._can_write()

    def _toggle_edit(self, editing):
        if editing and not self._can_edit():
            return
        self._editing = editing
        self._set_edit_buttons(editing)
        self._render_visit_card()
        self._render_clinical_card()
        self._render_followups_card()
        self._render_billing_card()

    def _open_adjust(self):
        if not self._receipt_id:
            return
        from src.ui.dialogs.visit_adjust_dialog import VisitAdjustDialog
        dialog = VisitAdjustDialog(
            self._visit_id, self._receipt_id, self, current_user=self._current_user
        )
        if dialog.exec_():
            self._load_data()
            self._render_billing_card()
            self._notify_parent_changed()

    def _current_consult_fee(self):
        from src.config.constants import DEFAULT_CONSULT_FEE
        from src.utils.settings_manager import SettingsManager
        return float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))

    def _save_edits(self):
        from src.core.repositories import visit_repo, sales_repo, user_repo, supply_repo
        from src.core.repositories import receipt_adjustment_repo
        from src.core.repositories.audit_repo import record_action
        user_id = (self._current_user or {}).get("user_id")

        date_str = self._date_edit.dateTime().toString(DATE_TIME_FORMAT)
        reason = self._reason_edit.text().strip()
        diagnosis = self._diag_edit.text().strip()
        notes = self._notes_edit.toPlainText().strip()
        consult_on = self._consult_cb.isChecked()
        doctor_id = None
        if getattr(self, "_doctor_combo", None) is not None and self._doctor_combo.currentIndex() >= 0:
            doctor_id = self._doctor_combo.currentData()

        consult_changed = bool(consult_on) != bool(self._consult)
        old_total = None
        if self._receipt_id:
            header = sales_repo.get_receipt(self._receipt_id)
            try:
                old_total = float(header["total_price"] or 0.0)
            except (TypeError, ValueError, KeyError):
                old_total = None

        ok = visit_repo.update_visit(
            self._visit_id, diagnosis, notes, date_str,
            1 if consult_on else 0,
            reason_for_visit=reason, doctor_id=doctor_id, audit_user_id=user_id,
        )
        if not ok:
            QMessageBox.critical(self, tr("Error"), tr("Failed to update visit record."))
            return

        if self._receipt_id:
            if not self._save_receipt_items(old_total, consult_on, consult_changed, user_id):
                return

        self._save_followups()

        self._visit_date = date_str
        self._reason = reason
        self._diagnosis = diagnosis
        self._notes = notes
        self._consult = 1 if consult_on else 0
        self._doctor_id = doctor_id
        if doctor_id is not None:
            self._doctor_name = next(
                (d["doctor_name"] for d in user_repo.get_doctors() if d["doctor_id"] == doctor_id),
                self._doctor_name,
            )
        self._editing = False
        self._set_edit_buttons(False)
        self._load_data()
        self._render_visit_card()
        self._render_clinical_card()
        self._render_followups_card()
        self._render_billing_card()
        self._notify_parent_changed()

    def _save_receipt_items(self, old_total, consult_on, consult_changed, user_id):
        """Applies consult reconcile + supply ops + discount, then records an adjustment."""
        from src.core.repositories import sales_repo, supply_repo
        from src.core.repositories.receipt_adjustment_repo import add_adjustment
        from src.core.repositories.audit_repo import record_action

        if consult_changed:
            sales_repo.reconcile_consultation(self._receipt_id, consult_on, self._current_consult_fee())

        current_lines = sales_repo.get_receipt_line_items(self._receipt_id)
        supply_lines = [it for it in current_lines if it["line_type"] == "Supply"]
        existing = {}
        for it in supply_lines:
            existing.setdefault(str(it["name"]), it)

        items = []
        kept_names = set()
        if getattr(self, "_supply_rows", None) is not None:
            for entry in self.get_final_items():
                name = str(entry["item_name"] or "").strip()
                if not name:
                    continue
                kept_names.add(name)
                line = existing.get(name)
                if line is not None:
                    items.append({
                        "op": "update",
                        "item_type": "Supply",
                        "item_id": line["item_id"],
                        "link_id": line["link_id"],
                        "quantity": entry["quantity"],
                        "unit_price": entry["price"],
                    })
                else:
                    supply_id = supply_repo.resolve_supply_id(name, entry["category"])
                    if supply_id is None:
                        continue
                    items.append({
                        "op": "add",
                        "item_type": "Supply",
                        "item_id": supply_id,
                        "name": name,
                        "quantity": entry["quantity"],
                        "unit_price": entry["price"],
                    })
            for name, line in existing.items():
                if name not in kept_names:
                    items.append({
                        "op": "delete",
                        "item_type": "Supply",
                        "item_id": line["item_id"],
                        "link_id": line["link_id"],
                    })

        line_totals = {it["link_id"]: it["quantity"] * it["unit_price"] for it in supply_lines}
        new_subtotal = sum(v for v in line_totals.values())
        for op in items:
            if op["item_type"] != "Supply":
                continue
            if op["op"] == "update":
                new_subtotal += op["quantity"] * op["unit_price"] - line_totals.get(op["link_id"], 0)
            elif op["op"] == "delete":
                new_subtotal -= line_totals.get(op["link_id"], 0)
            elif op["op"] == "add":
                new_subtotal += op["quantity"] * op["unit_price"]
        # Non-supply lines (services/others/packages) stay as-is.
        new_subtotal += sum(
            it["quantity"] * it["unit_price"]
            for it in current_lines if it["line_type"] != "Supply"
        )
        pct = self._discount_spin.value() if getattr(self, "_discount_spin", None) else 0.0
        # Cent-round so the stored discount matches what the dialog displayed.
        discount_cash = round(new_subtotal * (float(pct) / 100.0), 2)

        if not sales_repo.update_receipt(
            self._receipt_id, discount_cash, items, audit_user_id=user_id
        ):
            QMessageBox.critical(self, tr("Error"), tr("Failed to update receipt."))
            return False

        header = sales_repo.get_receipt(self._receipt_id)
        new_total = float(header["total_price"] or 0.0) if header else new_subtotal - discount_cash
        if old_total is not None and abs(new_total - old_total) > 0.004:
            details = []
            changes = []
            if consult_changed:
                details.append({
                    "item": tr("Consultation"),
                    "old_value": tr("Yes") if (not consult_on) else tr("No"),
                    "new_value": tr("Yes") if consult_on else tr("No"),
                })
                changes.append({
                    "field_name": tr("Consultation"),
                    "old_value": "1" if (not consult_on) else "0",
                    "new_value": "1" if consult_on else "0",
                })
            for name, line in existing.items():
                if name not in kept_names:
                    details.append({
                        "item": name,
                        "old_value": format_currency(line["quantity"] * line["unit_price"]),
                        "new_value": format_currency(0.0),
                    })
            add_adjustment(
                self._receipt_id,
                visit_id=self._visit_id,
                adjusted_by=user_id,
                description=tr("Receipt adjusted: total {old} -> {new}").format(
                    old=format_currency(old_total), new=format_currency(new_total)
                ),
                old_total=old_total,
                new_total=float(new_total),
                details=details,
            )
            record_action(
                "ADJUST", "receipts", self._receipt_id,
                changes=changes, user_id=user_id,
            )
        return True

    def _save_followups(self):
        """Saves follow-up editors: updates kept, deletes removed, adds new."""
        from src.core.repositories import followup_repo

        for entry in getattr(self, "_followup_editors", []):
            followup_id = entry.get("id")
            date_str = entry["date"].dateTime().toString(DATE_TIME_FORMAT)
            notes = entry["notes"].text().strip()
            if followup_id is None:
                followup_repo.add_followup(self._visit_id, date_str, notes=notes)
            else:
                followup_repo.update_followup(
                    followup_id, date_str, entry.get("state_id"), notes,
                    doctor_id=entry.get("doctor_id"),
                )
        for followup_id in getattr(self, "_removed_followup_ids", []):
            followup_repo.delete_followup(followup_id)

    def _update_total(self):
        total = 0.0
        if getattr(self, "_supply_rows", None) is not None:
            total = sum(e["quantity"] * e["price"] for e in self.get_final_items())
        if getattr(self, "supplies_total_label", None) is not None:
            self.supplies_total_label.setText(
                tr("Supplies total: {amount}").format(amount=format_currency(total))
            )

    def _settle_receipt(self):
        from src.core.repositories import payment_repo
        try:
            balance = payment_repo.get_receipt_balance(self._receipt_id) or 0.0
        except Exception:
            balance = 0.0
        if balance <= 0:
            return
        answer = QMessageBox.question(
            self, tr("Settle Payment"),
            tr("Pay the outstanding balance of {amount}?").format(amount=format_currency(balance)),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if payment_repo.add_payment(self._receipt_id, balance, "Cash",
                                    tr("Settled from visit details"),
                                    audit_user_id=(self._current_user or {}).get("user_id")):
            self._load_data()
            self._render_billing_card()
            self._notify_parent_changed()
        else:
            QMessageBox.critical(self, tr("Error"), tr("Failed to record payment."))

    def _load_data(self):
        from src.core.repositories import client_repo, sales_repo, payment_repo
        from src.core.repositories import followup_repo, clinical_exam_repo

        self._pet = self._resolve_pet()
        if self._pet:
            self._pet_id = self._pet.get("pet_id") or self._pet_id
            self._pet_name = self._pet.get("pet_name") or self._pet_name
            self._owner_id = self._pet.get("client_id") or self._owner_id
            self._owner_name = self._pet.get("owner_name") or self._owner_name

        if not self._owner_id and self._owner_name:
            client = next(
                (c for c in client_repo.get_clients() if c["owner_name"] == self._owner_name),
                None,
            )
            if client:
                self._owner_id = client["client_id"]
        if self._owner_id:
            details = client_repo.get_owner_details(self._owner_id)
            if details:
                self._owner_name = details.get("owner_name") or self._owner_name
                self._owner_phone = details.get("phone_number") or ""
                self._owner_created_at = str(details.get("created_at") or "")[:10]

        vid = self._visit_id
        if vid is not None:
            try:
                self._exam = clinical_exam_repo.get_clinical_exam(vid)
            except Exception:
                self._exam = None
            try:
                self._followups = followup_repo.get_followups_for_visit(vid)
            except Exception:
                self._followups = []

        if not self._receipt_id and self._visit_id is not None:
            try:
                self._receipt_id = sales_repo.get_receipt_for_visit(self._visit_id)
            except Exception:
                self._receipt_id = None

        if self._receipt_id:
            try:
                self._receipt = sales_repo.get_receipt(self._receipt_id)
            except Exception:
                self._receipt = None

    def _resolve_pet(self):
        from src.core.repositories import pet_repo
        if self._pet_id:
            details = pet_repo.get_pet_details(self._pet_id)
            if details:
                return details
        name = (self._pet_name or "").strip()
        if name:
            return next((p for p in pet_repo.get_pets() if p["pet_name"] == name), None)
        return None

    def _build_cards(self):
        visit_card, self._visit_body = self._make_card(tr("Visit Info"))
        pet_card, self._pet_body = self._make_card(tr("Pet Info"))
        owner_card, self._owner_body = self._make_card(tr("Owner Info"))
        followup_card, self._followup_body = self._make_card(tr("Follow-ups"))
        clinical_card, self._clinical_body = self._make_card(tr("Clinical Exam"))
        billing_card, self._billing_body = self._make_card(tr("Billing"))

        self._grid.addWidget(visit_card, 0, 0)
        self._grid.addWidget(followup_card, 0, 1)
        self._grid.addWidget(owner_card, 1, 0)
        self._grid.addWidget(pet_card, 1, 1)
        self._grid.addWidget(clinical_card, 2, 0)
        self._grid.addWidget(billing_card, 2, 1)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)

        self._render_visit_card()
        self._render_pet_card()
        self._render_owner_card()
        self._render_followups_card()
        self._render_clinical_card()
        self._render_billing_card()

    def _render_visit_card(self):
        self._clear_layout(self._visit_body)

        header = QHBoxLayout()
        header.setSpacing(10)
        avatar = QLabel("#%s" % (self._visit_id or "?"))
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            "background-color: %s; color: %s; border-radius: 23px;"
            "font-size: 11pt; font-weight: bold;"
            % (self._brand, get_contrast_color(self._brand))
        )
        header.addWidget(avatar)
        info_col = QVBoxLayout()
        info_col.setSpacing(0)
        title = QLabel(tr("Visit #%s") % (self._visit_id or ""))
        title.setProperty("class", "avatar-name")
        info_col.addWidget(title)
        subtitle = QLabel(self._visit_date or tr("N/A"))
        subtitle.setProperty("class", "caption-label")
        info_col.addWidget(subtitle)
        header.addLayout(info_col, 1)
        self._visit_body.addLayout(header)

        if self._editing and self._can_write():
            from src.core.repositories import visit_repo, user_repo
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            self._date_edit = QDateTimeEdit(
                QDateTime.fromString(self._visit_date or "", DATE_TIME_FORMAT)
            )
            self._date_edit.setDisplayFormat(DATE_TIME_FORMAT)
            self._date_edit.setCalendarPopup(True)
            self._doctor_combo = QComboBox()
            self._doctor_combo.addItem(tr("Unassigned"), None)
            for doctor in user_repo.get_doctors():
                self._doctor_combo.addItem(doctor["doctor_name"], doctor["doctor_id"])
            if self._doctor_id is not None:
                idx = self._doctor_combo.findData(self._doctor_id)
                if idx >= 0:
                    self._doctor_combo.setCurrentIndex(idx)
            self._reason_edit = QLineEdit(self._reason or "")
            self._diag_edit = QLineEdit(self._diagnosis or "")
            completer = QCompleter(visit_repo.get_unique_diagnoses())
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self._diag_edit.setCompleter(completer)
            self._consult_cb = QCheckBox(tr("Consult Charge Applied?"))
            self._consult_cb.setChecked(bool(self._consult))
            form.addRow(tr("Visit Date:"), self._date_edit)
            form.addRow(tr("Doctor:"), self._doctor_combo)
            form.addRow(tr("Reason for Visit:"), self._reason_edit)
            form.addRow(tr("Diagnosis:"), self._diag_edit)
            form.addRow(tr("Consult:"), self._consult_cb)
            self._visit_body.addLayout(form)
            return

        self._visit_body.addWidget(
            self._detail_row(tr("Doctor:"), self._doctor_name or tr("Unassigned"))
        )
        if self._reason:
            self._visit_body.addWidget(self._detail_row(tr("Reason for Visit:"), self._reason))
        self._visit_body.addWidget(self._detail_row(tr("Diagnosis:"), self._diagnosis or tr("N/A")))
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(8)
        strip.addWidget(QLabel(tr("Consult:")))
        strip.addWidget(self._badge(
            tr("Yes") if self._consult else tr("No"),
            self._success if self._consult else self._secondary,
        ))
        strip.addStretch()
        self._visit_body.addLayout(strip)

    def _render_pet_card(self):
        self._clear_layout(self._pet_body)
        pet = self._pet or {}
        parts = [p for p in (
            pet.get("species"),
            pet.get("breed"),
            pet.get("gender"),
        ) if p]

        lines = []
        if pet.get("age_months") not in (None, ""):
            lines.append("%s: %s" % (tr("Age"), format_age(pet.get("age_months"))))
        if pet.get("weight") not in (None, ""):
            lines.append("%s: %s" % (tr("Weight"), str(pet.get("weight"))))

        if not self._pet_name and not parts:
            self._pet_body.addWidget(self._empty_label(tr("N/A")))
            return

        line = " · ".join([self._pet_name] + parts) or self._pet_name
        self._pet_body.addWidget(
            self._history_row(self._clip(line, 44), self._open_pet)
        )
        if lines:
            meta = QLabel("   ".join(lines))
            meta.setProperty("class", "muted-label")
            self._pet_body.addWidget(meta)

    def _render_owner_card(self):
        self._clear_layout(self._owner_body)
        if not self._owner_name:
            self._owner_body.addWidget(self._empty_label(tr("N/A")))
            return
        self._owner_body.addWidget(
            self._history_row(self._clip(self._owner_name, 44), self._open_owner)
        )
        if self._owner_phone:
            self._owner_body.addWidget(self._detail_row(tr("Phone:"), self._owner_phone))
        if self._owner_created_at:
            self._owner_body.addWidget(
                self._detail_row(tr("Member Since"), self._owner_created_at)
            )

    def _render_followups_card(self):
        self._clear_layout(self._followup_body)
        if self._editing and self._can_write():
            self._render_followups_edit()
            return
        status_colors = {
            "Pending": self._info,
            "Completed": self._success,
            "Canceled": self._secondary,
            "Late": self._warning,
        }
        for fu in self._followups:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            date = str(fu.get("followup_date") or "")[:16]
            note = self._clip(fu.get("notes") or "", 24)
            line = date + ("  ·  " + note if note else "")
            h.addWidget(QLabel(line), 1)
            status = fu.get("status") or "Pending"
            h.addWidget(self._badge(status, status_colors.get(status, self._info)))
            self._followup_body.addWidget(row)
        if not self._followups:
            self._followup_body.addWidget(self._empty_label(tr("No follow-ups")))

    def _render_followups_edit(self):
        from src.core.repositories import followup_repo
        self._followup_editors = []
        self._removed_followup_ids = []

        for fu in self._followups:
            self._add_followup_editor(
                fu.get("followup_id"), fu.get("followup_date") or "",
                fu.get("notes") or "", fu.get("state_id"), fu.get("doctor_id"),
            )

        add_btn = QPushButton(tr("+ Add Follow-up"))
        add_btn.setProperty("class", "compact-button")
        add_btn.clicked.connect(self._add_followup_editor)
        self._followup_body.addWidget(add_btn)

    def _add_followup_editor(self, followup_id=None, date_str="", notes="",
                             state_id=None, doctor_id=None, *args):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(6)
        date_edit = QDateTimeEdit(QDateTime.fromString(str(date_str)[:16], DATE_TIME_FORMAT))
        date_edit.setDisplayFormat(DATE_TIME_FORMAT)
        date_edit.setCalendarPopup(True)
        notes_edit = QLineEdit(notes or "")
        notes_edit.setPlaceholderText(tr("Notes..."))
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(28, 28)
        del_btn.setProperty("action", "delete")
        h.addWidget(date_edit, 1)
        h.addWidget(notes_edit, 2)
        h.addWidget(del_btn)
        entry = {
            "id": followup_id,
            "date": date_edit,
            "notes": notes_edit,
            "state_id": state_id,
            "doctor_id": doctor_id,
        }
        self._followup_editors.append(entry)
        del_btn.clicked.connect(lambda: self._remove_followup_editor(entry, row))

        if self._followup_body is not None:
            layout = self._followup_body
            if layout.itemAt(layout.count() - 1) is not None and layout.count() > 1:
                layout.insertWidget(layout.count() - 1, row)
            else:
                layout.addWidget(row)

    def _remove_followup_editor(self, entry, row):
        if entry in self._followup_editors:
            self._followup_editors.remove(entry)
        if entry.get("id") is not None:
            self._removed_followup_ids.append(entry.get("id"))
        row.setParent(None)
        row.deleteLater()

    def _render_clinical_card(self):
        self._clear_layout(self._clinical_body)
        if self._editing and self._can_write():
            self._clinical_body.addWidget(QLabel(tr("Notes:")))
            self._notes_edit = QTextEdit(self._notes or "")
            self._notes_edit.setFixedHeight(70)
            self._clinical_body.addWidget(self._notes_edit)
            return
        if not self._exam:
            self._clinical_body.addWidget(self._empty_label(tr("No clinical exam recorded")))
            return
        self._render_exam_sections(self._exam)

    @staticmethod
    def _exam_join(*parts):
        return " · ".join(str(p) for p in parts if p not in (None, ""))

    @staticmethod
    def _exam_token(value):
        return str(value).strip().capitalize() if value else ""

    def _add_exam_section(self, title_text, pairs):
        pairs = [(label, value) for label, value in pairs if value]
        if not pairs:
            return
        heading = QLabel("<b>%s</b>" % title_text)
        heading.setProperty("class", "section-heading")
        self._clinical_body.addWidget(heading)
        for label, value in pairs:
            self._clinical_body.addWidget(
                self._detail_row(self._clip(label, 26), self._clip(str(value), 34))
            )

    def _render_exam_sections(self, exam):
        general = exam.get("generalPhysicalExamination") or {}
        signs = exam.get("clinicalSigns") or {}
        physical = exam.get("physicalExam") or {}
        recommended = exam.get("recommendedTestsTreatments") or {}

        weight = general.get("weight") or {}
        temperature = general.get("temperature") or {}
        self._add_exam_section(tr("General Physical Examination"), [
            (tr("Weight"), self._exam_join(weight.get("value"), tr(self._exam_token(weight.get("condition"))))),
            (tr("Temperature"), self._exam_join(temperature.get("value"), tr(self._exam_token(temperature.get("status"))))),
            (tr("Neutered"), tr("Yes") if general.get("neutered") else ""),
        ])

        feces = signs.get("feces") or {}
        sign_pairs = [
            (tr("Energy"), tr(self._exam_token(signs.get("energy")))),
            (tr("Appetite"), tr(self._exam_token(signs.get("appetite")))),
            (tr("Water Intake"), tr(self._exam_token(signs.get("waterIntake")))),
            (tr("Urination"), tr(self._exam_token(signs.get("urination")))),
            (tr("Feces"), self._exam_join(
                tr(self._exam_token(feces.get("status"))), feces.get("notes"))),
        ]
        for key, label in (("vomiting", "Vomiting"), ("coughing", "Coughing"),
                           ("sneezing", "Sneezing")):
            entry = signs.get(key) or {}
            if entry.get("present"):
                sign_pairs.append((tr(label), entry.get("frequency") or tr("Yes")))
        self._add_exam_section(tr("Clinical Signs"), sign_pairs)

        self._add_exam_section(tr("Routine Tests"), [
            (t.get("testName") or tr("Test"),
             tr(self._exam_token(t.get("result"))) or tr("Pending"))
            for t in (exam.get("routineTests") or [])
        ])

        vaccinations = exam.get("vaccinations") or []
        self._add_exam_section(tr("Vaccinations"), [
            (tr("Given"), ", ".join(str(v) for v in vaccinations)),
        ])

        systems = (
            ("Heart", "heart"), ("Lungs", "lungs"), ("Eyes", "eyes"),
            ("Ears", "ears"), ("Nose & Throat", "noseAndThroat"),
            ("Mouth, Teeth & Gums", "mouthTeethGums"), ("Abdomen", "abdomen"),
            ("Musculoskeletal", "musculoskeletal"), ("Skin, Hair & Coat", "skinHairCoat"),
        )
        physical_pairs = []
        for label, key in systems:
            data = physical.get(key) or {}
            parts = list(data.get("findings") or []) + list(data.get("conditions") or [])
            if key == "heart":
                murmur = data.get("murmur") or {}
                if murmur.get("left"):
                    parts.append("%s: %s" % (tr("Murmur"), murmur.get("left")))
                if murmur.get("right"):
                    parts.append("%s: %s" % (tr("Murmur"), murmur.get("right")))
                if data.get("rateCategory") in ("slow", "fast"):
                    parts.append(tr(self._exam_token(data.get("rateCategory"))))
            if key == "mouthTeethGums" and data.get("gingivitisSeverity") not in (None, "", "none"):
                parts.append("%s (%s)" % (tr("Gingivitis"), tr(self._exam_token(data.get("gingivitisSeverity")))))
            if key == "musculoskeletal" and data.get("locations"):
                parts.append(", ".join(str(loc) for loc in data["locations"]))
            if parts:
                physical_pairs.append((tr(label), "; ".join(str(p) for p in parts)))
            elif data.get("normal") is True:
                physical_pairs.append((tr(label), tr("Normal")))
        self._add_exam_section(tr("Physical Exam"), physical_pairs)

        recommended_labels = (
            ("xrays", "X-rays"), ("ekg", "EKG"), ("urinalysis", "Urinalysis"),
            ("thyroidLevel", "Thyroid Level"),
            ("ultrasonicTeethCleaning", "Ultrasonic Teeth Cleaning"),
            ("drugMonitoring", "Drug Monitoring"), ("bloodScreen", "Blood Screen"),
            ("deepEarVideo", "Deep Ear Video"),
        )
        rec_pairs = [(tr(label), tr("Yes")) for key, label in recommended_labels
                     if recommended.get(key)]
        if recommended.get("other"):
            rec_pairs.append((tr("Other"), recommended.get("other")))
        self._add_exam_section(tr("Recommended Tests & Treatments"), rec_pairs)

    def _render_billing_card(self):
        self._clear_layout(self._billing_body)
        editing = self._editing and self._can_write()
        if self._receipt:
            from src.core.repositories import payment_repo

            title = QLabel("<b>%s</b>" % tr("Receipt Details"))
            title.setProperty("class", "section-heading")
            self._billing_body.addWidget(title)
            self._billing_body.addWidget(
                self._detail_row(tr("Receipt ID:"), str(self._receipt.get("receipt_id") or ""))
            )
            self._billing_body.addWidget(
                self._detail_row(tr("Date:"), str(self._receipt.get("receipt_date") or "")[:10])
            )
            self._billing_body.addWidget(
                self._detail_row(tr("Total"), format_currency(self._receipt.get("total_price")))
            )
            self._billing_body.addWidget(
                self._detail_row(tr("Paid"), format_currency(payment_repo.get_total_paid(self._receipt_id)))
            )
            status = self._receipt.get("payment_status") or "Unpaid"
            status_color = {
                "Paid": self._success,
                "Partial": self._warning,
                "Unpaid": self._danger,
            }.get(status, self._info)
            strip = QHBoxLayout()
            strip.setContentsMargins(0, 0, 0, 0)
            strip.setSpacing(8)
            strip.addWidget(QLabel(tr("Payment Status:")))
            strip.addWidget(self._badge(status, status_color))
            strip.addStretch()
            self._billing_body.addLayout(strip)
            try:
                balance = payment_repo.get_receipt_balance(self._receipt_id) or 0.0
            except Exception:
                balance = 0.0
            self._billing_body.addWidget(self._detail_row(tr("Outstanding"), format_currency(balance)))
        elif not editing:
            self._billing_body.addWidget(self._empty_label(tr("No receipts yet")))

        if editing:
            from src.core.repositories import sales_repo
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            self._discount_spin = QDoubleSpinBox()
            self._discount_spin.setRange(0, 100)
            self._discount_spin.setDecimals(2)
            self._discount_spin.setSuffix(" %")
            self._discount_spin.valueChanged.connect(self._update_total)
            form.addRow(tr("Discount (%):"), self._discount_spin)
            subtotal = 0.0
            if self._receipt_id:
                subtotal = sum(
                    it["quantity"] * it["unit_price"]
                    for it in sales_repo.get_receipt_line_items(self._receipt_id)
                )
            if subtotal > 0 and self._receipt:
                self._discount_spin.setValue(
                    round((float(self._receipt.get("discount") or 0) / subtotal) * 100.0, 2)
                )
            self._billing_body.addLayout(form)

            self._setup_supplies_section(self._billing_body)
            self._prefill_supply_rows()
            self.supplies_total_label = QLabel(
                tr("Supplies total: {amount}").format(amount=format_currency(0.0))
            )
            self.supplies_total_label.setProperty("class", "muted-label")
            self._billing_body.addWidget(self.supplies_total_label)
            self._update_total()

        self._add_billing_actions()

    def _prefill_supply_rows(self):
        if not self._receipt_id or getattr(self, "items_layout", None) is None:
            return
        from src.core.repositories import sales_repo
        try:
            lines = [
                it for it in sales_repo.get_receipt_line_items(self._receipt_id)
                if it["line_type"] == "Supply" and it.get("name")
            ]
        except Exception:
            lines = []
        for line in lines:
            self._add_supply_row()
            row_widget = self.items_layout.itemAt(self.items_layout.count() - 1).widget()
            combos = row_widget.findChildren(QComboBox)
            qty_boxes = row_widget.findChildren(QSpinBox)
            if len(combos) >= 3:
                cat, sub, item = combos[:3]
                cat.setCurrentText(line.get("category") or "")
                sub.setCurrentText(line.get("sub_category") or "")
                idx = item.findText(str(line["name"]))
                if idx >= 0:
                    item.setCurrentIndex(idx)
            if qty_boxes:
                qty_boxes[0].setValue(int(line["quantity"] or 1))

    def _add_billing_actions(self):
        if not (self._editing and self._can_write()):
            return
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        if self._receipt_id:
            try:
                from src.core.repositories import payment_repo
                balance = payment_repo.get_receipt_balance(self._receipt_id) or 0.0
            except Exception:
                balance = 0.0
            if balance > 0:
                settle = QPushButton(tr("Settle Payment"))
                settle.clicked.connect(self._settle_receipt)
                row.addWidget(settle)
            adjust = QPushButton(tr("Adjust"))
            adjust.clicked.connect(self._open_adjust)
            row.addWidget(adjust)
        row.addStretch()
        self._billing_body.addLayout(row)

    def _open_pet(self):
        pet = self._pet or {
            "pet_id": self._pet_id,
            "pet_name": self._pet_name,
            "client_id": self._owner_id,
            "owner_name": self._owner_name,
        }
        self._close_and_open(
            lambda parent: PetInfoDialog(pet, parent, current_user=self._current_user)
        )

    def _open_owner(self):
        owner = {
            "client_id": self._owner_id,
            "owner_name": self._owner_name,
            "phone_number": self._owner_phone,
        }
        self._close_and_open(
            lambda parent: OwnerInfoDialog(owner, parent, current_user=self._current_user)
        )

    def _close_and_open(self, factory):
        """Closes this dialog, then opens the target dialog on the parent page."""
        parent = self.parent()
        self.accept()
        dialog = factory(parent if parent is not None else self)
        dialog.exec_()
        self._notify_parent_changed()