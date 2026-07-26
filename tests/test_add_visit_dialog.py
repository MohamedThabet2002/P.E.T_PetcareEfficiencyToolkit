"""Tests for the AddFullEntryDialog wizard layout (Add Visit).

Covers the professional/compact rework: the framed step indicator with numbered
badges and a step counter, the two titled cards on step 1, the footer chrome,
navigation gating, and the receipt preview wiring.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFormLayout, QFrame, QLabel, QMessageBox,
    QPushButton, QTableWidget,
)

from src.ui.dialogs.base_clinical_dialog import (
    BASE_DIALOG_MIN_HEIGHT,
    BASE_DIALOG_MIN_WIDTH,
    SECTION_CHEVRON_CLOSED,
    SECTION_CHEVRON_OPEN,
    STEP_CONTENT_MARGIN,
    STEP_CONTENT_SPACING,
)
from src.ui.dialogs.full_entry_dialog import (
    ADD_FULL_ENTRY_DIALOG_HEIGHT,
    ADD_FULL_ENTRY_DIALOG_WIDTH,
    AddFullEntryDialog,
)


@pytest.fixture
def dialog(qapp, fresh_db):
    """A ready-to-use Add Visit dialog on an isolated database.

    A package is seeded because ``_add_package_row`` opens a real (modal)
    information box when none exist, which access-violates pytest offscreen.
    """
    from src.core.repositories import package_repo
    package_repo.add_package("Vaccine Bundle", "Annual shots", 40.0)

    dlg = AddFullEntryDialog(current_user={"user_id": 1, "username": "admin",
                                           "roles": ["admin"]})
    yield dlg
    dlg.deleteLater()


def _card_form(card):
    """Returns the QFormLayout inside a card built by _make_form_card."""
    return card.layout().itemAt(1).layout()


class TestStepIndicator:
    """The step strip is a framed card of numbered badges, not a flat run of text."""

    def test_stepper_is_framed_and_numbered(self, dialog):
        assert dialog.step_indicator_row.objectName() == "wizardStepper"
        assert [b.text() for b in dialog._step_badges] == ["1", "2", "3", "4"]
        assert [b.property("class") for b in dialog._step_badges] == \
            ["step-badge"] * 4
        assert [l.text() for l in dialog._step_labels] == [
            "Patient & Visit", "Clinical Exam", "Other Supplies", "Billing & Review",
        ]
        # One arrow separates each pair of steps
        arrows = [
            w for w in dialog.step_indicator_row.findChildren(QLabel)
            if w.property("class") == "step-arrow"
        ]
        assert len(arrows) == len(dialog._step_labels) - 1

    def test_badge_states_track_the_current_step(self, dialog):
        states = lambda: [b.property("state") for b in dialog._step_badges]
        assert states() == ["active", "pending", "pending", "pending"]
        assert dialog.step_counter_label.text() == "Step 1 of 4"

        dialog._go_next_step()
        assert states() == ["done", "active", "pending", "pending"]
        assert dialog.step_counter_label.text() == "Step 2 of 4"

        dialog._go_next_step()
        dialog._go_next_step()
        assert states() == ["done", "done", "done", "active"]
        assert dialog.step_counter_label.text() == "Step 4 of 4"

    def test_step_badge_numbering_has_no_prefix_in_the_title(self, dialog):
        """The number moved into its own badge, so titles are plain text."""
        assert not any(l.text().startswith("1.") for l in dialog._step_labels)


class TestNavigation:
    def test_next_and_back_walk_the_steps(self, dialog):
        assert dialog._current_step == 0
        assert dialog.back_button.isEnabled() is False

        dialog._go_next_step()
        assert dialog._current_step == 1
        assert dialog.back_button.isEnabled() is True

        dialog._go_previous_step()
        assert dialog._current_step == 0
        assert dialog.back_button.isEnabled() is False

    def test_next_and_save_swap_on_the_last_step(self, dialog):
        assert dialog.next_button.isHidden() is False
        assert dialog.save_button.isHidden() is True
        for _ in range(3):
            dialog._go_next_step()
        assert dialog._current_step == 3
        # isHidden(), not isVisible(): the dialog itself is never shown here
        assert dialog.next_button.isHidden() is True
        assert dialog.save_button.isHidden() is False

    def test_proceeding_is_gated_on_the_owner_name(self, dialog):
        assert dialog.next_button.isEnabled() is False
        assert dialog.save_button.isEnabled() is False

        dialog.owner_name.setText("Mohamed")
        assert dialog.next_button.isEnabled() is True
        assert dialog.save_button.isEnabled() is True

        dialog.owner_name.setText("   ")
        assert dialog.next_button.isEnabled() is False

    def test_returning_to_a_step_revalidates_it(self, dialog):
        """Clearing the owner name and stepping back must re-disable Save."""
        dialog.owner_name.setText("Mohamed")
        for _ in range(3):
            dialog._go_next_step()
        assert dialog._current_step == 3

        dialog._go_to_step(0)
        dialog.owner_name.clear()
        dialog._go_to_step(3)

        assert dialog._current_step == 3
        assert dialog.save_button.isEnabled() is False

    def test_stepper_click_returns_to_a_reached_step_only(self, dialog):
        # Nothing reached yet -> a click cannot skip the validation gate
        _click(dialog._step_items[2])
        assert dialog._current_step == 0

        for _ in range(2):
            dialog._go_next_step()
        assert dialog._current_step == 2

        # Back to the first step, then forward to a step already reached
        _click(dialog._step_items[0])
        assert dialog._current_step == 0
        _click(dialog._step_items[2])
        assert dialog._current_step == 2

        # Clicking the badge or the title of a reached step works too
        _click(dialog._step_badges[1])
        assert dialog._current_step == 1
        _click(dialog._step_labels[0])
        assert dialog._current_step == 0

        # ...but the unreached final step stays out of reach
        _click(dialog._step_items[3])
        assert dialog._current_step == 0


class TestCompactStepLayout:
    """Step 1 is two titled cards instead of one long scrolling column."""

    def test_step_one_has_identity_and_visit_cards(self, dialog):
        for card in (dialog.identity_card, dialog.visit_card):
            assert isinstance(card, QFrame)
            assert card.property("class") == "form-card"
            assert isinstance(_card_form(card), QFormLayout)

        assert _card_form(dialog.identity_card).rowCount() == 7
        assert _card_form(dialog.visit_card).rowCount() == 4

    def test_card_titles_are_translated_headings(self, dialog):
        headings = [
            card.layout().itemAt(0).widget().text()
            for card in (dialog.identity_card, dialog.visit_card)
        ]
        assert headings == ["Client & Pet Details", "Visit Details"]
        for card in (dialog.identity_card, dialog.visit_card):
            heading = card.layout().itemAt(0).widget()
            assert heading.property("class") == "form-card-title"
            assert heading.wordWrap() is True

    def test_step_one_body_is_not_the_detached_default_form(self, dialog):
        """bare_steps leaves the auto form out of the page, ready for the cards."""
        assert dialog.step_bodies[0].indexOf(dialog.step_forms[0]) == -1
        # The other steps keep their plain auto-generated form
        assert dialog.step_bodies[1].indexOf(dialog.step_forms[1]) != -1
        assert dialog.step_bodies[2].indexOf(dialog.step_forms[2]) != -1
        assert dialog.step_bodies[3].indexOf(dialog.step_forms[3]) != -1

    def test_step_pages_share_the_compact_rhythm(self, dialog):
        for body in dialog.step_bodies:
            assert body.spacing() == STEP_CONTENT_SPACING
            margins = body.contentsMargins()
            assert (margins.left(), margins.top()) == \
                (STEP_CONTENT_MARGIN[0], STEP_CONTENT_MARGIN[1])

    def test_dialog_is_wide_enough_for_two_columns_but_cannot_be_collapsed(
        self, dialog
    ):
        assert dialog.width() >= 900
        assert dialog.minimumWidth() == BASE_DIALOG_MIN_WIDTH
        assert dialog.minimumHeight() == BASE_DIALOG_MIN_HEIGHT

    def test_over_wide_labels_are_capped_so_the_page_never_scrolls_sideways(
        self, dialog
    ):
        for form in (_card_form(dialog.identity_card),
                     _card_form(dialog.visit_card)):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                label = item.widget() if item is not None else None
                if label is not None and label.wordWrap():
                    assert label.maximumWidth() <= 150

    def test_visit_date_uses_the_shared_display_format(self, dialog):
        assert dialog.v_date.displayFormat() == "yyyy-MM-dd HH:mm"


class TestSuppliesStep:
    def test_supply_and_package_sections_share_the_card_heading_style(self, dialog):
        assert dialog.supplies_header_label.property("class") == "form-card-title"
        assert dialog.packages_header_label.property("class") == "form-card-title"
        assert "<b>" not in dialog.supplies_header_label.text()
        assert "<b>" not in dialog.packages_header_label.text()

    def test_delete_button_is_pinned_to_the_trailing_edge(self, dialog):
        dialog._add_supply_row()
        row = dialog.items_layout.itemAt(0).widget().layout()
        assert row.itemAt(row.count() - 1).widget().property("action") == "delete"
        # ...preceded by a stretch so the delete column hugs the trailing edge
        assert row.itemAt(row.count() - 2).spacerItem() is not None

        dialog._add_package_row()
        pkg_row = dialog.pkg_items_layout.itemAt(0).widget().layout()
        assert pkg_row.itemAt(pkg_row.count() - 1).widget().property("action") == \
            "delete"
        assert pkg_row.itemAt(pkg_row.count() - 2).spacerItem() is not None

    def test_headers_align_with_the_trailing_delete_column(self, dialog):
        headers = dialog.headers_frame.layout()
        assert headers.itemAt(headers.count() - 1).spacerItem() is not None


class TestReceiptPreview:
    def test_receipt_card_and_items_table_are_wired(self, dialog):
        assert dialog.receipt_frame.property("class") == "receipt"
        assert isinstance(dialog.receipt_items_table, QTableWidget)
        assert dialog.receipt_items_table.objectName() == "receiptItems"
        assert dialog.receipt_frame.parent() is not None

    def test_print_and_export_were_moved_off_step_four(self, dialog):
        """Printing now lives in the post-save success dialog; Save Visit stays
        the only action on this step."""
        assert dialog.save_button.property("class") == "primary-action"
        assert not hasattr(dialog, "print_receipt_btn")
        assert not hasattr(dialog, "export_pdf_btn")

    def test_preview_hint_is_shown_before_the_receipt(self, dialog):
        assert dialog.receipt_hint_label.property("class") == "form-card-hint"
        assert dialog.receipt_hint_label.wordWrap() is True
        body = dialog.step_bodies[3]
        # Above the receipt card, just below the step's own (empty) form
        assert body.indexOf(dialog.receipt_hint_label) == 1
        assert body.indexOf(dialog.receipt_frame) > \
            body.indexOf(dialog.receipt_hint_label)

    def test_receipt_meta_follows_the_entered_patient(self, dialog):
        dialog.owner_name.setText("mohamed ali")
        dialog.phone.setText("0100")
        dialog.pet_name.setText("rex")
        dialog._update_total()
        assert dialog.receipt_owner.text() == "Mohamed Ali"
        assert dialog.receipt_phone.text() == "0100"
        assert dialog.receipt_pet.text() == "rex"

    def test_consultation_line_appears_in_the_receipt(self, dialog):
        dialog.consult.setChecked(True)
        dialog._update_total()
        table = dialog.receipt_items_table
        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "Consultation"
        assert table.item(0, 3).text() != "$0.00"


class TestFooterChrome:
    def test_footer_is_separated_from_the_working_area(self, dialog):
        assert dialog.footer_divider.objectName() == "dialogFooterDivider"
        layout = dialog.main_layout
        assert layout.indexOf(dialog.footer_divider) < \
            layout.indexOf(dialog.footer_layout)

    def test_footer_buttons_share_one_width(self, dialog):
        widths = {
            b.minimumWidth()
            for b in (dialog.back_button, dialog.cancel_button,
                      dialog.next_button, dialog.save_button)
        }
        assert len(widths) == 1


def _click(widget):
    """Sends a click the way the stepper's event filter receives it."""
    event = QMouseEvent(
        QEvent.MouseButtonRelease, QPoint(1, 1), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _shown(dialog, step):
    """Shows the dialog on `step` and settles the layout."""
    dialog.show()
    dialog._steps_widget.setCurrentIndex(step)
    QApplication.processEvents()
    return dialog


class TestNoDeadVerticalSpace:
    """Every step fills the dialog it opens in - no band of dead space.

    The wizard opens at its full design height instead of shrinking to its
    tallest step, so the spare height has to go somewhere: step 1 shares it
    between its two form cards, the supplies step hands it to its two lists,
    and the billing step hands it to the receipt card so the billing bar lands
    on the page's bottom edge. Step 2 (the exam step) is the exception - it
    keeps the base behaviour, with the room parked in its bottom spacer. Every
    page keeps that spacer as its last item (the page structure is part of the
    contract); it claims height only on step 2.
    """

    def test_each_step_page_ends_with_a_spacer(self, dialog):
        """The spacer stays the last item of every page."""
        for index, body in enumerate(dialog.step_bodies):
            last = body.itemAt(body.count() - 1)
            assert last.spacerItem() is not None
            # ...and it holds the page's room only on step 2.
            assert body.stretch(body.count() - 1) == (1 if index == 1 else 0)

    def test_padding_the_pages_twice_adds_nothing(self, dialog):
        """_initialise_step_layout runs from __init__ *and* showEvent."""
        before = [body.count() for body in dialog.step_bodies]
        dialog._initialise_step_layout()
        dialog._initialise_step_layout()
        assert [body.count() for body in dialog.step_bodies] == before

    def test_dialog_opens_at_its_default_height(self, dialog):
        """720px, not the height the tallest step happens to need."""
        _shown(dialog, 0)
        assert dialog.height() == ADD_FULL_ENTRY_DIALOG_HEIGHT
        assert dialog.width() == ADD_FULL_ENTRY_DIALOG_WIDTH
        # The fit never goes under the floor this dialog sets for itself...
        assert dialog._fit_floor == ADD_FULL_ENTRY_DIALOG_HEIGHT
        assert dialog.height() == dialog._fit_floor
        # ...and still stays inside the design bounds.
        assert dialog.height() <= dialog._design_height
        assert dialog.height() >= BASE_DIALOG_MIN_HEIGHT

    @pytest.mark.parametrize("step", [0, 2, 3])
    def test_step_content_reaches_the_bottom_of_the_page(self, dialog, step):
        """The content of these steps runs down to the page's bottom margin."""
        _shown(dialog, step)
        body = dialog.step_bodies[step]
        page = dialog._steps_widget.widget(step)
        spacer = body.itemAt(body.count() - 1)
        assert spacer.spacerItem() is not None
        assert spacer.geometry().height() <= 4
        last = body.itemAt(body.count() - 2)
        assert page.height() - last.geometry().bottom() \
            <= STEP_CONTENT_MARGIN[3] + 4

    def test_the_exam_step_keeps_its_room_in_the_spacer(self, dialog):
        """Step 2 is the reverted one: its cards stay at their natural height."""
        _shown(dialog, 1)
        body = dialog.step_bodies[1]
        page = dialog._steps_widget.widget(1)
        spacer = body.itemAt(body.count() - 1)
        # The spacer holds the slack...
        assert body.stretch(body.count() - 1) == 1
        assert spacer.geometry().height() > 4
        # ...so the last card stops well short of the page's bottom edge.
        last = body.itemAt(body.count() - 2)
        assert page.height() - last.geometry().bottom() > 4
        assert last.widget().height() <= 48

    @pytest.mark.parametrize("step", [0, 1, 2, 3])
    def test_no_step_needs_to_scroll(self, dialog, step):
        """Every step fits the dialog, so no step opens with a scrollbar."""
        _shown(dialog, step)
        page = dialog._steps_widget.widget(step)
        assert page.sizeHint().height() <= dialog.left_scroll.viewport().height()
        assert not dialog.left_scroll.verticalScrollBar().isVisible()

    def test_supplies_step_hands_its_spare_height_to_the_lists(self, dialog):
        """Quick Purchase splits its free height between its two lists.

        Step 3 is built the same way: both lists stretch 3 and this page's
        bottom spacer is taken out of the running, so the room the tallest
        step leaves over reaches the lists instead of parking as a dead band
        under them (the old setup kept them at their natural height and left
        ~62-80px of gap below).
        """
        _shown(dialog, 2)
        body = dialog.step_bodies[2]
        supplies = body.itemAt(1).widget()
        packages = body.itemAt(2).widget()
        spacer = body.itemAt(body.count() - 1)
        # The spacer is still the last item of the page...
        assert spacer.spacerItem() is not None
        # ...it just no longer claims any of this page's height...
        assert spacer.geometry().height() <= 4
        # ...so both lists grow past their natural height, and neither one
        # outgrows the viewport it lives in.
        assert supplies.height() > supplies.sizeHint().height()
        assert packages.height() > packages.sizeHint().height()
        viewport = dialog.left_scroll.viewport().height()
        assert supplies.height() <= viewport
        assert packages.height() <= viewport

    def test_the_receipt_card_absorbs_the_billing_steps_room(self, dialog):
        """The receipt grows into the slack, pushing the billing bar down."""
        _shown(dialog, 3)
        # The card grows past its natural height (its items table takes the
        # room), so the bar under it is not left floating above a dead band...
        assert dialog.receipt_frame.height() > \
            dialog.receipt_frame.sizeHint().height()
        body = dialog.step_bodies[3]
        page = dialog._steps_widget.widget(3)
        bar = body.itemAt(body.count() - 2)
        # ...it sits on the page's bottom edge instead.
        assert page.height() - bar.geometry().bottom() \
            <= STEP_CONTENT_MARGIN[3] + 4


class TestRecordBookExamSections:
    """Step 2 is the record-book exam: six collapsible cards, same chrome.

    The sections replaced the old health-stats/tests/treatments/vaccinations/
    medications mixins, so the collapsed-step-height guarantees are re-checked
    against the new cards.
    """

    GROUPS = ("general", "signs", "tests", "vaccinations", "physical",
              "recommended")

    def test_every_section_starts_closed_and_empty(self, dialog):
        for name in self.GROUPS:
            group = dialog._record_cards[name]
            assert group.isChecked() is False
            assert group._section_content.isHidden() is True

    def test_a_closed_section_is_one_line_tall(self, dialog):
        _shown(dialog, 1)
        for name in self.GROUPS:
            group = dialog._record_cards[name]
            # A bare title line. (QGroupBox's own sizeHint under-reports the
            # title by ~11px, so this is bounded rather than compared.)
            assert group.height() <= 48

    def test_leaving_the_exam_step_collapses_its_sections(self, dialog):
        # Advance 0 -> 1 via the real Next button (enabled once the patient is
        # named), expand every section, then leave 1 -> 2 via Next again.
        dialog.show()
        dialog.owner_name.setText("Owner")
        dialog.pet_name.setText("Pet")
        dialog.next_button.click()
        QApplication.processEvents()
        assert dialog._current_step == 1
        for name in self.GROUPS:
            dialog._record_cards[name].setChecked(True)
        assert all(dialog._record_cards[n].isChecked() for n in self.GROUPS)
        QApplication.processEvents()
        expanded_stack = dialog._steps_widget.sizeHint().height()

        dialog.next_button.click()

        assert dialog._current_step == 2
        assert all(dialog._record_cards[n].isChecked() is False for n in self.GROUPS)
        # The collapse must re-measure the (now hidden) Clinical Exam page too:
        # with the stale expanded height the stacked widget stays tall and the
        # sections only *look* collapsed once the user steps back to them.
        page = dialog._steps_widget.widget(1)
        assert page.sizeHint().height() < 480
        assert dialog._steps_widget.sizeHint().height() < expanded_stack

    def test_the_exam_step_no_longer_needs_to_scroll(self, dialog):
        _shown(dialog, 1)
        page = dialog._steps_widget.widget(1)
        # Six closed cards + the consultation toggle still fit without a scroll.
        assert page.sizeHint().height() < 480
        assert not dialog.left_scroll.verticalScrollBar().isVisible()

    def test_ticking_a_section_reveals_and_enables_its_rows(self, dialog):
        group = dialog._record_cards["general"]
        group.setChecked(True)
        QApplication.processEvents()
        assert group._section_content.isHidden() is False
        assert group._section_content.isEnabled() is True
        # ...and unticking hides them again
        group.setChecked(False)
        assert group._section_content.isHidden() is True

    def test_clicking_a_header_expands_and_collapses_the_card(self, dialog):
        """The chevron/summary header is the card's own toggle - no checkbox."""
        group = dialog._record_cards["tests"]
        header = group._section_header
        assert group.isCheckable() is False
        assert group.isChecked() is False
        _click(header)
        QApplication.processEvents()
        assert group.isChecked() is True
        assert group._section_content.isHidden() is False
        assert header.chevron.text() == SECTION_CHEVRON_OPEN
        # Clicking the title label propagates to the header as well
        _click(header.title_label)
        QApplication.processEvents()
        assert group.isChecked() is False
        assert group._section_content.isHidden() is True
        assert header.chevron.text() == SECTION_CHEVRON_CLOSED

    def test_every_section_starts_summarised_as_none(self, dialog):
        for name in self.GROUPS:
            assert dialog._record_cards[name]._section_header.summary_label.text() \
                in ("None", "لا شيء")

    def test_routine_test_rows_can_be_added_and_removed(self, dialog):
        group = dialog._record_cards["tests"]
        group.setChecked(True)
        dialog._add_record_test_row("CBC", "pending")
        assert len(dialog._rec_test_rows) == 1
        assert group._section_header.summary_label.text() in ("1 recorded", "1 مسجلة")

        row, _name, _result = dialog._rec_test_rows[0]
        row.layout().itemAt(2).widget().click()
        assert dialog._rec_test_rows == []
        assert group._section_header.summary_label.text() in ("None", "لا شيء")

    def test_vaccination_checkboxes_update_the_summary(self, dialog):
        assert dialog._rec_vaccine_checkboxes, "a fresh DB seeds vaccines"
        dialog._rec_vaccine_checkboxes[0].setChecked(True)
        assert dialog._record_cards["vaccinations"] \
            ._section_header.summary_label.text() in ("1 selected", "1 محددة")

    def test_general_exam_collects_into_the_record_book_shape(self, dialog):
        dialog._rec_weight_value.setValue(12.5)
        dialog._rec_weight_condition.setCurrentIndex(
            dialog._rec_weight_condition.findData("normal"))
        dialog._rec_temperature_value.setValue(38.4)
        dialog._rec_temperature_status.setCurrentIndex(
            dialog._rec_temperature_status.findData("normal"))
        dialog._rec_neutered.setChecked(True)

        general = dialog.get_clinical_exam_data()["generalPhysicalExamination"]

        assert general["weight"] == {"value": 12.5, "condition": "normal"}
        assert general["temperature"] == {"value": 38.4, "status": "normal"}
        assert general["neutered"] is True

    def test_clinical_signs_collect(self, dialog):
        dialog._rec_energy.setCurrentIndex(dialog._rec_energy.findData("decreased"))
        dialog._rec_water.setCurrentIndex(dialog._rec_water.findData("increased"))
        dialog._rec_feces_status.setCurrentIndex(
            dialog._rec_feces_status.findData("abnormal"))
        dialog._rec_feces_notes.setText("loose")
        dialog._rec_vomiting_present.setChecked(True)
        dialog._rec_vomiting_freq.setText("twice")

        signs = dialog.get_clinical_exam_data()["clinicalSigns"]

        assert signs["energy"] == "decreased"
        assert signs["waterIntake"] == "increased"
        assert signs["feces"] == {"status": "abnormal", "notes": "loose"}
        assert signs["vomiting"] == {"present": True, "frequency": "twice"}

    def test_physical_findings_are_split_into_a_list(self, dialog):
        dialog._rec_lungs_normal.setChecked(False)
        dialog._rec_findings["lungs"].setText("crackles; wheeze")
        dialog._rec_gingivitis.setCurrentIndex(
            dialog._rec_gingivitis.findData("mild"))
        dialog._rec_msk_locations.setText("left hip")

        physical = dialog.get_clinical_exam_data()["physicalExam"]

        assert physical["lungs"] == {"normal": False,
                                     "findings": ["crackles", "wheeze"]}
        assert physical["mouthTeethGums"]["gingivitisSeverity"] == "mild"
        assert physical["musculoskeletal"]["locations"] == ["left hip"]

    def test_recommended_collects_checks_and_notes(self, dialog):
        dialog._rec_recommended["xrays"].setChecked(True)
        dialog._rec_recommended["bloodScreen"].setChecked(True)
        dialog._rec_other.setText("dental diet")

        recommended = dialog.get_clinical_exam_data()["recommendedTestsTreatments"]

        assert recommended["xrays"] is True
        assert recommended["bloodScreen"] is True
        assert recommended["ekg"] is False
        assert recommended["other"] == "dental diet"

    def test_add_test_button_click_does_not_crash(self, dialog):
        card = dialog._record_cards["tests"]
        card.setChecked(True)
        button = next(
            b for b in card.findChildren(QPushButton) if "Add Test" in b.text()
        )
        button.click()
        assert len(dialog._rec_test_rows) == 1

    def test_accept_without_a_pet_name_warns(self, dialog, monkeypatch):
        seen = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            lambda *args, **kwargs: seen.append(args[2]),
        )
        dialog.owner_name.setText("John Doe")
        dialog.handle_accept()
        assert seen == ["No pet selected."]


class TestStepOneIsOneRowOfTwoCards:
    """Step 1 is a single row of two cards - no third full-width band."""

    def test_follow_up_lives_inside_the_visit_card(self, dialog):
        assert dialog.followup_group.parentWidget() is dialog.visit_card
        assert dialog.visit_card.layout().indexOf(dialog.followup_group) > 0

    def test_step_one_body_holds_only_the_card_row_and_a_spacer(self, dialog):
        body = dialog.step_bodies[0]
        assert body.count() == 2
        assert body.itemAt(0).layout() is not None  # the two-card row
        assert body.itemAt(1).spacerItem() is not None


class TestConfirmExistingRecordEditsOnNext:
    """Next on step 1 asks before an existing owner/pet record is rewritten."""

    def _seed_existing_pet(self):
        from src.core.repositories import client_repo, pet_repo
        client_repo.add_client("Mohamed Ali", "01001112223")
        cid = client_repo.get_clients_by_name_exact("Mohamed Ali")[0]["client_id"]
        pet_repo.add_pet("Buddy", "Dog", "Lab", "Male", 12, 5.0, cid)

    def _resolve_pet(self, dialog, owner="Mohamed Ali", pet="Buddy"):
        """Reproduces what Qt does when the two name fields lose focus."""
        dialog.owner_name.setText(owner)
        dialog.owner_name.editingFinished.emit()
        dialog.pet_name.setText(pet)
        dialog.pet_name.editingFinished.emit()
        return dialog._found_pet

    @pytest.fixture
    def asked(self, monkeypatch):
        """Captures the confirmation instead of opening a real modal."""
        calls = []

        def question(parent, title, message, buttons):
            calls.append((title, message))
            return QMessageBox.No

        monkeypatch.setattr(
            "src.ui.dialogs.full_entry_dialog.QMessageBox.question", question
        )
        return calls

    def _answer(self, monkeypatch, reply):
        monkeypatch.setattr(
            "src.ui.dialogs.full_entry_dialog.QMessageBox.question",
            lambda *a, **k: reply,
        )

    def test_a_changed_breed_asks_and_declining_keeps_step_one(
            self, dialog, asked, monkeypatch):
        self._seed_existing_pet()
        assert self._resolve_pet(dialog) is not None
        dialog.breed.setText("Poodle")

        dialog._go_next_step()

        assert len(asked) == 1
        title, message = asked[0]
        assert title == "Confirm Update"
        assert "Pet breed will be updated" in message
        assert dialog._current_step == 0
        assert dialog.breed.text() == "Poodle"

    def test_accepting_the_confirmation_moves_on(self, dialog, monkeypatch):
        self._seed_existing_pet()
        self._resolve_pet(dialog)
        dialog.breed.setText("Poodle")
        self._answer(monkeypatch, QMessageBox.Yes)

        dialog._go_next_step()

        assert dialog._current_step == 1

    @pytest.mark.parametrize("field,widget,value,expected", [
        ("age", "age", 24, "Pet age will be updated"),
        ("gender", "gender", "Female", "Pet gender will be updated"),
        ("species", "species", "Cat", "Pet species will be updated"),
    ])
    def test_each_pet_field_edit_is_listed(
            self, dialog, asked, field, widget, value, expected):
        self._seed_existing_pet()
        self._resolve_pet(dialog)
        target = getattr(dialog, widget)
        if widget == "age":
            target.setValue(value)
        else:
            target.setCurrentText(value)

        dialog._go_next_step()

        assert len(asked) == 1, field
        assert expected in asked[0][1]

    def test_an_untouched_existing_pet_is_not_confirmed(self, dialog, asked):
        self._seed_existing_pet()
        self._resolve_pet(dialog)

        dialog._go_next_step()

        assert asked == []
        assert dialog._current_step == 1

    def test_a_brand_new_pet_is_not_confirmed(self, dialog, asked):
        self._resolve_pet(dialog, owner="Someone New", pet="Snoopy")
        assert dialog._found_pet is None

        dialog._go_next_step()

        assert asked == []
        assert dialog._current_step == 1

    def test_the_confirmation_lists_every_changed_field_at_once(
            self, dialog, asked):
        self._seed_existing_pet()
        self._resolve_pet(dialog)
        dialog.breed.setText("Poodle")
        dialog.age.setValue(30)

        dialog._go_next_step()

        message = asked[0][1]
        assert "Pet breed will be updated" in message
        assert "Pet age will be updated" in message


def _silence_message_boxes(monkeypatch, seen=None):
    """Stubs the modal boxes the dialog opens, recording what was shown."""
    def _record(kind):
        def _hook(*args, **kwargs):
            if seen is not None:
                text = args[2] if len(args) > 2 else ""
                seen.append((kind, str(text)))
        return _hook

    monkeypatch.setattr(QMessageBox, "information", _record("info"))
    monkeypatch.setattr(QMessageBox, "warning", _record("warning"))
    monkeypatch.setattr(QMessageBox, "critical", _record("critical"))
    # The post-save confirmation is a QMessageBox built and exec_()'d on its
    # own, so stub the whole method instead of the static information().
    def _success(self, msg):
        if seen is not None:
            seen.append(("info", str(msg)))

    monkeypatch.setattr(AddFullEntryDialog, "_show_success", _success)


def _consult_fee():
    from src.config.constants import DEFAULT_CONSULT_FEE
    from src.utils.settings_manager import SettingsManager
    return float(SettingsManager.get("consultation_fee", DEFAULT_CONSULT_FEE))


def _receipt_rows(fresh_db):
    """(receipt_id, total, discount, payment_status) for every receipt."""
    from PyQt5.QtSql import QSqlQuery
    query = QSqlQuery(fresh_db)
    query.exec("SELECT receipt_id, total_price, discount, payment_status "
               "FROM receipts ORDER BY receipt_id")
    rows = []
    while query.next():
        rows.append((query.value(0), float(query.value(1)),
                     float(query.value(2)), query.value(3)))
    return rows


class TestBillingBarOnStepFour:
    """Step 4 takes a percentage discount, at the bottom of the page.

    The bar sits under the receipt, is entered as a percentage exactly like the
    Edit Receipt dialog, and saving writes the cash it works out to onto the
    receipt. An Amount Paid field next to it defaults to the discounted total
    and records what was handed over on the spot.
    """

    @staticmethod
    def _on_step(widget, page):
        while widget is not None:
            if widget is page:
                return True
            widget = widget.parentWidget()
        return False

    @staticmethod
    def _fill(dialog, owner="Discount Owner", phone="0111222333", pet="Rex"):
        # visits.pet_id is NOT NULL, so a save always needs a pet.
        dialog.owner_name.setText(owner)
        dialog.phone.setText(phone)
        dialog.pet_name.setText(pet)

    @staticmethod
    def _payment_count(fresh_db):
        from PyQt5.QtSql import QSqlQuery
        query = QSqlQuery(fresh_db)
        query.exec("SELECT COUNT(*) FROM payments")
        assert query.next()
        return int(query.value(0))

    def test_the_discount_bar_sits_under_the_receipt(self, dialog):
        _shown(dialog, 3)
        page = dialog._steps_widget.widget(3)
        body = dialog.step_bodies[3]
        # The page still opens with its form, then the receipt hint...
        assert body.indexOf(dialog.step_forms[3]) == 0
        assert body.indexOf(dialog.receipt_hint_label) == 1
        # ...and the discount bar is below the receipt card, at the bottom.
        assert self._on_step(dialog.discount_percent_spin, page)
        spin = dialog.discount_percent_spin.mapToGlobal(
            dialog.discount_percent_spin.rect().topLeft())
        receipt = dialog.receipt_frame.mapToGlobal(
            dialog.receipt_frame.rect().topLeft())
        assert spin.y() > receipt.y() + dialog.receipt_frame.height()

    def test_the_discount_is_a_percentage_like_the_edit_receipt_dialog(self, dialog):
        spin = dialog.discount_percent_spin
        assert spin.minimum() == 0.0
        assert spin.maximum() == 100.0
        assert spin.suffix().strip() == "%"
        # No cash discount spin: the base class would read one as dollars and
        # subtract the percentage figure from the total.
        assert not hasattr(dialog, "discount_spin")

    def test_a_percentage_discount_lowers_the_total_and_the_receipt(self, dialog):
        from src.utils.formatters import format_currency
        fee = _consult_fee()
        dialog.consult.setChecked(True)
        assert dialog.billing_total_label.text() == format_currency(fee)

        dialog.discount_percent_spin.setValue(10.0)

        cash = round(fee * 0.10, 2)
        assert dialog.billing_total_label.text() == format_currency(fee - cash)
        assert dialog.receipt_total.text() == format_currency(fee - cash)
        assert dialog.receipt_discount.text() == "-" + format_currency(cash)

    def test_the_receipt_subtotal_is_everything_before_the_discount(self, dialog):
        from src.utils.formatters import format_currency
        fee = _consult_fee()
        dialog.consult.setChecked(True)

        # The consultation fee is billed, so it belongs in the Subtotal too -
        # it used to be added straight to the Total, leaving Subtotal - Discount
        # != Total whenever only a consultation was booked.
        assert dialog.receipt_subtotal.text() == format_currency(fee)

        dialog.discount_percent_spin.setValue(10.0)

        cash = round(fee * 0.10, 2)
        assert dialog.receipt_subtotal.text() == format_currency(fee)
        assert dialog.receipt_discount.text() == "-" + format_currency(cash)
        assert dialog.receipt_total.text() == format_currency(fee - cash)

    def test_accept_writes_the_cash_discount_onto_the_receipt(
            self, dialog, fresh_db, monkeypatch):
        seen = []
        _silence_message_boxes(monkeypatch, seen)
        fee = _consult_fee()
        self._fill(dialog)
        dialog.consult.setChecked(True)
        dialog.discount_percent_spin.setValue(10.0)
        cash = round(fee * 0.10, 2)

        dialog.handle_accept()

        rows = _receipt_rows(fresh_db)
        assert len(rows) == 1, rows
        _receipt_id, total, discount, status = rows[0]
        assert total == pytest.approx(fee - cash)
        assert discount == pytest.approx(cash)
        # The default paid amount is the (discounted) total, so the visit is
        # settled at the counter - no trip to the Receipts page afterwards.
        assert status == "Paid"
        assert self._payment_count(fresh_db) == 1
        assert [kind for kind, _ in seen] == ["info"], seen

    def test_amount_paid_defaults_to_the_discounted_total(self, dialog):
        fee = _consult_fee()
        dialog.consult.setChecked(True)
        assert dialog.amount_paid_spin.value() == pytest.approx(fee)

        dialog.discount_percent_spin.setValue(10.0)

        cash = round(fee * 0.10, 2)
        assert dialog.amount_paid_spin.value() == pytest.approx(fee - cash)

    def test_a_custom_paid_amount_is_never_overwritten(self, dialog):
        fee = _consult_fee()
        dialog.consult.setChecked(True)
        dialog.amount_paid_spin.setValue(5.0)
        assert dialog._paid_touched
        dialog.discount_percent_spin.setValue(10.0)

        # The typed figure survives the total changing...
        assert dialog.amount_paid_spin.value() == 5.0
        # ...but the total still clamps what can be handed over.
        cash = round(fee * 0.10, 2)
        assert dialog.amount_paid_spin.maximum() == pytest.approx(fee - cash)

    def test_accept_records_what_the_client_handed_over(
            self, dialog, fresh_db, monkeypatch):
        _silence_message_boxes(monkeypatch)
        fee = _consult_fee()
        self._fill(dialog)
        dialog.consult.setChecked(True)
        dialog.discount_percent_spin.setValue(10.0)
        cash = round(fee * 0.10, 2)
        dialog.amount_paid_spin.setValue(5.0)
        dialog.pay_method_combo.setCurrentIndex(1)  # Card

        dialog.handle_accept()

        rows = _receipt_rows(fresh_db)
        assert len(rows) == 1, rows
        _receipt_id, total, discount, status = rows[0]
        assert total == pytest.approx(fee - cash)
        assert status == "Partial"

        from PyQt5.QtSql import QSqlQuery
        query = QSqlQuery(fresh_db)
        query.exec("SELECT COALESCE(SUM(amount), 0), MAX(payment_method) FROM payments")
        assert query.next()
        assert abs(float(query.value(0)) - 5.0) < 1e-6
        assert query.value(1) == "Card"

    def test_payment_method_defaults_to_cash(self, dialog):
        combo = dialog.pay_method_combo
        assert combo.currentIndex() == 0
        assert dialog.payment_method() == "Cash"
        combo.setCurrentIndex(2)
        assert dialog.payment_method() == "Bank Transfer"

    def test_nothing_billed_records_no_receipt(self, dialog, fresh_db, monkeypatch):
        _silence_message_boxes(monkeypatch)
        self._fill(dialog)
        assert dialog.discount_percent_spin.value() == 0.0

        dialog.handle_accept()

        assert _receipt_rows(fresh_db) == []
        assert self._payment_count(fresh_db) == 0


class TestSuccessBox:
    """The post-save confirmation carries Print (renamed off step 4) + OK."""

    def _spy_box(self, monkeypatch, clicked=None):
        from PyQt5.QtWidgets import QMessageBox as MB
        captured = {}

        class SpyMessageBox(MB):
            def exec_(self):
                captured["box"] = self
                return 0

            def clickedButton(self):
                if clicked is None:
                    return None
                return next(
                    (b for b in self.buttons() if b.text() == clicked), None)

        monkeypatch.setattr("src.ui.dialogs.full_entry_dialog.QMessageBox",
                            SpyMessageBox)
        return captured

    def test_success_box_has_ok_and_print(self, dialog, monkeypatch):
        captured = self._spy_box(monkeypatch)
        # never touch the real printer (QPrinter COM init dies offscreen)
        monkeypatch.setattr(dialog, "_print_receipt", lambda: None)

        dialog._show_success("Record added successfully.")

        box = captured["box"]
        # the built-in OK button + a custom Print button
        assert box.standardButtons() == QMessageBox.Ok
        assert len(box.buttons()) == 2
        assert any(b.text() == "Print" for b in box.buttons())

    def test_print_button_prints_the_receipt(self, dialog, monkeypatch):
        printed = []
        monkeypatch.setattr(dialog, "_print_receipt",
                            lambda: printed.append(1))
        self._spy_box(monkeypatch, clicked="Print")

        dialog._show_success("Record added successfully.")

        assert printed == [1]


class TestPrintButtonAfterSave:
    """The success box's Print button mirrors the Receipts page's
    Print for Client: the client copy, refused until fully paid."""

    def _make_receipt(self, repos, entity_factory, billed=True):
        cid = entity_factory["make_client"]()
        pid = entity_factory["make_pet"](cid, name="Rex")
        items = []
        if billed:
            _, item_name = entity_factory["make_supply"](quantity=10)
            items = [{"item_name": item_name, "quantity": 1, "price": 25.0}]
        return int(repos["visit"].add_visit(
            "2026-09-07 10:00", "Checkup", 1, "", pet_id=pid, items=items))

    def test_print_delegates_to_print_for_client(self, dialog, fresh_db, repos,
                                                 entity_factory, monkeypatch):
        receipt_id = self._make_receipt(repos, entity_factory)
        from src.ui.pages.database_pages.receipts_page import ReceiptInfoDialog
        calls = []
        monkeypatch.setattr(
            ReceiptInfoDialog, "print_for_client",
            lambda self, parent=None: calls.append(parent) or True)

        dialog._saved_receipt_id = receipt_id
        dialog._print_receipt()

        assert calls == [dialog]

    def test_unpaid_receipt_is_denied_and_never_printed(self, dialog, fresh_db, repos,
                                                        entity_factory, monkeypatch):
        receipt_id = self._make_receipt(repos, entity_factory)  # nothing paid
        messages = []
        monkeypatch.setattr(
            QMessageBox, "information",
            lambda parent, title, message, *a, **k: messages.append(message))
        printed = []

        class _SpyPrintDialog:
            def __init__(self, *a, **k):
                printed.append(True)

            def exec_(self):
                return 0

        monkeypatch.setattr(
            "src.ui.pages.database_pages.receipts_page.QPrintDialog",
            _SpyPrintDialog)

        dialog._saved_receipt_id = receipt_id
        dialog._print_receipt()

        assert messages, "the not-fully-paid refusal must reach the user"
        assert "fully paid" in messages[0].lower()
        assert not printed, "an unpaid receipt must never reach the printer"

    def test_no_receipt_falls_back_to_the_step_four_preview(self, dialog, monkeypatch):
        """An unbilled visit has no client copy, so the preview still prints."""
        from src.ui.dialogs.base_clinical_dialog import BaseClinicalDialog
        calls = []
        monkeypatch.setattr(BaseClinicalDialog, "_print_receipt",
                            lambda self: calls.append(1))
        assert dialog._saved_receipt_id is None

        dialog._print_receipt()

        assert calls == [1]


class TestGenderLanguageRoundTrip:
    """The gender combo stores English whatever the display language.

    A translated label used to be written straight into ``pets.gender`` and, on
    restore, ``findText`` could not match the stored English value in Arabic, so
    an existing pet's gender silently reverted to the first item.
    """

    def _seed(self):
        from src.core.repositories import client_repo, pet_repo
        client_repo.add_client("Mohamed Ali", "01001112223")
        cid = client_repo.get_clients_by_name_exact("Mohamed Ali")[0]["client_id"]
        pet_repo.add_pet("Buddy", "Dog", "Lab", "Male", 12, 5.0, cid)

    def test_gender_value_stays_english_when_labels_are_translated(
            self, qapp, fresh_db, monkeypatch):
        from src.core.repositories import package_repo
        package_repo.add_package("Vaccine Bundle", "Annual shots", 40.0)

        import src.ui.dialogs.full_entry_dialog as fed
        monkeypatch.setattr(
            fed, "tr", lambda key, default=None: f"<ar>{key}</ar>")
        from src.ui.dialogs.full_entry_dialog import AddFullEntryDialog

        dlg = AddFullEntryDialog(current_user={"user_id": 1, "username": "admin",
                                               "roles": ["admin"]})
        try:
            # Labels are translated...
            assert dlg.gender.itemText(0).startswith("<ar>")
            # ...but the payload stays English.
            assert [dlg.gender.itemData(i) for i in range(dlg.gender.count())] == \
                ["Male", "Female", "Other"]

            self._seed()
            dlg.owner_name.setText("Mohamed Ali")
            dlg.owner_name.editingFinished.emit()
            dlg.pet_name.setText("Buddy")
            dlg.pet_name.editingFinished.emit()

            # Restore finds the English value behind the Arabic label.
            assert (dlg.gender.currentData() or dlg.gender.currentText()) == "Male"

            dlg.gender.setCurrentIndex(dlg.gender.findData("Female"))
            assert (dlg.gender.currentData() or dlg.gender.currentText()) == "Female"
        finally:
            dlg.deleteLater()
