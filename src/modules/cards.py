
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel,
    QGridLayout, QPushButton, QButtonGroup
)
from PyQt5.QtCore import Qt

from src.utils.i18n import tr

CARD_PERIOD_BUTTON_SIZE = (36, 30)

def create_info_card_with_periods(self, title_text: str, period_key: str, callback, card_height: int = 50):
    """Helper to create a KPI card with period selection buttons (Day, Week, etc)."""
    card = QFrame()
    card.setProperty("class", "info-card")
    layout = QGridLayout(card)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    
    header = QWidget()
    header.setProperty("class", "info-card-header")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(10)
    
    title = QLabel(title_text)
    title.setProperty("class", "info-card-title")
    header_layout.addWidget(title)
    header_layout.addStretch()
    
    value_label = QLabel("0")
    value_label.setAlignment(Qt.AlignCenter)
    value_label.setFixedHeight(card_height)
    value_label.setProperty("class", "info-card-value")
    
    period_container = QFrame()
    period_container.setProperty("class", "timestamp-button-group")
    period_layout = QHBoxLayout(period_container)
    period_layout.setContentsMargins(0, 0, 0, 0)
    period_layout.setSpacing(0)
    
    group = QButtonGroup(self)
    period_buttons = []
    for period_name, label in [("Day", "D"), ("Week", "W"), ("Month", "M"), ("Year", "Y"), ("All", "All")]:
        btn = QPushButton(tr(label))
        btn.setCheckable(True)
        btn.setFixedSize(*CARD_PERIOD_BUTTON_SIZE)
        btn.setProperty("class", "timestamp-button-group")
        btn.setCursor(Qt.PointingHandCursor)
        if self.periods.get(period_key) == period_name:
            btn.setChecked(True)
        group.addButton(btn)
        period_layout.addWidget(btn)
        btn.clicked.connect(lambda _, p=period_name, k=period_key, l=value_label: callback(k, p, l))
        period_buttons.append((btn, label))
    if hasattr(self, "period_buttons") and isinstance(self.period_buttons, list):
        self.period_buttons.extend(period_buttons)
    
    header_layout.addWidget(period_container, alignment=Qt.AlignRight)
    layout.addWidget(header, 0, 0, 1, 2)
    layout.addWidget(value_label, 1, 0, 1, 2)
    return card, value_label, title

def create_info_card_day(self, title_text: str, period_key: str, callback=None, card_height: int = 44, period: str = "Month"):
    """KPI card for a fixed period, with a month-over-month trend chip under the value."""
    card = QFrame()
    card.setProperty("class", "info-card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    header = QWidget()
    header.setProperty("class", "info-card-header")
    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(10)

    title = QLabel(title_text)
    title.setProperty("class", "info-card-title")
    header_layout.addWidget(title)
    header_layout.addStretch()

    value_label = QLabel("0")
    value_label.setAlignment(Qt.AlignCenter)
    value_label.setFixedHeight(card_height)
    value_label.setProperty("class", "info-card-value")

    chip = QFrame()
    chip.setProperty("class", "trend-chip")
    chip_layout = QHBoxLayout(chip)
    chip_layout.setContentsMargins(8, 0, 8, 8)
    chip_layout.setSpacing(6)

    pill = QFrame()
    pill.setFrameShape(QFrame.NoFrame)
    pill.setProperty("class", "trend-pill")
    pill.setProperty("state", "neutral")
    pill_layout = QHBoxLayout(pill)
    pill_layout.setContentsMargins(8, 2, 8, 2)
    pill_layout.setSpacing(4)

    arrow = QLabel("●")
    arrow.setProperty("class", "trend-arrow")
    arrow.setProperty("state", "neutral")
    delta = QLabel("")
    delta.setProperty("class", "trend-delta")
    delta.setProperty("state", "neutral")
    pct = QLabel("")
    pct.setProperty("class", "trend-pct")
    pct.setProperty("state", "neutral")
    pill_layout.addWidget(arrow)
    pill_layout.addWidget(delta)
    pill_layout.addWidget(pct)

    caption = QLabel(tr("vs last month"))
    caption.setProperty("class", "trend-caption")

    chip_layout.addStretch()
    chip_layout.addWidget(pill)
    chip_layout.addWidget(caption)
    chip_layout.addStretch()

    layout.addWidget(header)
    layout.addWidget(value_label)
    layout.addWidget(chip)

    if callback:
        callback(period_key, period, value_label)

    trend = {
        "chip": chip,
        "pill": pill,
        "arrow": arrow,
        "delta": delta,
        "pct": pct,
        "caption": caption,
    }
    return card, value_label, title, trend

def on_info_card_period_changed(self, period_key, new_period, label_obj, repo_func, formatter=str):
    """Unified handler for updating KPI values based on period selection."""
    self.periods[period_key] = new_period
    label_obj.setText(formatter(repo_func(new_period)))