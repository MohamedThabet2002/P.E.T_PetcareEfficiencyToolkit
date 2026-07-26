"""
Reorder Level Settings Dialog for the PET Application.
Provides a centralized interface to manage global reorder thresholds for inventory items.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox, QPushButton, QHBoxLayout, QLabel

import src.core.repositories.supply_repo as supply_repo
from src.utils.i18n import tr

#==================================== CONSTANTS =======================================================#

REORDER_WINDOW_TABLE_COL_NAMES = ["Category", "Sub-Category", "Item Name", "Reorder Level"]
REORDER_WINDOW_DIMENSIONS_WIDTH = 600
REORDER_WINDOW_DIMENSIONS_HEIGHT = 600
REORDER_WINDOW_TABLE_COL_COUNT = 4
REORDER_WINDOW_SAVE_BTN_WIDTH = 120
REORDER_WINDOW_CLOSE_BTN_WIDTH = 100

#============================================== CODE =====================================================#

class ReorderSettingsDialog(QDialog):
    """
    A dialog to manage global reorder levels for each unique item in the inventory.
    Allows setting thresholds that apply to the sum of all batches for an item name.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Inventory Reorder Settings"))
        self.resize(REORDER_WINDOW_DIMENSIONS_WIDTH, REORDER_WINDOW_DIMENSIONS_HEIGHT)
        self.setup_ui()
        self.refresh_list()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        header = QLabel(f"<b>{tr('Manage Global Reorder Levels')}</b>")
        header.setStyleSheet("font-size: 14px; margin-bottom: 5px;")
        layout.addWidget(header)
        
        help_text = QLabel(tr("Set the minimum total quantity (across all batches) for each item."))
        help_text.setStyleSheet("color: #7F8C8D; margin-bottom: 10px;")
        layout.addWidget(help_text)
        
        self.table = QTableWidget()
        self.table.setColumnCount(REORDER_WINDOW_TABLE_COL_COUNT)
        self.table.setHorizontalHeaderLabels([tr(col) for col in REORDER_WINDOW_TABLE_COL_NAMES])
        for i in range(REORDER_WINDOW_TABLE_COL_COUNT):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch) # make the 2nd column stretch
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        
        footer = QHBoxLayout()
        self.status_msg = QLabel("")
        footer.addWidget(self.status_msg)
        footer.addStretch()
        
        save_btn = QPushButton(tr("Save Changes"))
        save_btn.clicked.connect(self.save_all)
        footer.addWidget(save_btn)
        
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        
        layout.addLayout(footer)

    def refresh_list(self):
        items = supply_repo.get_all_unique_item_names()
        levels = supply_repo.get_all_reorder_levels()
        
        self.table.setRowCount(len(items))
        for i, (name, cat, sub) in enumerate(items):
            # Category
            cat_item = QTableWidgetItem(tr(cat))
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, cat_item)
            
            # Sub-Category
            sub_item = QTableWidgetItem(tr(sub))
            sub_item.setFlags(sub_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 1, sub_item)
            
            # Item Name
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 2, name_item)
            
            spin = QSpinBox()
            spin.setRange(0, 99999)
            spin.setValue(int(levels.get(name, 0)))
            spin.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(i, 3, spin)

    def save_all(self):
        for i in range(self.table.rowCount()):
            name = self.table.item(i, 2).text()
            level = self.table.cellWidget(i, 3).value()
            supply_repo.set_reorder_level(name, level)
        
        self.status_msg.setText(tr("✓ Saved successfully"))
        self.status_msg.setStyleSheet("color: #2ECC71;")

