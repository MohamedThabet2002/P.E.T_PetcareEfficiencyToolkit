"""
Inventory Management module for the PET Application.
Handles categorized stock tracking with low-stock alerts.

Note: Tabs are generated dynamically from the 'categories' and 'subcategories' database tables.
"""

import os

from PyQt5.QtWidgets import (
    QComboBox, QLineEdit, QTableWidgetItem, 
    QDialog, QFormLayout, QDateEdit, QSpinBox, QListView,
    QDoubleSpinBox, QDialogButtonBox, QMessageBox,
    QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea, QWidget, QLabel, QFrame
)
from PyQt5.QtCore import Qt, QDate, QSize
from PyQt5.QtGui import QColor, QIcon

from src.config import (
    ICONS_DIR, DEFAULT_EXPIRY_YEARS
)
from src.ui.themes.color_palettes import get_active_palette, ThemeManager
import src.core.repositories.sales_repo as sales_repo
import src.core.repositories.supply_repo as supply_repo
from src.ui.base_page import BaseEntityPage
from src.utils.i18n import tr

#=========================================== CONSTANTS ===================================================#

# --- Supplies Tuning Constants ---
SUPPLY_CONFIG = {
    "DIALOG_SIZE": (400, 390),
    "BULK_WINDOW_SIZE": (800, 600),
    "BULK_ICO": "buy-ico.png",
    "DATE_FIELD_WIDTH": 120,
    "SUPPLIER_FIELD_WIDTH": 250,
    "DELETE_BTN_SIZE": (30, 30)
}

SUPPLY_COLUMN_MAP = [
    ("ID",             "id",               0),
    ("Item Name",      "item_name",        200),
    ("Sub-Category",   "sub_category",     150),
    ("Purchase Date",  "purchase_date",    150),
    ("Expiry Date",    "expiry_date",      150),
    ("Buy Price",      "buy_price",        120),
    ("Sell Price",     "sell_price",       120),
    ("Quantity",       "quantity",         100),
    ("Supplier",       "supplier",         150),
    ("Receipt ID",     "receipt_id",       100)
]

BULK_PURCHASE_ROW_MAP = [
    ("Category", "category", 120),
    ("Sub-Category", "sub_category", 120),
    ("Item Name", "item_name", 200),
    ("Buy Price", "buy_price", 80),
    ("Sell Price", "sell_price", 80),
    ("Quantity", "quantity", 70)
]

#============================================== CODE =====================================================#

class BulkPurchaseDialog(QDialog):
    """
    A dialog for recording multiple supply purchases or restocks at once.
    Similar to the Visit Supplies section but for inventory management.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Bulk Inventory Purchase"))
        self.setMinimumSize(*SUPPLY_CONFIG["BULK_WINDOW_SIZE"])
        self._rows = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header Section: Global Info
        header = QFrame()
        header_layout = QHBoxLayout(header)
        self.purchase_date = QDateEdit(calendarPopup=True)
        self.purchase_date.setDate(QDate.currentDate())
        self.purchase_date.setFixedWidth(SUPPLY_CONFIG["DATE_FIELD_WIDTH"])
        self.supplier = QLineEdit()
        self.supplier.setFixedWidth(SUPPLY_CONFIG["SUPPLIER_FIELD_WIDTH"])
        self.supplier.setPlaceholderText(tr("Common Supplier (optional)"))
        
        header_layout.addWidget(QLabel(tr("Purchase Date:")))
        header_layout.addWidget(self.purchase_date)
        header_layout.addStretch()
        header_layout.addWidget(QLabel(tr("Default Supplier:")))
        header_layout.addWidget(self.supplier)
        header_layout.addStretch()
        
        add_row_btn = QPushButton(tr("+ Add Row"))
        add_row_btn.clicked.connect(self._add_row)
        header_layout.addWidget(add_row_btn)
        
        layout.addWidget(header)

        # Middle Section: Scrollable Rows
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.rows_layout = QVBoxLayout(self.container)
        self.rows_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

        # Table-like Headers
        headers_frame = QFrame()
        h_layout = QHBoxLayout(headers_frame)
        h_layout.setContentsMargins(20, 0, 110, 0)  # Align with row layout
        h_layout.setSpacing(25)
        for header_text, _, width in BULK_PURCHASE_ROW_MAP:
            lbl = QLabel(f"<b>{tr(header_text)}</b>")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedWidth(width)
            h_layout.addWidget(lbl)
        layout.insertWidget(1, headers_frame)

        # Bottom Section: Buttons
        footer_layout = QHBoxLayout()
        self.total_label = QLabel(tr("<b>Total Purchase: ${total:,.2f}</b>"))
        self.total_label.setStyleSheet("font-size: 14px; color: #2ECC71; margin-left: 10px;")
        footer_layout.addWidget(self.total_label)
        footer_layout.addStretch()

        self.buttons = QDialogButtonBox()
        ok_button = self.buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = self.buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self._handle_accept)
        self.buttons.rejected.connect(self.reject)
        footer_layout.addWidget(self.buttons)
        layout.addLayout(footer_layout)

        # Initial row
        self._add_row()

    def _setup_styled_combo(self, width, editable=True):
        """Helper to create search-ready, styled combo boxes."""
        cb = QComboBox()
        cb.setFixedWidth(width)
        cb.setView(QListView())
        cb.view().window().setAttribute(Qt.WA_TranslucentBackground)
        cb.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        if editable:
            cb.setEditable(True)
            cb.setInsertPolicy(QComboBox.NoInsert)
            if cb.completer():
                cb.completer().setFilterMode(Qt.MatchContains)
        return cb

    def _add_row(self):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 2, 0, 2)

        cat = self._setup_styled_combo(BULK_PURCHASE_ROW_MAP[0][2])
        cat.addItems(supply_repo.get_all_categories())

        sub = self._setup_styled_combo(BULK_PURCHASE_ROW_MAP[1][2])
        name = self._setup_styled_combo(BULK_PURCHASE_ROW_MAP[2][2])
        
        buy = QDoubleSpinBox(); buy.setMaximum(9999); buy.setFixedWidth(BULK_PURCHASE_ROW_MAP[3][2])
        sell = QDoubleSpinBox(); sell.setMaximum(9999); sell.setFixedWidth(BULK_PURCHASE_ROW_MAP[4][2])
        qty = QSpinBox(); qty.setMaximum(9999); qty.setFixedWidth(BULK_PURCHASE_ROW_MAP[5][2]); qty.setValue(1)
        
        del_btn = QPushButton(tr("✕"))
        del_btn.setFixedSize(*SUPPLY_CONFIG["DELETE_BTN_SIZE"])
        del_btn.setProperty("action", "delete")

        def update_names():
            current_text = name.currentText()
            name.clear()
            items = supply_repo.get_items_by_subcategory(cat.currentText(), sub.currentText())
            name.addItems(items)
            name.setEditText(current_text)

        def update_subs():
            sub.clear()
            sub.addItems(supply_repo.get_subcategories_by_category(cat.currentText()))
            update_names()

        cat.currentTextChanged.connect(update_subs)
        sub.currentTextChanged.connect(update_names)
        update_subs()

        # Connect value changes to update the total price indicator
        buy.valueChanged.connect(self._update_total)
        qty.valueChanged.connect(self._update_total)

        row_data = (cat, sub, name, buy, sell, qty)
        del_btn.clicked.connect(lambda: self._remove_row(row_widget, row_data))

        for w in [cat, sub, name, buy, sell, qty, del_btn]:
            row_layout.addWidget(w)
        
        self.rows_layout.addWidget(row_widget)
        self._rows.append(row_data)
        self._update_total()

    def _remove_row(self, widget, data):
        if len(self._rows) > 1:
            self._rows.remove(data)
            widget.deleteLater()
            self._update_total()

    def _handle_accept(self):
        """Validates that all rows have an item name before accepting."""
        for i, row in enumerate(self._rows):
            name_widget = row[2] # item_name QComboBox
            if not name_widget.currentText().strip():
                QMessageBox.warning(self, tr("Validation Error"), tr("Item name is required for row {row}.").format(row=i + 1))
                name_widget.setFocus()
                return
        self.accept()

    def _update_total(self):
        """Calculates and updates the total cost of the bulk purchase."""
        total = 0.0
        for row in self._rows:
            # row data format: (cat, sub, name, buy, sell, qty)
            total += row[3].value() * row[5].value()
        self.total_label.setText(tr("<b>Total Purchase: ${total:,.2f}</b>").format(total=total))

    def get_data(self):
        """Returns formatted list of items for processing."""
        results = []
        global_date = self.purchase_date.date().toString(Qt.ISODate)
        global_supplier = self.supplier.text().strip().title()
        
        for cat, sub, name, buy, sell, qty in self._rows:
            if name.currentText().strip():
                results.append({
                    'category': cat.currentText(),
                    'sub_category': sub.currentText(),
                    'item_name': name.currentText().strip().title(),
                    'buy_price': buy.value(),
                    'sell_price': sell.value(),
                    'quantity': qty.value(),
                    'purchase_date': global_date,
                    'expiry_date': QDate.fromString(global_date, Qt.ISODate).addYears(DEFAULT_EXPIRY_YEARS).toString(Qt.ISODate),
                    'supplier': global_supplier if global_supplier else None
                })
        return results

class SuppliesPage(BaseEntityPage):
    """
    Page for managing clinic inventory. 
    Organizes supplies into categories using a tabbed view with CRUD and search functionality.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._setup_ui()
        
        # Connect tab change signal to refresh the active tab (standardizing with ClientsPage)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        # Re-apply row highlights when theme changes
        ThemeManager.instance().theme_changed.connect(self.retranslate_ui)
    
    def _setup_ui(self):
        """Initializes the UI layout and dynamically creates category tabs."""
        # Add Bulk Purchase button to the corner of the tab widget
        self.bulk_purchase_btn = QPushButton(tr(" Bulk Inventory Purchase "))
        self.bulk_purchase_btn.setIcon(QIcon(os.path.join(ICONS_DIR, SUPPLY_CONFIG["BULK_ICO"])))
        self.bulk_purchase_btn.setCursor(Qt.PointingHandCursor)
        self.bulk_purchase_btn.clicked.connect(self.open_bulk_purchase_dialog)
        
        self.tabs.setCornerWidget(self.bulk_purchase_btn, Qt.TopRightCorner)
        self.tabs.setUsesScrollButtons(True)

        # Placeholder for empty inventory structure
        self.placeholder_widget = QWidget()
        p_layout = QVBoxLayout(self.placeholder_widget)
        self.placeholder_label = QLabel(tr("No inventory categories found. Please add some in Settings > Custom Lists."))
        self.placeholder_label.setAlignment(Qt.AlignCenter)
        self.placeholder_label.setStyleSheet("font-size: 16px; color: #7f8c8d; line-height: 150%;")
        p_layout.addStretch()
        p_layout.addWidget(self.placeholder_label)
        p_layout.addStretch()
        self.main_layout.addWidget(self.placeholder_widget)
        
        self.rebuild_tabs()

    def rebuild_tabs(self):
        """Generates tabs dynamically based on categories in the database."""
        self.clear_tabs()
        categories = supply_repo.get_all_categories()

        if not categories:
            self.tabs.hide()
            self.placeholder_widget.show()
            return

        self.tabs.show()
        self.placeholder_widget.hide()

        header_keys = [tr(col[0]) for col in SUPPLY_COLUMN_MAP]
        widths = [col[2] for col in SUPPLY_COLUMN_MAP]
        for category in categories:
            subs = supply_repo.get_subcategories_by_category(category)
            self.create_tab(
                name=category,
                headers=header_keys,
                filter_items=["All"] + subs,
                add_callback=lambda _, c=category: self.add_supply_dialog(c),
                delete_callback=lambda _, c=category: self.delete_selected_supply(c),
                refresh_callback=lambda text, c=category: self.refresh_category_table(c, text),
                hide_cols=[0],
                col_widths=widths
            )
            self.refresh_category_table(category, "")
    
    def retranslate_ui(self):
        """Updates UI text for all tabs and headers when language changes."""
        self.rebuild_tabs()
        self.bulk_purchase_btn.setText(tr(" Bulk Inventory Purchase "))
        
    def on_row_double_clicked(self, category, row):
        """Triggers the edit flow when a supply row is double-clicked."""
        self.edit_supply_dialog(category, row)

    def on_tab_changed(self, index):
        """Refreshes the data when switching between tabs."""
        if 0 <= index < len(self._tab_configs):
            category = self._tab_configs[index]["name_key"]
            if category in self.tables:
                search_text = self.search_bars[category].text()
                self.refresh_category_table(category, search_text)

    def open_bulk_purchase_dialog(self):
        """Opens the multi-item entry dialog and processes the results."""
        dialog = BulkPurchaseDialog(self)
        if dialog.exec() == QDialog.Accepted:
            items = dialog.get_data()
            if not items:
                return

            success_count = 0
            shared_rid = None

            for item in items:
                # Reuse existing repo logic: check for duplicates then add/update
                existing = supply_repo.get_existing_supply(
                    item['item_name'], item['category'], item['sub_category'], 
                    item['purchase_date'], item['expiry_date'], item['supplier']
                )

                if existing:
                    # Bulk restock updates qty and prices automatically
                    updated, exp_details = supply_repo.update_supply_stock(
                        existing["id"], existing["quantity"] + item['quantity'],
                        item['buy_price'], item['sell_price']
                    )
                    if updated and exp_details:
                        shared_rid = sales_repo.log_supply_purchase_expense(**exp_details, receipt_id=shared_rid)
                        if shared_rid: supply_repo.update_supply_receipt(existing["id"], shared_rid)
                    success_count += 1
                else:
                    sid, exp_details = supply_repo.add_supply(**item)
                    if sid:
                        if exp_details:
                            shared_rid = sales_repo.log_supply_purchase_expense(**exp_details, receipt_id=shared_rid)
                            if shared_rid: supply_repo.update_supply_receipt(sid, shared_rid)
                        success_count += 1
            
            if success_count > 0:
                QMessageBox.information(self, tr("Success"), tr("Successfully processed {count} items.").format(count=success_count))
                self.refresh_all_tabs()
                self.data_changed.emit()

    def add_supply_dialog(self, category):
        """Opens a dialog to add a new inventory item."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Add {category}").format(category=tr(category)))
        dialog.setFixedSize(*SUPPLY_CONFIG["DIALOG_SIZE"])
        layout = QFormLayout(dialog)
        
        item_name = QLineEdit()
        sub_category = QComboBox()
        sub_category.setView(QListView())
        sub_category.view().window().setAttribute(Qt.WA_TranslucentBackground)
        sub_category.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        sub_category.setEditable(True)
        sub_category.setInsertPolicy(QComboBox.NoInsert)
        sub_category.completer().setFilterMode(Qt.MatchContains)
        sub_category.setPlaceholderText(tr("Select Sub-Category..."))
        sub_category.addItems(supply_repo.get_subcategories_by_category(category))
        sub_category.setCurrentIndex(-1)
        purchase_date = QDateEdit(calendarPopup=True)
        purchase_date.setDate(QDate.currentDate())
        expiry_date = QDateEdit(calendarPopup=True)
        expiry_date.setDate(QDate.currentDate().addYears(DEFAULT_EXPIRY_YEARS))
        buy_price = QDoubleSpinBox(); buy_price.setMaximum(99999.99); buy_price.setSuffix(" $")
        sell_price = QDoubleSpinBox(); sell_price.setMaximum(99999.99); sell_price.setSuffix(" $")
        
        quantity = QSpinBox(); quantity.setMaximum(99999)
        supplier = QLineEdit()
        
        layout.addRow(tr("Item Name*:"), item_name)
        layout.addRow(tr("Sub-Category*:"), sub_category)
        layout.addRow(tr("Purchase Date:"), purchase_date)
        layout.addRow(tr("Expiry Date:"), expiry_date)
        layout.addRow(tr("Buy Price:"), buy_price)
        layout.addRow(tr("Sell Price:"), sell_price)
        layout.addRow(tr("Quantity:"), quantity)
        layout.addRow(tr("Supplier:"), supplier)
        # Dialog box button to add or cancel
        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        
        def handle_accept():
            if not item_name.text().strip():
                QMessageBox.warning(dialog, tr("Input Error"), tr("Item name is required for row {row}."))
                return
            
            if sub_category.currentIndex() == -1:
                QMessageBox.warning(dialog, tr("Input Error"), tr("Sub Category is required."))
                return
            
            # Extract values for checking
            name_val = item_name.text().strip().title()
            sub_val = sub_category.currentText()
            p_date_val = purchase_date.date().toString(Qt.ISODate)
            e_date_val = expiry_date.date().toString(Qt.ISODate)
            buy_val = buy_price.value()
            sell_val = sell_price.value()
            qty_val = quantity.value()
            supplier_val = supplier.text().strip().title() or None
            
            # Check for existing supply
            existing = supply_repo.get_existing_supply(name_val, category, sub_val, p_date_val, e_date_val, supplier_val)
            
            if existing:
                target_buy = None
                target_sell = None
                
                if buy_val != existing["buy_price"] or sell_val != existing["sell_price"]:
                    reply = QMessageBox.question(dialog, tr("Duplicate Found"), tr("An existing supply was found. The quantity will be added. Do you want to update the price values as well?"), QMessageBox.Yes | QMessageBox.No)
                    if reply == QMessageBox.Yes:
                        target_buy = buy_val
                        target_sell = sell_val
                
                updated, expense_details = supply_repo.update_supply_stock(
                    existing["id"],
                    existing["quantity"] + qty_val,
                    target_buy,
                    target_sell,
                    purchase_date=p_date_val
                )
                
                if not updated:
                    QMessageBox.critical(dialog, tr("Error"), tr("Failed to update supply stock."))
                    return
                
                if expense_details:
                    res_rid = sales_repo.log_supply_purchase_expense(**expense_details)
                    if not res_rid:
                            QMessageBox.warning(dialog, tr("Warning"), tr("Stock updated, but failed to log expense record."))
                QMessageBox.information(dialog, tr("Update"), tr("Successfully added {qty} to existing stock.").format(qty=qty_val))
                dialog.accept() # Close dialog after update attempt
            else:
                # Add as new record if no match found
                supply_id, expense_details = supply_repo.add_supply(
                    name_val,
                    category,
                    sub_val,
                    p_date_val,
                    e_date_val,
                    buy_val,
                    sell_val,
                    qty_val,
                    supplier_val
                )
                if supply_id is not None:
                    if expense_details:
                        res_rid = sales_repo.log_supply_purchase_expense(**expense_details)
                    if not res_rid:
                        QMessageBox.warning(dialog, tr("Warning"), tr("Stock updated, but failed to log expense record."))
                    supply_repo.update_supply_receipt(supply_id, res_rid)
                            
                    QMessageBox.information(dialog, tr("Success"), tr("{name} added to {category}").format(name=name_val, category=tr(category)))
                    dialog.accept()
                else:
                    QMessageBox.critical(dialog, tr("Error"), tr("Failed to add new supply."))
            
            self.refresh_category_table(category, "")
            self.data_changed.emit()
        
        layout.addWidget(buttons)
        buttons.accepted.connect(handle_accept)
        buttons.rejected.connect(dialog.reject)
        
        dialog.exec()
    
    def edit_supply_dialog(self, category, row):
        """Opens a dialog to edit an existing inventory item."""
        table = self.tables[category]
        supply_id = int(table.item(row, 0).text())
        
        # Fetch item from database to ensure fresh data
        items = supply_repo.search_supplies(category=category)
        data = next((i for i in items if i["id"] == supply_id), None)
        if not data: return

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Edit {item}").format(item=data['item_name']))
        dialog.setFixedSize(*SUPPLY_CONFIG["DIALOG_SIZE"])
        layout = QFormLayout(dialog)

        name = QLineEdit(data['item_name'])
        sub = QComboBox()
        sub.setView(QListView())
        sub.view().window().setAttribute(Qt.WA_TranslucentBackground)
        sub.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        sub.setEditable(True)
        sub.setInsertPolicy(QComboBox.NoInsert)
        sub.completer().setFilterMode(Qt.MatchContains)
        sub.addItems(supply_repo.get_subcategories_by_category(category))
        sub.setCurrentText(data['sub_category'])
        p_date = QDateEdit(QDate.fromString(data['purchase_date'], Qt.ISODate), calendarPopup=True)
        e_date = QDateEdit(QDate.fromString(data['expiry_date'], Qt.ISODate) if data['expiry_date'] else QDate.currentDate(), calendarPopup=True)
        buy = QDoubleSpinBox(); buy.setMaximum(99999); buy.setValue(data['buy_price'])
        sell = QDoubleSpinBox(); sell.setMaximum(99999); sell.setValue(data['sell_price'])
        qty = QSpinBox(); qty.setMaximum(99999); qty.setValue(data['quantity'])
        supplier = QLineEdit(data['supplier'] or "")

        layout.addRow(tr("Item Name"), name); layout.addRow(tr("Sub-Category"), sub); layout.addRow(tr("Purchase Date"), p_date)
        layout.addRow(tr("Expiry Date"), e_date); layout.addRow(tr("Buy Price"), buy); layout.addRow(tr("Sell Price"), sell)
        layout.addRow(tr("Quantity"), qty); layout.addRow(tr("Supplier"), supplier)

        buttons = QDialogButtonBox()
        ok_button = buttons.addButton(tr("OK"), QDialogButtonBox.AcceptRole)
        cancel_button = buttons.addButton(tr("Cancel"), QDialogButtonBox.RejectRole)
        def handle_save():
            if supply_repo.update_supply(supply_id, name.text().strip().title(), category, sub.currentText(), p_date.date().toString(Qt.ISODate),
                                         e_date.date().toString(Qt.ISODate), buy.value(), sell.value(), qty.value(), supplier.text().strip()):
                self.refresh_category_table(category, ""); self.data_changed.emit(); dialog.accept()

        layout.addWidget(buttons)
        buttons.accepted.connect(handle_save); buttons.rejected.connect(dialog.reject); dialog.exec()

    def refresh_all_tabs(self):
        """Refreshes the data in all supply category tables."""
        for category in supply_repo.get_all_categories():
            # Refresh using an empty string for the search text to show all items
            self.refresh_category_table(category, "")
    
    def refresh_category_table(self, category, text):
        """Fetches filtered data and populates the specific category table."""
        selected_filter = self.filters[category].currentText()
        results = supply_repo.search_supplies(category, text, selected_filter)
        
        # Get aggregated stock info to determine highlighting
        reorder_levels = supply_repo.get_all_reorder_levels()
        total_quantities = supply_repo.get_total_quantities_by_item()
        
        table = self.tables[category]
        palette = get_active_palette()
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row_data in results:
            item_name = row_data.get("item_name")
            total_qty = total_quantities.get(item_name, 0)
            reorder = reorder_levels.get(item_name, 0)
            
            # Determine row highlighting once per row
            bg_color = None
            if total_qty == 0:
                bg_color = palette.qcolor("stock_out")
            elif total_qty <= reorder:
                bg_color = palette.qcolor("stock_low")
            
            row = table.rowCount()
            table.insertRow(row)
            
            for col, (_, key, _) in enumerate(SUPPLY_COLUMN_MAP):
                item = QTableWidgetItem()
                # Use .get() to prevent crashes if a key is missing in the result set
                val = row_data.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    item.setData(Qt.DisplayRole, val)
                else:
                    item.setText(str(val) if val is not None else "")
                
                if bg_color:
                    item.setBackground(bg_color)
                    # Ensure text is readable on the colored background
                    item.setForeground(palette.qcolor("bg_surface", "#FFFFFF")) 
                
                table.setItem(row, col, item)
                
        table.setSortingEnabled(True)
    
    def delete_selected_supply(self, category):
        """Deletes the selected supply record after confirmation."""
        table = self.tables[category]
        row = table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Selection Required"), tr("Please select a supply to delete."))
            return
            
        supply_id = table.item(row, 0).text()
        item_name = table.item(row, 1).text()
        
        reply = QMessageBox.question(   self, tr("Confirm Delete"),
                                        tr("Delete '{item}' from {category}?").format(item=item_name, category=tr(category)),
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            if supply_repo.delete_supply(supply_id):
                self.refresh_category_table(category, "")
                self.data_changed.emit()
